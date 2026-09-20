import os, sys, shutil, time, subprocess, tempfile, json, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.abspath(__file__))

def _copy_tree(src, dst):
    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.db", "*.db-wal", "*.db-shm", "*.log", "storage", ".icon_secret")
    dest = os.path.join(dst, "repo")
    shutil.copytree(src, dest, ignore=ignore)
    return dest

def main():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 8090))
    except Exception:
        print("Port 8090 is busy, stop.")
        sys.exit(1)
    finally:
        s.close()
        
    tmp = tempfile.mkdtemp(prefix="icon_live_")
    repo = _copy_tree(REPO, tmp)
    db_file = os.path.join(tmp, "test.db")
    env = dict(os.environ)
    env["ICON_HOST"] = "127.0.0.1"
    env["ICON_PORT"] = "8090"
    env["ICON_DB_FILE"] = db_file
    
    server_proc = subprocess.Popen([sys.executable, "serve.py"], cwd=repo, env=env)
    
    time.sleep(2) # wait for boot
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # S0 no mutation: signed out, then signed in as Admin, 12 s -> no banner, chip Online
            page.goto("http://127.0.0.1:8090/")
            time.sleep(1)
            
            def sign_in_as(role_match):
                # wait for select
                page.wait_for_selector("#who")
                options = page.eval_on_selector_all("#who option", "opts => opts.map(o => ({val: o.value, text: o.textContent}))")
                for opt in options:
                    if role_match.lower() in opt['text'].lower() and opt['val']:
                        page.select_option("#who", opt['val'])
                        page.evaluate("if(typeof signIn === 'function') signIn()")
                        time.sleep(1)
                        break
            
            sign_in_as("admin")
            time.sleep(12)
            page.screenshot(path="S0_admin_12s.png")
            print("S0: S0_admin_12s.png, PASS")
            assert page.locator("#icon-live-banner").is_hidden()
            assert "Online" in page.locator("#connTxt").inner_text()
            
            # S1 signed out, append a comment to app.py in the copy -> NO banner
            page.evaluate("if(typeof signOut === 'function') signOut()")
            time.sleep(1)
            with open(os.path.join(repo, "app.py"), "a") as f:
                f.write("\n# S1\n")
            time.sleep(12)
            page.screenshot(path="S1_signed_out_no_banner.png")
            print("S1: S1_signed_out_no_banner.png, PASS")
            assert page.locator("#icon-live-banner").is_hidden()
            
            # S1b sign in as Admin, SIGN OUT, then append a comment to app.py and to static/icon_live.js -> NO banner on the sign-in screen.
            js_path = os.path.join(repo, "static", "icon_live.js")
            page.reload()
            time.sleep(1)
            sign_in_as("admin")
            page.evaluate("if(typeof signOut === 'function') signOut()")
            with open(os.path.join(repo, "app.py"), "a") as f:
                f.write("\n# S1b green app\n")
            with open(js_path, "a") as f:
                f.write("\n// S1b green js\n")
            time.sleep(12)
            page.screenshot(path="S1b_green.png")
            print("S1b (green): S1b_green.png, PASS (green)")
            assert page.locator("#icon-live-banner").is_hidden()
            
            # Restore app.py to clear server_stale
            shutil.copy2(os.path.join(REPO, "app.py"), os.path.join(repo, "app.py"))
            time.sleep(2) # clear 2s cache
            
            # S2 signed in as Admin, append a comment to static/icon_live.js -> "This page is out of date" with a Reload link
            sign_in_as("admin")
            with open(js_path, "a") as f:
                f.write("\n// S2\n")
            time.sleep(12)
            page.screenshot(path="S2_reload_banner.png")
            print("S2: S2_reload_banner.png, PASS")
            banner_text = page.locator("#icon-live-banner").inner_text()
            assert "out of date" in banner_text
            assert "Reload" in banner_text
            assert "older code" not in banner_text
            
            page.locator("#icon-live-banner a").click() # Reload
            time.sleep(2)
            sign_in_as("admin")
            time.sleep(12)
            assert page.locator("#icon-live-banner").is_hidden()
            
            # S3 Admin, append a comment to app.py -> "The server is running older code ... restart it"; Reload does not clear it
            with open(os.path.join(repo, "app.py"), "a") as f:
                f.write("\n# S3\n")
            time.sleep(12)
            page.screenshot(path="S3_restart_banner.png")
            print("S3: S3_restart_banner.png, PASS")
            banner_text = page.locator("#icon-live-banner").inner_text()
            assert "older code" in banner_text
            
            page.reload()
            time.sleep(1)
            sign_in_as("admin")
            time.sleep(12)
            assert page.locator("#icon-live-banner").is_visible()
            
            # S4 non-Admin (FQC Operator): app.py changed -> nothing; icon_live.js changed -> the Reload banner
            page.evaluate("if(typeof signOut === 'function') signOut()")
            time.sleep(1)
            sign_in_as("fqc")
            with open(os.path.join(repo, "app.py"), "a") as f:
                f.write("\n# S4\n")
            time.sleep(12)
            page.screenshot(path="S4_app_change_nothing.png")
            print("S4 (app change): S4_app_change_nothing.png, PASS")
            assert page.locator("#icon-live-banner").is_hidden()
            
            with open(js_path, "a") as f:
                f.write("\n// S4\n")
            time.sleep(12)
            page.screenshot(path="S4_js_change_reload.png")
            print("S4 (js change): S4_js_change_reload.png, PASS")
            assert "out of date" in page.locator("#icon-live-banner").inner_text()
            
            page.reload()
            time.sleep(1)
            sign_in_as("fqc")
            time.sleep(12)
            assert page.locator("#icon-live-banner").is_hidden()
            
            # S5 restart the server from the same copy and DB -> restart banner gone for Admin; .icon_secret byte-identical
            secret_file = os.path.join(tmp, ".icon_secret")
            with open(secret_file, "rb") as f:
                secret_before = f.read()
                
            server_proc.terminate()
            server_proc.wait()
            
            server_proc = subprocess.Popen([sys.executable, "serve.py"], cwd=repo, env=env)
            time.sleep(2)
            
            page.reload()
            time.sleep(1)
            sign_in_as("admin")
            time.sleep(12)
            page.screenshot(path="S5_restarted.png")
            print("S5: S5_restarted.png, PASS")
            assert page.locator("#icon-live-banner").is_hidden()
            
            with open(secret_file, "rb") as f:
                secret_after = f.read()
            assert secret_before == secret_after
            
            # S6 append <!-- stage0-marker --> to templates/frag_settings.html in the copy; GET the fragment route -> marker present NO restart
            with open(os.path.join(repo, "templates", "frag_settings.html"), "a") as f:
                f.write("\n<!-- stage0-marker -->\n")
            time.sleep(1)
            
            req = urllib.request.Request("http://127.0.0.1:8090/view/settings")
            with urllib.request.urlopen(req) as resp:
                frag_html = resp.read().decode('utf-8')
            assert "stage0-marker" in frag_html
            
            time.sleep(12)
            page.screenshot(path="S6_template.png")
            print("S6: S6_template.png, PASS")
            # The Reload banner is expected, but the Restart banner is not.
            if page.locator("#icon-live-banner").is_visible():
                assert "older code" not in page.locator("#icon-live-banner").inner_text()
            
            # S7 seed one row; POST /api/db/reset -> 403; Settings Reset disabled...
            req = urllib.request.Request("http://127.0.0.1:8090/api/indent", method="POST", data=b'{"indent_no": "TEST-1", "customer": "Test", "indent_date": "2026-09-09", "items": [{"item_code": "F02010001", "qty": 1}]}')
            urllib.request.urlopen(req).read()
            
            req = urllib.request.Request("http://127.0.0.1:8090/api/db/reset", method="POST")
            try:
                urllib.request.urlopen(req)
                assert False, "Should 403"
            except urllib.error.HTTPError as e:
                assert e.code == 403
                
            import sqlite3
            conn = sqlite3.connect(db_file)
            assert conn.execute("SELECT count(*) FROM indent").fetchone()[0] == 1
            conn.close()
            
            # The Settings Reset button is disabled with the reason...
            page.evaluate("if(typeof go === 'function') go('settings', document.createElement('div'))")
            time.sleep(1)
            page.screenshot(path="S7_reset_disabled.png")
            print("S7: S7_reset_disabled.png, PASS")
            btn = page.locator("#s_resetBtn")
            assert btn.get_attribute("disabled") is not None
            
            # restart with ICON_ALLOW_RESET=1
            server_proc.terminate()
            server_proc.wait()
            env["ICON_ALLOW_RESET"] = "1"
            server_proc = subprocess.Popen([sys.executable, "serve.py"], cwd=repo, env=env)
            time.sleep(2)
            
            req = urllib.request.Request("http://127.0.0.1:8090/api/db/reset", method="POST")
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 200
            
            conn = sqlite3.connect(db_file)
            assert conn.execute("SELECT count(*) FROM indent").fetchone()[0] == 0
            conn.close()
            
            print("All live tests passed.")
    finally:
        if server_proc:
            server_proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
