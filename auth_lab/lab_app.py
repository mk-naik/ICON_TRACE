import os
import sys
import html
import urllib.parse

# Set ICON_DB_FILE before importing store
BASE = os.path.dirname(os.path.abspath(__file__))
if "ICON_DB_FILE" not in os.environ:
    os.environ["ICON_DB_FILE"] = os.path.join(BASE, "lab.db")

# Add parent directory to path so we can import store and icon_auth
sys.path.insert(0, os.path.dirname(BASE))

import store
import icon_auth
import icon_barcode
from flask import Flask, request, redirect, make_response, render_template_string, jsonify
import json
from werkzeug.security import generate_password_hash

import os

app = Flask(__name__)

def _get_or_create_secret():
    db_file = os.environ.get("ICON_DB_FILE", "icontrace.db")
    if os.path.isabs(db_file):
        secret_path = os.path.join(os.path.dirname(db_file), ".icon_secret")
    else:
        secret_path = os.path.join(os.path.dirname(os.path.abspath(db_file)), ".icon_secret")
    
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()
    else:
        import secrets
        key = secrets.token_hex(32)
        with open(secret_path, "w") as f:
            f.write(key)
        return key

app.secret_key = _get_or_create_secret()

def _get_cookie():
    from itsdangerous import URLSafeSerializer
    s = URLSafeSerializer(app.secret_key)
    c = request.cookies.get("auth_session")
    if not c: return None
    try:
        return s.loads(c)
    except Exception:
        return None

def _set_cookie(resp, data):
    from itsdangerous import URLSafeSerializer
    s = URLSafeSerializer(app.secret_key)
    resp.set_cookie("auth_session", s.dumps(data), httponly=True, samesite="Lax")

def _clear_cookie(resp):
    resp.delete_cookie("auth_session")

# A successful sign-in resets the client-side attempt counter (Round 19,
# section 2). This page is only ever reached with a valid session, i.e.
# after icon_auth.login() actually returned ok - so reaching it at all is
# the reset condition; nothing here needs to know which ID succeeded.
_CLEAR_ATTEMPT_SCRIPT = "<script>try { sessionStorage.removeItem('iconAuthAttempt'); } catch (e) {}</script>"

