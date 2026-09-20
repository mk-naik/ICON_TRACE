import os
import time
import socket
import struct
import secrets
import hmac
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash, check_password_hash

# Config Overrides for testing
MAX_FAILS = int(os.environ.get("ICON_AUTH_MAX_FAILS", "5"))
LOCK_SECONDS = int(os.environ.get("ICON_AUTH_LOCK_SECONDS", "300"))
NTP_SERVER = os.environ.get("ICON_NTP_SERVER", "pool.ntp.org")

# Roles rank
ROLE_RANK = {
    "Super Admin": 3,
    "Admin": 2
}
def get_rank(role):
    return ROLE_RANK.get(role, 1)

class KeyMissing(Exception):
    pass

class AuthError(Exception):
    pass

def _now(now=None):
    return int(now if now is not None else time.time())

# Ensure we use O_CREAT | O_EXCL for the key
def _get_key_path():
    db_file = os.environ.get("ICON_DB_FILE", "icontrace.db")
    if os.path.isabs(db_file):
        return os.path.join(os.path.dirname(db_file), ".icon_totp_key")
    return os.path.join(os.path.dirname(os.path.abspath(db_file)), ".icon_totp_key")

def _load_or_create_key():
    p = _get_key_path()
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            key = Fernet.generate_key()
            os.write(fd, key)
        finally:
            os.close(fd)
        return key
    except FileExistsError:
        try:
            with open(p, "rb") as f:
                return f.read().strip()
        except FileNotFoundError:
            raise KeyMissing("Key file missing during read.")

def get_fernet():
    key = _load_or_create_key()
    if not key:
        raise KeyMissing("Key is empty.")
    try:
        return Fernet(key)
    except Exception as e:
        raise KeyMissing(f"Invalid key format: {e}")

def encrypt_secret(secret_str):
    if not secret_str: return None
    return get_fernet().encrypt(secret_str.encode("utf-8")).decode("utf-8")

