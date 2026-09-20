import os
import sys

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

app = Flask(__name__)
app.secret_key = "lab_secret_key"

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

def render_layout(title, body, banner=""):
    html = f"""
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
    return html

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
    <form method="POST" action="/login">
        <label>Login ID:</label>
        <input type="text" name="login_id" required>
        <label>Password or authenticator code:</label>
        <input type="password" name="credential" required>
        <button type="submit">Sign In</button>
    </form>
    """
    err = request.args.get("err")
    if err:
        body = f'<div class="error">{err}</div>' + body
    
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
                return render_layout("Change Password", f'<div class="error">{e}</div><a href="/change-password">Try again</a>')

    body = """
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
                body = "<h3>Enrolment Successful!</h3>"
                if res: # recovery codes
                    body += "<p>Save these recovery codes NOW. They will not be shown again.</p><div class='codes'>"
                    body += "<br>".join(res)
                    body += "</div>"
                body += "<br><a href='/'>Go to login</a>"
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
        <p>Or enter this secret manually: <strong>{res["secret"]}</strong></p>
        <form method="POST">
            <input type="hidden" name="token" value="{token or ''}">
            <input type="hidden" name="login_id" value="{login_id}">
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

    body = f"""
    <div class="box">
        <p><strong>Login ID:</strong> {session['login_id']}</p>
        <p><strong>Role:</strong> {session['role']}</p>
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
                    token = icon_auth.issue_enrol_token(cur, session["login_id"], target, ip=request.remote_addr)
                    msg = f"Token issued. URL: /enrol?login_id={target}&token={token}"
                elif action == "open_window":
                    icon_auth.open_backup_window(cur, session["login_id"], target, ip=request.remote_addr)
                    msg = "Backup window opened for 30 minutes."
                elif action == "reset_totp":
                    token = icon_auth.reset_totp(cur, session["login_id"], target, ip=request.remote_addr)
                    msg = f"TOTP Reset. New URL: /enrol?login_id={target}&token={token}"
            except icon_auth.AuthError as e:
                msg = f"Error: {e}"

    with store.conn() as (cx, cur):
        users = icon_auth.list_users(cur, session["login_id"])
    
    users_html = "<table border=1 cellpadding=5 style='width:100%; border-collapse:collapse; margin-bottom:20px;'>"
    users_html += "<tr><th>ID</th><th>Name</th><th>Role</th><th>Active</th><th>Locked Until</th></tr>"
    for u in users:
        users_html += f"<tr><td>{u['login_id']}</td><td>{u['display_name']}</td><td>{u['role']}</td><td>{u['active']}</td><td>{u['locked_until']}</td></tr>"
    users_html += "</table>"

    body = f"""
    {f"<div class='error' style='color:green;'>{msg}</div>" if msg else ""}
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
    print("Serving lab on http://127.0.0.1:8091")
    serve(app, host="127.0.0.1", port=8091)
