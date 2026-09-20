import os
import sqlite3
import tempfile
import time
import subprocess
import threading
import socket
import struct
import sys
import pytest
import pyotp
import store
import icon_auth

GENERIC_FAIL = "That ID or password/code was not accepted, or the ID is temporarily locked."

@pytest.fixture(scope="function")
def db_env():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    old_db = os.environ.get("ICON_DB_FILE")
    old_ntp = os.environ.get("ICON_NTP_SERVER")
    old_max = os.environ.get("ICON_AUTH_MAX_FAILS")
    old_lock = os.environ.get("ICON_AUTH_LOCK_SECONDS")
    
    os.environ["ICON_DB_FILE"] = path
    # We will override these in icon_auth as well since it caches them at load time
    icon_auth.MAX_FAILS = 5
    icon_auth.LOCK_SECONDS = 300
    
    key_path = os.path.join(os.path.dirname(path), ".icon_totp_key")
    if os.path.exists(key_path):
        os.remove(key_path)

    store.DB_PATH = path
    icon_auth.create_key()
    
    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)
        icon_auth.create_superadmin(cur, "super1", "Super One")
        # Admins do not have passwords to bootstrap with, so they are created directly or by an enrol token flow not yet fully formalized as a single function.
        cur.execute("INSERT INTO app_user (login_id, display_name, role, created_at, created_by) VALUES (%s, %s, %s, %s, %s)",
                    ("admin1", "Admin One", "Admin", 100000, "super1"))
        cur.execute("INSERT INTO app_user (login_id, display_name, role, created_at, created_by) VALUES (%s, %s, %s, %s, %s)",
                    ("admin2", "Admin Two", "Admin", 100000, "super1"))
        icon_auth.create_operator(cur, "admin1", "op1", "Operator One", "FQC Operator", "TempPass123!")
        
        # Give super1 a password hash directly to test that it NEVER works
        cur.execute("UPDATE app_user SET pw_hash=%s WHERE login_id='super1'", (icon_auth.hash_pw("SuperSecret123!"),))
        
    yield path
    
    os.remove(path)
    if os.path.exists(key_path):
        os.remove(key_path)
        
    if old_db: os.environ["ICON_DB_FILE"] = old_db
    else: del os.environ["ICON_DB_FILE"]
    if old_ntp: os.environ["ICON_NTP_SERVER"] = old_ntp
    else: os.environ.pop("ICON_NTP_SERVER", None)
    if old_max: os.environ["ICON_AUTH_MAX_FAILS"] = old_max
    else: os.environ.pop("ICON_AUTH_MAX_FAILS", None)
    if old_lock: os.environ["ICON_AUTH_LOCK_SECONDS"] = old_lock
    else: os.environ.pop("ICON_AUTH_LOCK_SECONDS", None)

def test_1_password_policy(db_env):
    assert icon_auth.check_password_policy("short", "user", "name") == "Password must be at least 8 characters."
    assert icon_auth.check_password_policy("123456", "user", "name") == "Please choose a password that is not 6 digits and does not look like a recovery code (ABCD-1234)."
    assert icon_auth.check_password_policy("1234-5678", "user", "name") == "Please choose a password that is not 6 digits and does not look like a recovery code (ABCD-1234)."
    assert icon_auth.check_password_policy("a"*129, "user", "name") == "Password must be at most 128 characters."
    assert icon_auth.check_password_policy("useruser", "useruser", "name") == "Password cannot be your ID or name."
    assert icon_auth.check_password_policy("iconsolar", "user", "name") == "Password is too common."
    assert icon_auth.check_password_policy("ValidPass123", "user", "name") is None
    
    pw = "GoodPass123!"
    h = icon_auth.hash_pw(pw)
    assert icon_auth.check_pw(h, pw)
    assert not icon_auth.check_pw(h, "wrong")

