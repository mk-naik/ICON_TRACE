import pytest
from playwright.sync_api import sync_playwright
import icon_auth
import store
import pyotp
import sqlite3
import subprocess
import os
import sys

def test_xss_escaping(lab_env):
    db_path, tmpdir, server_proc, env, app_path = lab_env
    url = f"http://127.0.0.1:{env.get('FLASK_RUN_PORT', '8091')}"

    cli_path = os.path.join(os.path.dirname(os.path.abspath(icon_auth.__file__)), "icon_auth_cli.py")

    # Create superadmin to login
    subprocess.run([sys.executable, cli_path, "create-superadmin", "alice", "Alice"], env=env, capture_output=True, text=True, check=True)

    # Inject XSS into Alice's display name directly via sqlite, and enrol a
    # TOTP secret directly rather than a password: rank 3 (Super Admin)
    # cannot log in with a password at all (icon_auth.login() blocks it -
    # "sa pw login blocked" - by design, so a real superadmin session can
    # only come from TOTP or a recovery code). Encrypted with the same key
    # icon_auth itself uses, so decrypt_secret() in the login path works.
    # store.DB_PATH is a module-level global read once at import time - the
    # env var alone is not enough once another test in the same pytest
    # session has already imported store with a different fixture's
    # db_path (test_icon_auth.py's own fixture sets this the same way).
    os.environ["ICON_DB_FILE"] = db_path
    store.DB_PATH = db_path
    secret = pyotp.random_base32()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_user SET display_name=?, totp_secret_enc=?, must_reenrol=0 WHERE login_id=?",
        ("<script>document.body.innerHTML='HACKED';</script>", icon_auth.encrypt_secret(secret), "alice"))
    conn.commit()
    conn.close()

    code = pyotp.TOTP(secret).now()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(f"{url}/")
        page.fill("input[name=login_id]", "alice")
        page.fill("input[name=credential]", code)
        page.click("button[type=submit]")
        page.wait_for_url("**/me")

        page.goto(f"{url}/admin")
        page.wait_for_selector("table")

        # "HACKED" not in body_text is not the right check: the payload's
        # own text literally contains the word "HACKED", so it is always a
        # substring of the escaped, inert text too. What actually proves
        # the script never ran is that document.body.innerHTML was never
        # replaced by it - the real page (nav bar, admin forms) is still
        # there - and that the payload appears HTML-escaped, not raw.
        body_text = page.evaluate("document.body.innerHTML")
        assert page.locator(".nav").count() > 0, \
            "the page's own nav bar is gone - document.body.innerHTML was overwritten, the script ran"
        assert "<script>document.body.innerHTML" not in body_text, \
            "XSS vulnerability found! the payload rendered as a live <script> tag, unescaped"
        assert "&lt;script&gt;document.body.innerHTML" in body_text, \
            "display_name should render escaped, not stripped or otherwise altered"

        browser.close()