def render_layout(title, body, banner=""):
    # named page_html, not html - this function's local scope must not
    # shadow the `html` module every other route in this file calls
    # html.escape() from.
    page_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <style>
            body {{ font-family: sans-serif; margin: 0; padding: 0; background: #f0f0f0; }}
            .container {{ max-width: 800px; margin: 20px auto; background: white; padding: 20px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            h1 {{ margin-top: 0; }}
            .nav {{ margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid #ccc; }}
            .nav a {{ margin-right: 15px; text-decoration: none; color: #0066cc; }}
            .error {{ color: red; font-weight: bold; margin-bottom: 15px; }}
            input, select, button {{ margin-bottom: 10px; padding: 8px; width: 100%; box-sizing: border-box; }}
            button {{ background: #0066cc; color: white; border: none; cursor: pointer; }}
            .box {{ border: 1px solid #ddd; padding: 15px; margin-bottom: 15px; background: #fafafa; }}
            .codes {{ font-family: monospace; font-size: 1.2em; background: #eee; padding: 10px; }}
        </style>
    </head>
    <body>
        {banner}
        <div class="container">
            <div class="nav">
                <a href="/">Home</a>
                <a href="/me">Me (Step-up)</a>
                <a href="/admin">Admin</a>
                <a href="/logout" style="float:right;">Logout</a>
            </div>
            <h1>{title}</h1>
            {body}
        </div>
    </body>
    </html>
    """
    return page_html

@app.route("/", methods=["GET"])
def index():
    session = _get_cookie()
    if session:
        if session.get("stage") == "ok":
            return redirect("/me")
        elif session.get("stage") == "change_password":
            return redirect("/change-password")
        elif session.get("stage") == "enrol":
            return redirect("/enrol")
    
    body = """
    <form method="POST" action="/login" id="loginForm">
        <label>Login ID:</label>
        <input type="text" name="login_id" id="login_id" required>
        <label>Password or authenticator code:</label>
        <input type="password" name="credential" required>
        <button type="submit" id="signInBtn">Sign In</button>
    </form>
    """
    err = request.args.get("err")
    err_html = html.escape(err) if err else ""
    body = f'<div class="error" id="errBox" style="{"" if err else "display:none;"}">{err_html}</div>' + body

    # This is a courtesy for the user, computed entirely client-side - the
    # server itself never returns a count, a remaining-attempts figure, a
    # lock state or a "wait N seconds" (see GENERIC_FAIL - every failure
    # response is identical). The real enforcement is
    # icon_auth._login_impl's own cooldown/lock check on the next request;
    # this only saves a doomed round trip and shows why.
    # 10, 5 minutes and the cooldown steps come from the server's own
    # constants, never hard-coded here. One shared counter for the tab, not
    # one per typed ID: a login page is one ID at a time in practice, and a
    # single counter is what "reset on any successful sign-in" (below)
    # means simply - it does not need to know which ID succeeded.
    body += f"""
    <script>
    (function() {{
        var MAX_FAILS = {icon_auth.MAX_FAILS};
        var LOCK_SECONDS = {icon_auth.LOCK_SECONDS};
        var COOLDOWN_STEPS = {json.dumps(list(icon_auth.COOLDOWN_STEPS))};
        var STORAGE_KEY = 'iconAuthAttempt';
        var form = document.getElementById('loginForm');
        var idInput = document.getElementById('login_id');
        var btn = document.getElementById('signInBtn');
        var errBox = document.getElementById('errBox');
        var serverErrText = errBox.textContent;
        var countdownTimer = null;

        function load() {{
            try {{ return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null'); }}
            catch (e) {{ return null; }}
        }}
        function save(state) {{
            try {{
                if (state) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
                else sessionStorage.removeItem(STORAGE_KEY);
            }} catch (e) {{}}
        }}

        function cooldownFor(count) {{
            if (!COOLDOWN_STEPS.length || count < 1) return 0;
            return COOLDOWN_STEPS[Math.min(count - 1, COOLDOWN_STEPS.length - 1)];
        }}

        function lineFor(count) {{
            var noun = count === 1 ? 'attempt' : 'attempts';
            if (count >= MAX_FAILS) {{
                return count + ' failed ' + noun + '. This ID is now locked for '
                    + Math.round(LOCK_SECONDS / 60) + ' minutes. Please wait, or ask an Admin to unlock it.';
            }}
            return count + ' failed ' + noun + '. After ' + MAX_FAILS
                + ', this ID is locked for ' + Math.round(LOCK_SECONDS / 60) + ' minutes.';
        }}

        function renderBox(count) {{
            var parts = [];
            if (serverErrText) parts.push(serverErrText);
            if (count) parts.push(lineFor(count));
            if (!parts.length) {{ errBox.style.display = 'none'; return; }}
            errBox.style.display = 'block';
            errBox.textContent = parts.join(' ');
        }}

        function tickCountdown(remainMs) {{
            clearInterval(countdownTimer);
            function tick() {{
                var s = Math.ceil(remainMs / 1000);
                if (s <= 0) {{
                    btn.disabled = false;
                    btn.textContent = 'Sign In';
                    clearInterval(countdownTimer);
                    return;
                }}
                btn.disabled = true;
                btn.textContent = 'Wait ' + s + 's...';
                remainMs -= 250;
            }}
            tick();
            countdownTimer = setInterval(tick, 250);
        }}

        function applyState() {{
            var st = load();
            var now = Date.now();
            if (st && (now - st.lastFailAt) > 5 * 60 * 1000) {{ st = null; save(null); }}
            if (!st || !st.count) {{ renderBox(0); btn.disabled = false; btn.textContent = 'Sign In'; return; }}
            renderBox(st.count);
            // Computed from lastFailAt, not from when the page loaded, so a
            // refresh neither restarts nor skips the wait.
            var cd = cooldownFor(st.count) * 1000;
            var remain = st.lastFailAt + cd - now;
            if (remain > 0) tickCountdown(remain);
            else {{ btn.disabled = false; btn.textContent = 'Sign In'; }}
        }}

        // Block Enter while disabled - the button itself is disabled, but
        // Enter in a text field submits the form directly.
        form.addEventListener('keydown', function(e) {{
            if (e.key === 'Enter' && btn.disabled) e.preventDefault();
        }});

        // A failure round-trips through ?err= on this same page (see
        // index()). Counted once, right here - but only ONCE per failure:
        // ?err= stays in the URL across a reload or back-button, and a
        // reload must recompute the same remaining wait, never add to it
        // (Round 19, section 2 - "refreshing the page neither restarts nor
        // skips the wait"). history.replaceState strips it right after
        // processing so a reload takes the "just displaying" path below.
        var params = new URLSearchParams(window.location.search);
        if (params.get('err')) {{
            var st = load() || {{count: 0, lastFailAt: 0}};
            st.count += 1;
            st.lastFailAt = Date.now();
            save(st);
            history.replaceState(null, '', window.location.pathname);
        }}

        applyState();
    }})();
    </script>
    """
    
    clock = icon_auth.clock_status()
    banner = ""
    if clock["status"] == "drift":
        banner = '<div style="background:red;color:white;padding:10px;text-align:center;">ERROR: Clock drift exceeds 20s. Please check system time.</div>'

    return render_layout("Sign In", body, banner=banner)

@app.route("/login", methods=["POST"])
def login():
    login_id = request.form.get("login_id")
    credential = request.form.get("credential")
    
    with store.conn() as (cx, cur):
        res = icon_auth.login(cur, login_id, credential, ip=request.remote_addr)
        if not res["ok"]:
            return redirect(f"/?err={res['reason']}")
        
        session_data = {
            "login_id": login_id,
            "user_id": res["user_id"],
            "role": res["role"],
            "stage": "ok"
        }
        if res["must_change_pw"]:
            session_data["stage"] = "change_password"
            target = "/change-password"
        elif res["must_reenrol"]:
            session_data["stage"] = "enrol"
            target = "/enrol"
        else:
            target = "/me"

        resp = make_response(redirect(target))
        _set_cookie(resp, session_data)
        return resp

@app.route("/logout")
def logout():
    resp = make_response(redirect("/"))
    _clear_cookie(resp)
    return resp

@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    session = _get_cookie()
    if not session: return redirect("/")
    
    if request.method == "POST":
        old_pw = request.form.get("old_pw")
        new_pw = request.form.get("new_pw")
        with store.conn() as (cx, cur):
            try:
                ok = icon_auth.change_password(cur, session["login_id"], old_pw, new_pw, ip=request.remote_addr)
                if ok:
                    session["stage"] = "ok"
                    resp = make_response(redirect("/me"))
                    _set_cookie(resp, session)
                    return resp
                else:
                    return render_layout("Change Password", '<div class="error">Change failed.</div>')
            except icon_auth.AuthError as e:
                return render_layout("Change Password", f'<div class="error">{html.escape(str(e))}</div><a href="/change-password">Try again</a>')

    body = _CLEAR_ATTEMPT_SCRIPT + """
    <form method="POST">
        <label>Old Password:</label>
        <input type="password" name="old_pw" required>
        <label>New Password:</label>
        <input type="password" name="new_pw" required>
        <button type="submit">Change Password</button>
    </form>
    """
    return render_layout("Change Password", body)

@app.route("/enrol", methods=["GET", "POST"])
def enrol():
    session = _get_cookie()
    token = request.args.get("token") or request.form.get("token")
    login_id = request.args.get("login_id") or request.form.get("login_id", "")
    
    if session and session.get("stage") == "enrol":
        login_id = session["login_id"]
        token = None

    if request.method == "POST":
        code = request.form.get("code")
        with store.conn() as (cx, cur):
            res = icon_auth.enrol_commit(cur, login_id, token, code, ip=request.remote_addr)
            if res is not False:
                # Success
                body = _CLEAR_ATTEMPT_SCRIPT + "<h3>Enrolment Successful!</h3>"
                if res: # recovery codes
                    body += "<p>Save these recovery codes NOW. They will not be shown again.</p><div class='codes'>"
                    body += "<br>".join(res)
                    body += "</div>"
                body += """
                <div id="close-btn-container" style="display:none; margin-top:20px;">
                    <button onclick="window.close()" style="padding:10px;">Close Window and Return to Admin</button>
                </div>
                <div id="login-link-container" style="display:none; margin-top:20px;">
                    <a href="/">Go to login</a>
                </div>
                <script>
                    if (window.opener) {
                        document.getElementById('close-btn-container').style.display = 'block';
                    } else {
                        document.getElementById('login-link-container').style.display = 'block';
                    }
                </script>
                """
                if session and session.get("stage") == "enrol":
                    resp = make_response(render_layout("Enrolment Complete", body))
                    _clear_cookie(resp)
                    return resp
                return render_layout("Enrolment Complete", body)
            else:
                return render_layout("Enrol", "<div class='error'>Invalid code or token.</div>")

    with store.conn() as (cx, cur):
        res = icon_auth.enrol_begin(cur, login_id, token, ip=request.remote_addr)
        if not res:
            return render_layout("Enrol", "<div class='error'>Invalid or expired token, or invalid user.</div>")
        
        qr_svg = icon_barcode.qr_svg(res["url"], module=4)
        body = f"""
        <p>Scan this QR code with your authenticator app:</p>
        <div>{qr_svg}</div>
        <p>Or enter this secret manually: <strong>{html.escape(res["secret"])}</strong></p>
        <form method="POST">
            <input type="hidden" name="token" value="{html.escape(token or '')}">
            <input type="hidden" name="login_id" value="{html.escape(login_id)}">
            <label>Enter the 6-digit code to confirm:</label>
            <input type="text" name="code" required autocomplete="off">
            <button type="submit">Complete Enrolment</button>
        </form>
        """
        return render_layout("Enrol TOTP", body)

@app.route("/me", methods=["GET", "POST"])
def me():
    session = _get_cookie()
    if not session or session.get("stage") != "ok": return redirect("/")
    
    msg = ""
    if request.method == "POST":
        code = request.form.get("code")
        with store.conn() as (cx, cur):
            if icon_auth.get_rank(session["role"]) < 2:
                msg = "<div class='error'>Ask an Admin</div>"
            else:
                ok = icon_auth.stepup_cancel(cur, session["login_id"], code, ip=request.remote_addr)
                if ok:
                    msg = "<div style='color:green;font-weight:bold;'>Cancel authorized.</div>"
                else:
                    msg = "<div class='error'>Step-up failed.</div>"

    body = _CLEAR_ATTEMPT_SCRIPT + f"""
    <div class="box">
        <p><strong>Login ID:</strong> {html.escape(session['login_id'])}</p>
        <p><strong>Role:</strong> {html.escape(session['role'])}</p>
    </div>
    <div class="box">
        <h3>Simulate Cancel (Step-up)</h3>
        {msg}
        <form method="POST">
            <label>Enter fresh authenticator code:</label>
            <input type="text" name="code" required autocomplete="off">
            <button type="submit">Cancel</button>
        </form>
    </div>
    """
    return render_layout("Me", body)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    session = _get_cookie()
    if not session or session.get("stage") != "ok": return redirect("/")
    if icon_auth.get_rank(session["role"]) < 2: return "Unauthorized", 403

    msg = ""
    enrol_url = ""
    if request.method == "POST":
        action = request.form.get("action")
        target = request.form.get("target")
        with store.conn() as (cx, cur):
            try:
                if action == "create_op":
                    name = request.form.get("display_name")
                    role = request.form.get("role")
                    pw = request.form.get("temp_pw")
                    icon_auth.create_operator(cur, session["login_id"], target, name, role, pw, ip=request.remote_addr)
                    msg = "Operator created."
                elif action == "set_pw":
                    pw = request.form.get("temp_pw")
                    icon_auth.set_temp_password(cur, session["login_id"], target, pw, ip=request.remote_addr)
                    msg = "Temporary password set."
                elif action == "unlock":
                    icon_auth.unlock_user(cur, session["login_id"], target, ip=request.remote_addr)
                    msg = "User unlocked."
                elif action == "issue_token":
                    token = icon_auth.issue_enrol_token(cur, session["login_id"], target)
                    enrol_url = f"/enrol?login_id={urllib.parse.quote(target)}&token={urllib.parse.quote(token)}"
                    msg = f"Token issued. URL: {enrol_url}"
                elif action == "create_admin":
                    name = request.form.get("display_name")
                    token = icon_auth.create_admin(cur, session["login_id"], target, name)
                    enrol_url = f"/enrol?login_id={urllib.parse.quote(target)}&token={urllib.parse.quote(token)}"
                    msg = f"Admin created. Enrolment URL: {enrol_url}"
                elif action == "open_window":
                    icon_auth.open_backup_window(cur, session["login_id"], target, ip=request.remote_addr)
                    msg = "Backup window opened for 30 minutes."
                elif action == "update_user":
                    name = request.form.get("display_name")
                    role = request.form.get("role")
                    icon_auth.update_user(cur, session["login_id"], target, display_name=name, role=role, ip=request.remote_addr)
                    msg = "User updated."
                elif action == "deactivate_user":
                    icon_auth.deactivate_user(cur, session["login_id"], target, ip=request.remote_addr)
                    msg = "User deactivated."
                elif action == "reset_totp":
                    token = icon_auth.reset_totp(cur, session["login_id"], target, ip=request.remote_addr)
                    enrol_url = f"/enrol?login_id={urllib.parse.quote(target)}&token={urllib.parse.quote(token)}"
                    msg = f"TOTP Reset. New URL: {enrol_url}"
            except icon_auth.AuthError as e:
                msg = f"Error: {html.escape(str(e))}"

    with store.conn() as (cx, cur):
        users = icon_auth.list_users(cur, session["login_id"])
    
    users_html = "<table border=1 cellpadding=5 style='width:100%; border-collapse:collapse; margin-bottom:20px;'>"
    users_html += "<tr><th>ID</th><th>Name</th><th>Role</th><th>Active</th><th>Locked Until</th><th>Action</th></tr>"
    import time
    t = int(time.time())
    for u in users:
        safe_login_id = html.escape(u['login_id'])
        locked_text = str(u['locked_until'])
        action_html = ""
        if u['locked_until'] > t:
            mins_left = (u['locked_until'] - t + 59) // 60  # round up: "1 min left" until truly over
            locked_text = f"<span style='color:red;'>Locked - {mins_left} min left</span>"
            action_html = f"<form method='POST' style='margin:0;'><input type='hidden' name='action' value='unlock'><input type='hidden' name='target' value='{safe_login_id}'><button type='submit' style='padding:2px 5px; margin:0;'>Unlock</button></form>"
        users_html += f"<tr><td>{safe_login_id}</td><td>{html.escape(u['display_name'])}</td><td>{html.escape(u['role'])}</td><td>{u['active']}</td><td>{locked_text}</td><td>{action_html}</td></tr>"
    users_html += "</table>"

    body = f"""
    {f"<div class='error' style='color:green;'>{html.escape(msg)}</div>" if msg else ""}
    {f"<script>window.open({json.dumps(enrol_url)}, '_blank');</script>" if enrol_url else ""}
    {users_html}
    
    <div class="box">
        <h3>Create Operator (Admin/Super Admin)</h3>
        <form method="POST">
            <input type="hidden" name="action" value="create_op">
            <input type="text" name="target" placeholder="Login ID" required>
            <input type="text" name="display_name" placeholder="Display Name" required>
            <input type="text" name="role" placeholder="Role (e.g. FQC Operator)" required>
            <input type="password" name="temp_pw" placeholder="Temp Password" required>
            <button type="submit">Create</button>
        </form>
    </div>
    
    <div class="box">
        <h3>Update User</h3>
        <form method="POST">
            <input type="hidden" name="action" value="update_user">
            <input type="text" name="target" placeholder="Login ID" required>
            <input type="text" name="display_name" placeholder="New Display Name (Optional)">
            <input type="text" name="role" placeholder="New Role (Optional)">
            <button type="submit">Update</button>
        </form>
    </div>
    
    <div class="box">
        <h3>Deactivate User</h3>
        <form method="POST" onsubmit="return confirm('Are you sure you want to deactivate this user?');">
            <input type="hidden" name="action" value="deactivate_user">
            <input type="text" name="target" placeholder="Login ID" required>
            <button type="submit" style="background-color: #be3325; color: white;">Deactivate</button>
        </form>
    </div>

    <div class="box">
        <h3>Create Admin (Super Admin Only)</h3>
        <form method="POST">
            <input type="hidden" name="action" value="create_admin">
            <input type="text" name="target" placeholder="Login ID" required>
            <input type="text" name="display_name" placeholder="Display Name" required>
            <button type="submit">Create</button>
        </form>
    </div>
    
    <div class="box">
        <h3>Set Temp Password (Admin/Super Admin)</h3>
        <form method="POST">
            <input type="hidden" name="action" value="set_pw">
            <input type="text" name="target" placeholder="Target Login ID" required>
            <input type="password" name="temp_pw" placeholder="Temp Password" required>
            <button type="submit">Set</button>
        </form>
    </div>
    
    <div class="box">
        <h3>Unlock User (Admin/Super Admin)</h3>
        <form method="POST">
            <input type="hidden" name="action" value="unlock">
            <input type="text" name="target" placeholder="Target Login ID" required>
            <button type="submit">Unlock</button>
        </form>
    </div>
    
    <div class="box">
        <h3>TOTP Controls (Super Admin Only)</h3>
        <form method="POST" style="margin-bottom:10px;">
            <input type="hidden" name="action" value="issue_token">
            <input type="text" name="target" placeholder="Target Login ID" required>
            <button type="submit">Issue Enrolment Token</button>
        </form>
        <form method="POST" style="margin-bottom:10px;">
            <input type="hidden" name="action" value="open_window">
            <input type="text" name="target" placeholder="Target Login ID" required>
            <button type="submit">Open Backup Window</button>
        </form>
        <form method="POST">
            <input type="hidden" name="action" value="reset_totp">
            <input type="text" name="target" placeholder="Target Login ID" required>
            <button type="submit">Reset TOTP & Issue Token</button>
        </form>
    </div>
    """
    return render_layout("Admin Panel", body)

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "clock": icon_auth.clock_status()})

if __name__ == "__main__":
    from waitress import serve
    import logging
    logging.basicConfig(level=logging.INFO)
    
    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)

    # Which database this is pointed at is the single most important thing
    # about a lab run, and it used to be the one thing this never said. An
    # account enrolled here only works in the app if BOTH are reading the
    # same file: the TOTP secret is Fernet-encrypted with the key that sits
    # beside the database, so a different file means a different key too,
    # and the app refuses the code with its usual generic "not accepted".
    # Hours were lost to exactly that, with nothing on screen to show why.
    real_db = os.path.join(os.path.dirname(BASE), "icontrace.db")
    db_path = os.path.abspath(store.DB_PATH)
    shared = os.path.normcase(db_path) == os.path.normcase(os.path.abspath(real_db))
    print("Serving lab on http://127.0.0.1:8091")
    print("Database: %s" % db_path)
    print("TOTP key: %s" % os.path.join(os.path.dirname(db_path), ".icon_totp_key"))
    if shared:
        print("This IS the app's own database - accounts enrolled here work "
              "in ICON TRACE.")
    else:
        print("")
        print("  WARNING: this is NOT the app's database (%s)." % real_db)
        print("  Anything enrolled here will NOT be able to sign in to ICON")
        print("  TRACE - different file, and a different .icon_totp_key with")
        print("  it. To enrol real accounts, restart pointed at the app's own")
        print("  database:")
        if os.name == "nt":
            print('    $env:ICON_DB_FILE = "%s"; python auth_lab\\lab_app.py' % real_db)
        else:
            print('    ICON_DB_FILE="%s" python auth_lab/lab_app.py' % real_db)
        print("")
    serve(app, host="127.0.0.1", port=8091)