def test_2_totp_window(db_env):
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    now = 100000
    
    # current step (3333)
    c_code = totp.at(now)
    assert icon_auth.verify_totp(secret, c_code, 0, now)[0]
    
    # prev step (3332)
    p_code = totp.at(now - 30)
    assert icon_auth.verify_totp(secret, p_code, 0, now)[0]
    
    # next step (3334)
    n_code = totp.at(now + 30)
    assert icon_auth.verify_totp(secret, n_code, 0, now)[0]
    
    # -2 step (3331)
    pp_code = totp.at(now - 60)
    assert not icon_auth.verify_totp(secret, pp_code, 0, now)[0]

def test_3_totp_replay(db_env):
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    now = 100000
    
    code = totp.at(now)
    ok, step = icon_auth.verify_totp(secret, code, 0, now)
    assert ok
    
    # same step again
    ok2, step2 = icon_auth.verify_totp(secret, code, step, now)
    assert not ok2
    
    # older step
    old_code = totp.at(now - 30)
    ok3, step3 = icon_auth.verify_totp(secret, old_code, step, now)
    assert not ok3

def test_3b_timing(db_env):
    # Test that unknown-ID, known-locked, known-wrong-password, and known-wrong-code take similar time
    import time
    import statistics
    
    # We will use the default 350ms floor so it covers pbkdf2 hashing overhead
    icon_auth.LOGIN_TIMING_FLOOR_MS = 350
    
    now = 100000
    with store.conn() as (cx, cur):
        # Ensure we have a password user
        icon_auth.set_temp_password(cur, "super1", "op1", "SomePass123!", now=now)
        
        # And an enrolled TOTP user (admin1)
        t_hex = icon_auth.issue_enrol_token(cur, "super1", "admin1", now=now)
        r = icon_auth.enrol_begin(cur, "admin1", t_hex, now=now)
        import pyotp
        totp = pyotp.TOTP(r["secret"])
        icon_auth.enrol_commit(cur, "admin1", t_hex, totp.at(now), now=now)
        
        # Lock super1 manually for the test
        cur.execute("UPDATE app_user SET locked_until=%s WHERE login_id='super1'", (now + 1000,))
        
        def measure(login_id, cred):
            times = []
            for _ in range(7):
                t0 = time.time()
                icon_auth.login(cur, login_id, cred, now=now)
                t1 = time.time()
                times.append(t1 - t0)
            return statistics.median(times)
            
        m_unknown = measure("nobody_here", "WrongPass123!")
        m_locked = measure("super1", "WrongPass123!")
        m_wrong_pw = measure("op1", "WrongPass123!")
        m_wrong_code = measure("admin1", "123456")
        
        # All medians should be within 40% of the maximum median
        results = [m_unknown, m_locked, m_wrong_pw, m_wrong_code]
        max_m = max(results)
        
        for m in results:
            assert m >= max_m * 0.60, f"Timing leaked! {results}"