def decrypt_secret(enc_str):
    if not enc_str: return None
    try:
        return get_fernet().decrypt(enc_str.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise KeyMissing("Cannot decrypt secret, key might be wrong.")

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    user_id INTEGER PRIMARY KEY,
    login_id TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    pw_hash TEXT,
    totp_secret_enc TEXT,
    totp_pending_enc TEXT,
    totp_last_step INTEGER NOT NULL DEFAULT 0,
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    must_reenrol INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS auth_recovery_code (
    code_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    used_at INTEGER
);

CREATE TABLE IF NOT EXISTS auth_enrol_token (
    token_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);

CREATE TABLE IF NOT EXISTS auth_backup_window (
    window_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    opened_by TEXT NOT NULL,
    opened_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);

CREATE TABLE IF NOT EXISTS auth_event (
    event_id INTEGER PRIMARY KEY,
    at INTEGER NOT NULL,
    login_id TEXT NOT NULL,
    event TEXT NOT NULL,
    ip TEXT,
    detail TEXT
);
"""

def ensure_schema(cur):
    for stmt in AUTH_SCHEMA.strip().split(";"):
        if stmt.strip():
            cur.execute(stmt)

def log_event(cur, login_id, event, ip=None, detail=None, now=None):
    cur.execute("INSERT INTO auth_event (at, login_id, event, ip, detail) VALUES (%s, %s, %s, %s, %s)",
                (_now(now), login_id or "", event, ip, detail))

GENERIC_FAIL = "That ID or password/code was not accepted, or the ID is temporarily locked."

def check_password_policy(pw, login_id, display_name):
    if len(pw) < 8: return "Password must be at least 8 characters."
    if len(pw) > 128: return "Password must be at most 128 characters."
    pw_l = pw.lower()
    if pw_l == login_id.lower() or pw_l == display_name.lower():
        return "Password cannot be your ID or name."
    blocklist = ["password", "12345678", "iconsolar", "icon1234", "qwerty123"]
    if pw_l in blocklist:
        return "Password is too common."
    return None

def hash_pw(pw):
    return generate_password_hash(pw, method="pbkdf2:sha256:600000")

def check_pw(pw_hash, pw):
    if not pw_hash: return False
    return check_password_hash(pw_hash, pw)

def hash_token(token):
    import hashlib
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def verify_totp(secret, code, last_step, now_epoch):
    if not secret or not code.isdigit() or len(code) != 6:
        return False, last_step
    totp = pyotp.TOTP(secret)
    current_step = now_epoch // 30
    for offset in (-1, 0, 1):
        step = current_step + offset
        if step <= last_step: continue # Replay guard
        if totp.at(step * 30) == code:
            return True, step
    return False, last_step

def _get_user(cur, login_id):
    cur.execute("SELECT * FROM app_user WHERE login_id=%s COLLATE NOCASE", (login_id,))
    return cur.fetchone()

def _require_can_act_on(actor, target):
    """
    An Admin may act on rank 1 only, or themselves.
    If the rule is violated, raise AuthError("Not found.") to hide the existence of higher IDs.
    """
    if not target:
        raise AuthError("Not found.")
    if actor and type(actor) is dict:
        actor_rank = get_rank(actor["role"])
        target_rank = get_rank(target["role"])
        if actor_rank == 2 and target_rank >= 2 and actor["login_id"] != target["login_id"]:
            raise AuthError("Not found.")

def list_users(cur, actor_login_id):
    if actor_login_id == "cli":
        actor_rank = 3
    else:
        actor = _get_user(cur, actor_login_id)
        if not actor: return []
        actor_rank = get_rank(actor["role"])
    cur.execute("SELECT login_id, display_name, role, active, locked_until FROM app_user ORDER BY created_at")
    users = cur.fetchall()
    if actor_rank == 2:
        users = [u for u in users if get_rank(u["role"]) == 1 or u["login_id"] == actor_login_id]
    elif actor_rank < 2:
        users = [u for u in users if u["login_id"] == actor_login_id]
    return users

def login(cur, login_id, credential, ip=None, now=None):
    t = _now(now)
    u = _get_user(cur, login_id)
    if not u:
        check_pw(hash_pw("dummy"), credential)
        log_event(cur, login_id, "login_fail", ip, "unknown ID", t)
        return {"ok": False, "reason": GENERIC_FAIL}

    if u["locked_until"] > t:
        log_event(cur, login_id, "login_fail", ip, "locked", t)
        return {"ok": False, "reason": GENERIC_FAIL}
    if not u["active"]:
        log_event(cur, login_id, "login_fail", ip, "inactive", t)
        return {"ok": False, "reason": GENERIC_FAIL}

    method = None
    if len(credential) == 6 and credential.isdigit():
        method = "totp"
    elif len(credential) == 9 and credential[4] == "-":
        method = "recovery"
    else:
        method = "password"

    rank = get_rank(u["role"])
    success = False
    detail = None
    
    if method == "totp":
        if rank < 2:
            detail = "totp not allowed for role"
        else:
            try:
                secret = decrypt_secret(u["totp_secret_enc"])
                ok, step = verify_totp(secret, credential, u["totp_last_step"], t)
                if ok:
                    cur.execute("UPDATE app_user SET totp_last_step=%s, failed_count=0 WHERE user_id=%s", (step, u["user_id"]))
                    success = True
                else:
                    detail = "wrong code or replayed"
            except KeyMissing as e:
                log_event(cur, login_id, "login_fail", ip, f"KeyMissing: {e}", t)
                return {"ok": False, "reason": GENERIC_FAIL}

    elif method == "recovery":
        if rank < 3:
            detail = "recovery not allowed for role"
        else:
            cur.execute("SELECT code_id FROM auth_recovery_code WHERE user_id=%s AND used_at IS NULL AND code_hash=%s",
                        (u["user_id"], hash_token(credential)))
            rc = cur.fetchone()
            if rc:
                cur.execute("UPDATE auth_recovery_code SET used_at=%s WHERE code_id=%s", (t, rc["code_id"]))
                cur.execute("UPDATE app_user SET must_reenrol=1, failed_count=0 WHERE user_id=%s", (u["user_id"],))
                success = True
                log_event(cur, login_id, "recovery_used", ip, None, t)
            else:
                detail = "wrong recovery code"

    elif method == "password":
        if rank == 3:
            check_pw(u["pw_hash"] or "", credential)
            detail = "super admin password never works"
        elif rank == 2:
            cur.execute("SELECT window_id FROM auth_backup_window WHERE user_id=%s AND used_at IS NULL AND expires_at > %s",
                        (u["user_id"], t))
            bw = cur.fetchone()
            if bw and check_pw(u["pw_hash"], credential):
                cur.execute("UPDATE auth_backup_window SET used_at=%s WHERE window_id=%s", (t, bw["window_id"]))
                cur.execute("UPDATE app_user SET failed_count=0 WHERE user_id=%s", (u["user_id"],))
                success = True
                log_event(cur, login_id, "backup_window_used", ip, None, t)
            else:
                detail = "wrong password or no window"
        else:
            if check_pw(u["pw_hash"], credential):
                cur.execute("UPDATE app_user SET failed_count=0 WHERE user_id=%s", (u["user_id"],))
                success = True
            else:
                detail = "wrong password"

    if success:
        log_event(cur, login_id, "login_ok", ip, method, t)
        must_reenrol = True if method == "recovery" else bool(u["must_reenrol"])
        return {"ok": True, "user_id": u["user_id"], "role": u["role"], 
                "must_change_pw": bool(u["must_change_pw"]), "must_reenrol": must_reenrol}
    else:
        fails = u["failed_count"] + 1
        if fails >= MAX_FAILS:
            cur.execute("UPDATE app_user SET failed_count=0, locked_until=%s WHERE user_id=%s", (t + LOCK_SECONDS, u["user_id"]))
            log_event(cur, login_id, "locked", ip, None, t)
        else:
            cur.execute("UPDATE app_user SET failed_count=%s WHERE user_id=%s", (fails, u["user_id"]))
            log_event(cur, login_id, "login_fail", ip, detail, t)
        return {"ok": False, "reason": GENERIC_FAIL}

def stepup_cancel(cur, login_id, code, ip=None, now=None):
    t = _now(now)
    u = _get_user(cur, login_id)
    if not u or not u["active"] or u["locked_until"] > t:
        return False
    if get_rank(u["role"]) < 2:
        return False
    
    try:
        secret = decrypt_secret(u["totp_secret_enc"])
        ok, step = verify_totp(secret, code, u["totp_last_step"], t)
        if ok:
            cur.execute("UPDATE app_user SET totp_last_step=%s WHERE user_id=%s", (step, u["user_id"]))
            log_event(cur, login_id, "stepup_ok", ip, None, t)
            return True
        else:
            log_event(cur, login_id, "stepup_fail", ip, "wrong code or replayed", t)
            return False
    except KeyMissing:
        return False

def change_password(cur, login_id, old_pw, new_pw, ip=None, now=None):
    t = _now(now)
    u = _get_user(cur, login_id)
    if not u or get_rank(u["role"]) > 1: return False
    
    if not check_pw(u["pw_hash"], old_pw):
        return False
    
    err = check_password_policy(new_pw, u["login_id"], u["display_name"])
    if err: raise AuthError(err)

    cur.execute("UPDATE app_user SET pw_hash=%s, must_change_pw=0 WHERE user_id=%s", (hash_pw(new_pw), u["user_id"]))
    log_event(cur, login_id, "password_set", ip, "change", t)
    return True

def create_superadmin(cur, login_id, display_name, now=None):
    t = _now(now)
    cur.execute("INSERT INTO app_user (login_id, display_name, role, created_at, created_by) VALUES (%s, %s, %s, %s, %s)",
                (login_id, display_name, "Super Admin", t, "cli"))
    return issue_enrol_token(cur, "cli", login_id, now)

def issue_enrol_token(cur, actor_login_id, target_login_id, now=None):
    t = _now(now)
    actor = None
    if actor_login_id != "cli":
        actor = _get_user(cur, actor_login_id)
        if not actor: raise AuthError("Actor not found.")
        actor_rank = get_rank(actor["role"])
    else:
        actor_rank = 3
    
    u = _get_user(cur, target_login_id)
    _require_can_act_on(actor, u)
    target_rank = get_rank(u["role"])
    
    if target_rank < 2: raise AuthError("Operators do not use TOTP.")
        
    token = secrets.token_hex(16)
    cur.execute("UPDATE auth_enrol_token SET expires_at=%s WHERE user_id=%s AND used_at IS NULL", (t, u["user_id"]))
    cur.execute("INSERT INTO auth_enrol_token (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (u["user_id"], hash_token(token), t + 900))
    log_event(cur, target_login_id, "enrol_token_issued", None, f"by {actor_login_id}", t)
    return token

def enrol_begin(cur, login_id, token, ip=None, now=None):
    t = _now(now)
    u = _get_user(cur, login_id)
    if not u: return None
    
    cur.execute("SELECT token_id FROM auth_enrol_token WHERE user_id=%s AND token_hash=%s AND used_at IS NULL AND expires_at > %s",
                (u["user_id"], hash_token(token), t))
    tk = cur.fetchone()
    if not tk: return None

    secret = pyotp.random_base32()
    enc = encrypt_secret(secret)
    cur.execute("UPDATE app_user SET totp_pending_enc=%s WHERE user_id=%s", (enc, u["user_id"]))
    log_event(cur, login_id, "enrol_begin", ip, None, t)
    
    totp = pyotp.TOTP(secret)
    url = totp.provisioning_uri(name=login_id, issuer_name="ICON TRACE")
    return {"secret": secret, "url": url}

def enrol_commit(cur, login_id, token, code, ip=None, now=None):
    t = _now(now)
    u = _get_user(cur, login_id)
    if not u: return False
    
    cur.execute("SELECT token_id FROM auth_enrol_token WHERE user_id=%s AND token_hash=%s AND used_at IS NULL AND expires_at > %s",
                (u["user_id"], hash_token(token), t))
    tk = cur.fetchone()
    if not tk: return False

    if not u["totp_pending_enc"]: return False
    secret = decrypt_secret(u["totp_pending_enc"])
    ok, step = verify_totp(secret, code, 0, t)
    if not ok: return False
    
    cur.execute("UPDATE auth_enrol_token SET used_at=%s WHERE token_id=%s", (t, tk["token_id"]))
    cur.execute("UPDATE app_user SET totp_secret_enc=%s, totp_pending_enc=NULL, totp_last_step=%s, must_reenrol=0 WHERE user_id=%s",
                (encrypt_secret(secret), step, u["user_id"]))
    log_event(cur, login_id, "enrol_ok", ip, None, t)
    
    recovery_codes = []
    if get_rank(u["role"]) == 3:
        cur.execute("UPDATE auth_recovery_code SET used_at=%s WHERE user_id=%s", (t, u["user_id"]))
        import string
        alph = string.ascii_uppercase + string.digits
        alph = alph.replace("0", "").replace("O", "").replace("1", "").replace("I", "")
        for _ in range(10):
            rc = "".join(secrets.choice(alph) for _ in range(8))
            rc = rc[:4] + "-" + rc[4:]
            recovery_codes.append(rc)
            cur.execute("INSERT INTO auth_recovery_code (user_id, code_hash) VALUES (%s, %s)",
                        (u["user_id"], hash_token(rc)))
        log_event(cur, login_id, "recovery_generated", ip, None, t)
    return recovery_codes

def unlock_user(cur, actor_login_id, target_login_id, ip=None, now=None):
    t = _now(now)
    actor = _get_user(cur, actor_login_id) if actor_login_id != "cli" else {"role": "Super Admin"}
    if not actor: raise AuthError("Actor not found.")
    u = _get_user(cur, target_login_id)
    _require_can_act_on(actor, u)
    
    if get_rank(actor["role"]) < 2:
        raise AuthError("Not authorized.")
        
    cur.execute("UPDATE app_user SET locked_until=0, failed_count=0 WHERE user_id=%s", (u["user_id"],))
    log_event(cur, target_login_id, "unlocked", ip, f"by {actor_login_id}", t)

def reset_totp(cur, actor_login_id, target_login_id, ip=None, now=None):
    t = _now(now)
    actor = _get_user(cur, actor_login_id) if actor_login_id != "cli" else {"role": "Super Admin"}
    if not actor: raise AuthError("Actor not found.")
    if get_rank(actor["role"]) < 3: raise AuthError("Only Super Admin can reset TOTP.")
    
    u = _get_user(cur, target_login_id)
    _require_can_act_on(actor, u)
    if get_rank(u["role"]) < 2: raise AuthError("Role does not use TOTP.")
    
    cur.execute("UPDATE app_user SET totp_secret_enc=NULL, must_reenrol=1 WHERE user_id=%s", (u["user_id"],))
    cur.execute("UPDATE auth_recovery_code SET used_at=%s WHERE user_id=%s AND used_at IS NULL", (t, u["user_id"]))
    log_event(cur, target_login_id, "totp_reset", ip, f"by {actor_login_id}", t)
    return issue_enrol_token(cur, actor_login_id, target_login_id, now)

def open_backup_window(cur, actor_login_id, target_login_id, ip=None, now=None):
    t = _now(now)
    actor = _get_user(cur, actor_login_id)
    if not actor or get_rank(actor["role"]) < 3: raise AuthError("Only Super Admin can open backup windows.")
    
    u = _get_user(cur, target_login_id)
    _require_can_act_on(actor, u)
    if get_rank(u["role"]) != 2: raise AuthError("Backup windows are only for Admins.")
    
    cur.execute("INSERT INTO auth_backup_window (user_id, opened_by, opened_at, expires_at) VALUES (%s, %s, %s, %s)",
                (u["user_id"], actor_login_id, t, t + 1800))
    log_event(cur, target_login_id, "backup_window_opened", ip, f"by {actor_login_id}", t)

def set_temp_password(cur, actor_login_id, target_login_id, temp_pw, ip=None, now=None):
    t = _now(now)
    actor = _get_user(cur, actor_login_id)
    if not actor or get_rank(actor["role"]) < 2: raise AuthError("Only Admins can set temp passwords.")
    
    u = _get_user(cur, target_login_id)
    _require_can_act_on(actor, u)
        
    if get_rank(u["role"]) >= 3:
        raise AuthError("Super Admins do not have passwords.")
    
    err = check_password_policy(temp_pw, u["login_id"], u["display_name"])
    if err: raise AuthError(err)
    
    must_change = 1 if get_rank(u["role"]) < 2 else 0
    cur.execute("UPDATE app_user SET pw_hash=%s, must_change_pw=%s, failed_count=0, locked_until=0 WHERE user_id=%s", (hash_pw(temp_pw), must_change, u["user_id"]))
    log_event(cur, target_login_id, "password_set", ip, f"temp by {actor_login_id}", t)

def create_operator(cur, actor_login_id, target_login_id, display_name, role, temp_pw, ip=None, now=None):
    t = _now(now)
    actor = _get_user(cur, actor_login_id)
    if not actor or get_rank(actor["role"]) < 2: raise AuthError("Only Admins can create operators.")
    if get_rank(role) > 1: raise AuthError("Can only create operators.")
    
    err = check_password_policy(temp_pw, target_login_id, display_name)
    if err: raise AuthError(err)
    
    cur.execute("INSERT INTO app_user (login_id, display_name, role, pw_hash, must_change_pw, created_at, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (target_login_id, display_name, role, hash_pw(temp_pw), 1, t, actor_login_id))
    log_event(cur, target_login_id, "password_set", ip, f"temp by {actor_login_id}", t)

def sntp_drift(server=None, timeout=2):
    if not server:
        server = NTP_SERVER
    if ":" in server:
        host, port_s = server.split(":")
        port = int(port_s)
    else:
        host, port = server, 123
        
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(timeout)
    data = b'\x1b' + 47 * b'\0'
    t1 = time.time()
    try:
        client.sendto(data, (host, port))
        data, address = client.recvfrom(1024)
        t4 = time.time()
    except Exception:
        return {"status": "unknown"}
    finally:
        client.close()

    if data:
        s = struct.unpack('!12I', data)
        t_rx = s[8] + float(s[9]) / 2**32 - 2208988800
        t_tx = s[10] + float(s[11]) / 2**32 - 2208988800
        offset = ((t_rx - t1) + (t_tx - t4)) / 2
        drift = int(round(offset))
        status = "drift" if abs(drift) > 20 else "ok"
        return {"status": status, "drift_s": drift}
    return {"status": "unknown"}

def clock_status():
    return sntp_drift()