def test_4_enrolment(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        token = icon_auth.issue_enrol_token(cur, "super1", "admin1", now=now)
        
        # begin
        res = icon_auth.enrol_begin(cur, "admin1", token, now=now)
        assert res["secret"]
        
        # pending doesn't work for login
        l_res = icon_auth.login(cur, "admin1", "123456", now=now)
        assert not l_res["ok"]
        
        # wrong code doesn't activate
        assert not icon_auth.enrol_commit(cur, "admin1", token, "000000", now=now)
        
        # right code activates
        totp = pyotp.TOTP(res["secret"])
        code = totp.at(now)
        assert icon_auth.enrol_commit(cur, "admin1", token, code, now=now) == [] # admin gets no recovery
        
        # login works
        l_res = icon_auth.login(cur, "admin1", totp.at(now+30), now=now+30)
        assert l_res["ok"]
        
        # token single use
        assert not icon_auth.enrol_begin(cur, "admin1", token, now=now+30)

def test_5_lockout(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        for i in range(5):
            r = icon_auth.login(cur, "op1", "wrong", now=now)
            assert not r["ok"]
            
        # 6th should be locked
        r = icon_auth.login(cur, "op1", "TempPass123!", now=now)
        assert not r["ok"]
        assert r["reason"] == GENERIC_FAIL
        
        # fast forward 5 mins
        r = icon_auth.login(cur, "op1", "TempPass123!", now=now+301)
        assert r["ok"]
        
        # success resets count
        r = icon_auth.login(cur, "op1", "wrong", now=now+302)
        assert not r["ok"]
        
        r = icon_auth.login(cur, "op1", "TempPass123!", now=now+303)
        assert r["ok"]

def test_6_identical_errors(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        r1 = icon_auth.login(cur, "unknown", "pass", now=now)
        r2 = icon_auth.login(cur, "op1", "wrong", now=now)
        
        for _ in range(5): icon_auth.login(cur, "op1", "wrong", now=now)
        r3 = icon_auth.login(cur, "op1", "TempPass123!", now=now) # locked
        
        token = icon_auth.issue_enrol_token(cur, "super1", "admin1", now=now)
        res = icon_auth.enrol_begin(cur, "admin1", token, now=now)
        icon_auth.enrol_commit(cur, "admin1", token, pyotp.TOTP(res["secret"]).at(now), now=now)
        
        code = pyotp.TOTP(res["secret"]).at(now+30)
        icon_auth.login(cur, "admin1", code, now=now+30)
        r4 = icon_auth.login(cur, "admin1", code, now=now+30) # replay
        
        assert r1 == r2 == r3 == r4
        assert r1["reason"] == GENERIC_FAIL

def test_7_roles(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        # Admin can't use password normally
        icon_auth.set_temp_password(cur, "super1", "admin1", "TempPass123!", now=now)
        r = icon_auth.login(cur, "admin1", "TempPass123!", now=now)
        assert not r["ok"]
        
        # Super admin opens window
        icon_auth.open_backup_window(cur, "super1", "admin1", now=now)
        
        # Admin password works
        r = icon_auth.login(cur, "admin1", "TempPass123!", now=now)
        assert r["ok"]
        
        # Window single use
        r = icon_auth.login(cur, "admin1", "TempPass123!", now=now)
        assert not r["ok"]
        
        # Super Admin password NEVER works
        r = icon_auth.login(cur, "super1", "SuperSecret123!", now=now)
        assert not r["ok"]

        # An operator with password "1234-5678" or "123456" can sign in (legacy/forced injection)
        cur.execute("INSERT INTO app_user (login_id, display_name, role, created_at, created_by, pw_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                    ("op2", "Op Two", "FQC Operator", 100000, "admin1", icon_auth.hash_pw("1234-5678")))
        cur.execute("INSERT INTO app_user (login_id, display_name, role, created_at, created_by, pw_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                    ("op3", "Op Three", "FQC Operator", 100000, "admin1", icon_auth.hash_pw("123456")))
        
        r = icon_auth.login(cur, "op2", "1234-5678", now=now)
        assert r["ok"]
        r = icon_auth.login(cur, "op3", "123456", now=now)
        assert r["ok"]

        # Admin's 6-digit password is still not accepted as a login outside a window
        cur.execute("UPDATE app_user SET pw_hash=%s WHERE login_id='admin1'", (icon_auth.hash_pw("123456"),))
        r = icon_auth.login(cur, "admin1", "123456", now=now)
        assert not r["ok"]
        # Admin cannot open window for SA
        with pytest.raises(icon_auth.AuthError):
            icon_auth.open_backup_window(cur, "admin1", "super1", now=now)

def test_8_hierarchy(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        # Admin can set OP password
        icon_auth.set_temp_password(cur, "admin1", "op1", "NewTemp123!", now=now)
        
        # Admin cannot set SA password (not found)
        with pytest.raises(icon_auth.AuthError, match="Not found"):
            icon_auth.set_temp_password(cur, "admin1", "super1", "NewTemp123!", now=now)

        # Admin cannot set another Admin's password (not found)
        with pytest.raises(icon_auth.AuthError, match="Not found"):
            icon_auth.set_temp_password(cur, "admin1", "admin2", "NewTemp123!", now=now)

        # Admin can change their own password (allowed via change_password, but set_temp_password also has a rule? Wait, set_temp_password expects target_rank < 2 if actor_rank == 2, so set_temp_password on self fails by rule. But change_password should work, we can test that)
        # We test Admin cannot unlock another Admin
        with pytest.raises(icon_auth.AuthError, match="Not found"):
            icon_auth.unlock_user(cur, "admin1", "admin2", now=now)
            
        # list users hides SA and other Admins from Admin
        u_admin = icon_auth.list_users(cur, "admin1")
        assert not any(u["login_id"] == "super1" for u in u_admin)
        assert not any(u["login_id"] == "admin2" for u in u_admin)
        assert any(u["login_id"] == "admin1" for u in u_admin)
        
        u_sa = icon_auth.list_users(cur, "super1")
        assert any(u["login_id"] == "super1" for u in u_sa)
        assert any(u["login_id"] == "admin1" for u in u_sa)
        assert any(u["login_id"] == "admin2" for u in u_sa)
        
        # nobody but CLI unlocks SA
        with pytest.raises(icon_auth.AuthError, match="Not found"):
            icon_auth.unlock_user(cur, "admin1", "super1", now=now)

def test_9_recovery(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        token = icon_auth.issue_enrol_token(cur, "cli", "super1", now=now)
        res = icon_auth.enrol_begin(cur, "super1", token, now=now)
        codes = icon_auth.enrol_commit(cur, "super1", token, pyotp.TOTP(res["secret"]).at(now), now=now)
        
        rc = codes[0]
        
        # login with rc
        r = icon_auth.login(cur, "super1", rc, now=now)
        assert r["ok"] and r["must_reenrol"]
        
        # single use
        r = icon_auth.login(cur, "super1", rc, now=now)
        assert not r["ok"]
        
        # db hashed
        cur.execute("SELECT * FROM auth_recovery_code WHERE code_hash=%s", (rc,))
        assert not cur.fetchone()

def test_10_at_rest(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        token = icon_auth.issue_enrol_token(cur, "cli", "super1", now=now)
        res = icon_auth.enrol_begin(cur, "super1", token, now=now)
        icon_auth.enrol_commit(cur, "super1", token, pyotp.TOTP(res["secret"]).at(now), now=now)

    # delete key
    key_path = os.path.join(os.path.dirname(db_env), ".icon_totp_key")
    os.remove(key_path)
    
    with store.conn() as (cx, cur):
        # keymissing handled, sign-in refused
        r = icon_auth.login(cur, "super1", pyotp.TOTP(res["secret"]).at(now+30), now=now+30)
        assert not r["ok"]
        
        cur.execute("SELECT totp_secret_enc FROM app_user WHERE totp_secret_enc IS NOT NULL")
        row = cur.fetchone()
        if row:
            assert res["secret"] != row["totp_secret_enc"]

def test_10b_key_handling(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        token = icon_auth.issue_enrol_token(cur, "cli", "super1", now=now)
        res = icon_auth.enrol_begin(cur, "super1", token, now=now)
        secret = res["secret"]
        icon_auth.enrol_commit(cur, "super1", token, pyotp.TOTP(secret).at(now), now=now)

    key_path = icon_auth._get_key_path()
    assert os.path.exists(key_path)
    assert os.path.dirname(os.path.abspath(key_path)) == os.path.dirname(os.path.abspath(store.DB_PATH))

    # delete key -> sign-in refused, no new file, clear log line
    os.remove(key_path)
    with store.conn() as (cx, cur):
        r = icon_auth.login(cur, "super1", pyotp.TOTP(secret).at(now+30), ip="1.2.3.4", now=now+30)
        assert not r["ok"]
        assert not os.path.exists(key_path)
        
        cur.execute("SELECT detail FROM auth_event WHERE login_id='super1' ORDER BY event_id DESC LIMIT 1")
        detail = cur.fetchone()["detail"]
        assert "KeyMissing" in detail

    # Empty and short files raise KeyMissing
    with open(key_path, "wb") as f:
        f.write(b"")
    with pytest.raises(icon_auth.KeyMissing):
        icon_auth.load_key()
        
    with open(key_path, "wb") as f:
        f.write(b"shortkey")
    with pytest.raises(icon_auth.KeyMissing):
        icon_auth.load_key()

def test_11_clock(db_env):
    # Fake UDP server
    def fake_ntp(offset_s):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        
        def run():
            try:
                s.settimeout(1.0)
                data, addr = s.recvfrom(1024)
                t = time.time() + offset_s + 2208988800
                ti = int(t)
                tf = int((t - ti) * 2**32)
                res = struct.pack('!12I', 0,0,0,0,0,0,0,0, ti,tf, ti,tf)
                s.sendto(res, addr)
            except Exception:
                pass
            finally:
                s.close()
        t = threading.Thread(target=run)
        t.daemon = True
        t.start()
        return port, t

    # +45s drift
    p, th = fake_ntp(45)
    res = icon_auth.sntp_drift(f"127.0.0.1:{p}", timeout=1)
    assert res["status"] == "drift"
    assert res["drift_s"] >= 44
    th.join()
    
    # +5s ok
    p, th = fake_ntp(5)
    res = icon_auth.sntp_drift(f"127.0.0.1:{p}", timeout=1)
    assert res["status"] == "ok"
    assert -6 <= res["drift_s"] <= 6
    th.join()
    
    # unreachable
    res = icon_auth.sntp_drift(f"127.0.0.1:40000", timeout=0.1)
    assert res["status"] == "unknown"

def test_12_no_leak(db_env):
    with store.conn() as (cx, cur):
        cur.execute("SELECT event, detail FROM auth_event")
        for row in cur.fetchall():
            s = (row["event"] + " " + (row["detail"] or "")).lower()
            assert "pass" not in s or "password" in s # it can say "wrong password" but not the actual password
            assert "token" not in s or "issued" in s
            assert "secret" not in s

def test_13_stepup(db_env):
    now = 100000
    with store.conn() as (cx, cur):
        token = icon_auth.issue_enrol_token(cur, "cli", "admin1", now=now)
        res = icon_auth.enrol_begin(cur, "admin1", token, now=now)
        icon_auth.enrol_commit(cur, "admin1", token, pyotp.TOTP(res["secret"]).at(now), now=now)
        
        # Use code to login
        c1 = pyotp.TOTP(res["secret"]).at(now+30)
        icon_auth.login(cur, "admin1", c1, now=now+30)
        
        # Stepup with same code fails (replay)
        assert not icon_auth.stepup_cancel(cur, "admin1", c1, now=now+30)
        
        # Stepup with next code ok
        c2 = pyotp.TOTP(res["secret"]).at(now+60)
        assert icon_auth.stepup_cancel(cur, "admin1", c2, now=now+60)
        
        # Operator cannot stepup
        assert not icon_auth.stepup_cancel(cur, "op1", "123456", now=now)

def test_14_cli(db_env):
    env = dict(os.environ)
    env["ICON_DB_FILE"] = store.DB_PATH
    
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon_auth_cli.py")
    
    res = subprocess.run([sys.executable, cli, "create-superadmin", "sa2", "SA Two"], env=env, capture_output=True, text=True)
    assert "Created Super Admin: sa2" in res.stdout
    assert "Enrolment Token:" in res.stdout
    
    res = subprocess.run([sys.executable, cli, "reset-totp", "sa2"], env=env, capture_output=True, text=True)
    assert "Reset TOTP for: sa2" in res.stdout
    
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET locked_until=9999999999 WHERE login_id='sa2'")
    
    res = subprocess.run([sys.executable, cli, "unlock", "sa2"], env=env, capture_output=True, text=True)
    assert "Unlocked user: sa2" in res.stdout
    
    res = subprocess.run([sys.executable, cli, "list"], env=env, capture_output=True, text=True)
    assert "sa2" in res.stdout
    assert "Super One" in res.stdout
