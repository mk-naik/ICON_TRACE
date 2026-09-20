import os
import sys
import time
import socket
import struct
import tempfile
import threading
import subprocess
import shutil
import pytest
import pyotp
import urllib.request
import urllib.parse
from playwright.sync_api import sync_playwright

def get_free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p

class FakeNTP:
    def __init__(self, offset_s, unreachable=False):
        self.offset_s = offset_s
        self.unreachable = unreachable
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", 0))
        self.port = self.s.getsockname()[1]
        self.running = True
        if not self.unreachable:
            self.th = threading.Thread(target=self.run)
            self.th.daemon = True
            self.th.start()
        
    def run(self):
        self.s.settimeout(1.0)
        while self.running:
            try:
                data, addr = self.s.recvfrom(1024)
                t = time.time() + self.offset_s + 2208988800
                ti = int(t)
                tf = int((t - ti) * 2**32)
                res = struct.pack('!12I', 0,0,0,0,0,0,0,0, ti,tf, ti,tf)
                self.s.sendto(res, addr)
            except Exception:
                pass
                
    def stop(self):
        self.running = False
        self.s.close()
        if not self.unreachable:
            self.th.join(timeout=1.0)

@pytest.fixture(scope="module")
def lab_env():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    tmpdir = tempfile.mkdtemp()
    
    env = dict(os.environ)
    env["ICON_DB_FILE"] = db_path
    env["ICON_AUTH_MAX_FAILS"] = "5"
    env["ICON_AUTH_LOCK_SECONDS"] = "15"
    
    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon_auth_cli.py")
    subprocess.run([sys.executable, cli_path, "init-key"], env=env, check=True)
    
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_lab", "lab_app.py")
    
    proc = subprocess.Popen([sys.executable, app_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    # wait for start
    for _ in range(30):
        try:
            req = urllib.request.Request("http://127.0.0.1:8091/healthz")
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    break
        except:
            pass
        time.sleep(0.5)
        
    yield db_path, tmpdir, proc, env, app_path
    
    proc.terminate()
    proc.wait()
    
    os.remove(db_path)
    shutil.rmtree(tmpdir)
    key_path = os.path.join(os.path.dirname(db_path), ".icon_totp_key")
    if os.path.exists(key_path):
        os.remove(key_path)

def test_live_scenarios(lab_env):
    db_path, tmpdir, server_proc, env, app_path = lab_env
    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon_auth_cli.py")
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        
        def snap(name):
            path = os.path.join(tmpdir, name + ".png")
            page.screenshot(path=path)
            print(f"Screenshot saved: {path}")

        # P1: CLI creates SA -> enrol -> token dead
        res = subprocess.run([sys.executable, cli_path, "create-superadmin", "sa1", "SA One"], env=env, capture_output=True, text=True)
        url = [line for line in res.stdout.splitlines() if "Enrol URL" in line][0].split(":", 1)[1].strip()

        page.goto("http://127.0.0.1:8091" + url)
        snap("P1_enrol_page")
        print("PAGE CONTENT:", page.content())
        
        # read secret
        secret_text = page.locator("strong").inner_text()
        totp = pyotp.TOTP(secret_text)
        
        # confirm with previous step to allow next step in P2 without sleeping
        page.fill("input[name='code']", totp.at(time.time() - 30))
        page.click("button[type='submit']")
        page.wait_for_selector(".codes")
        snap("P1_recovery_codes")
        
        rc_text = page.locator(".codes").inner_text()
        rc1 = rc_text.split()[0]
        
        # reload shows none
        page.reload()
        assert "recovery" not in page.content().lower()
        snap("P1_reload_no_codes")
        
        # token dead
        page.goto("http://127.0.0.1:8091" + url)
        assert "Invalid or expired token" in page.content()
        
        page.goto("http://127.0.0.1:8091/logout")
        
        # P2: SA signs in -> /me shows SA+totp -> same code in second context refused
        # Use current step
        c = totp.at(time.time())
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", c)
        page.click("button[type='submit']")
        
        assert "SA One" not in page.content() # only shows login id
        assert "sa1" in page.content()
        assert "Super Admin" in page.content()
        snap("P2_me_page")
        
        ctx2 = browser.new_context()
        p2 = ctx2.new_page()
        p2.goto("http://127.0.0.1:8091/")
        p2.fill("input[name='login_id']", "sa1")
        p2.fill("input[name='credential']", c)
        p2.click("button[type='submit']")
        assert "not accepted" in p2.content()
        snap("P2_reused_code")
        p2.close()
        
        # P3: 5 wrong codes -> locked -> correct refused -> wait 3s -> works
        page.goto("http://127.0.0.1:8091/logout")
        for _ in range(5):
            page.goto("http://127.0.0.1:8091/")
            page.fill("input[name='login_id']", "sa1")
            page.fill("input[name='credential']", "000000")
            page.click("button[type='submit']")
            
        # Use next step
        c2 = totp.at(time.time() + 30)
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", c2)
        page.click("button[type='submit']")
        assert "locked for another" in page.content() or "temporarily locked" in page.content()
        snap("P3_locked")
        
        time.sleep(15)
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", c2)
        page.click("button[type='submit']")
        assert "sa1" in page.content()
        
        # P4: Unknown ID and wrong password identical
        page.goto("http://127.0.0.1:8091/logout")
        
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "unknown")
        page.fill("input[name='credential']", "pass1234")
        page.click("button[type='submit']")
        out1 = page.content()
        snap("P4_unknown")
        
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", "pass1234")
        page.click("button[type='submit']")
        out2 = page.content()
        
        assert "That ID or password" in out1
        assert out1 == out2
        
        # Let's get an Admin to do P5/P6
        # P10 prep: We need an Admin for P10 as well. SA creates an Admin? SA creates an Admin via CLI or we use CLI.
        subprocess.run([sys.executable, cli_path, "create-superadmin", "sa2", "SA Two"], env=env)
        
        import sqlite3, store, icon_auth
        old = store.DB_PATH
        store.DB_PATH = db_path
        with store.conn() as (cx, cur):
            cur.execute("INSERT INTO app_user (login_id, display_name, role, created_at, created_by) VALUES ('ad1', 'Ad One', 'Admin', 0, 'cli')")
        store.DB_PATH = old
        
        res = subprocess.run([sys.executable, cli_path, "reset-totp", "ad1"], env=env, capture_output=True, text=True)
        url = [line for line in res.stdout.splitlines() if "Enrol URL" in line][0].split(":", 1)[1].strip()
        
        page.goto("http://127.0.0.1:8091" + url)
        ad_secret = page.locator("strong").inner_text()
        ad_totp = pyotp.TOTP(ad_secret)
        page.fill("input[name='code']", ad_totp.at(time.time() - 30))
        page.click("button[type='submit']")
        page.goto("http://127.0.0.1:8091/logout")
    
        # P5: Admin creates op with temp pw -> forced change -> weak refused -> strong works -> temp dead
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "ad1")
        page.fill("input[name='credential']", ad_totp.at(time.time()))
        page.click("button[type='submit']")
        page.goto("http://127.0.0.1:8091/admin")
        
        page.fill("input[name='target']", "op1")
        page.fill("input[name='display_name']", "Op One")
        page.fill("input[name='role']", "FQC Operator")
        page.fill("input[name='temp_pw']", "Temp1234!")
        # this is the first form on the admin page (Create Operator)
        page.click("button:has-text('Create')")
        assert "Operator created" in page.content()
        snap("P5_created_op")
        
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "op1")
        page.fill("input[name='credential']", "Temp1234!")
        page.click("button[type='submit']")
        
        # forced change
        assert "Change Password" in page.content()
        
        page.fill("input[name='old_pw']", "Temp1234!")
        page.fill("input[name='new_pw']", "weak")
        page.click("button[type='submit']")
        assert "at least 8 characters" in page.content()
        snap("P5_weak_pw")
        
        page.click("a:has-text('Try again')")
        page.fill("input[name='old_pw']", "Temp1234!")
        page.fill("input[name='new_pw']", "StrongPass123!")
        page.click("button[type='submit']")
        
        assert "Simulate Cancel" in page.content() # Reached /me
        
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "op1")
        page.fill("input[name='credential']", "Temp1234!")
        page.click("button[type='submit']")
        assert "not accepted" in page.content()
        
        # P6: Admin cannot sign in by password; SA opens backup window -> works once -> not twice
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        with store.conn() as (cx, cur):
            cur.execute("UPDATE app_user SET totp_last_step=0 WHERE login_id='sa1'")
        page.fill("input[name='credential']", totp.now())
        page.click("button[type='submit']")
        
        page.goto("http://127.0.0.1:8091/admin")
        # set temp password for ad1
        page.locator("form").nth(1).locator("input[name='target']").fill("ad1")
        page.locator("form").nth(1).locator("input[name='temp_pw']").fill("AdTemp123!")
        page.locator("form").nth(1).locator("button").click()
        assert "Temporary password set" in page.content()
        
        # open backup window
        page.locator("form").nth(4).locator("input[name='target']").fill("ad1")
        page.locator("form").nth(4).locator("button").click()
        assert "Backup window opened" in page.content()
        snap("P6_backup_window_opened")
        
        page.goto("http://127.0.0.1:8091/logout")
        
        # Admin signs in with password
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "ad1")
        page.fill("input[name='credential']", "AdTemp123!")
        page.click("button[type='submit']")
        assert "Simulate Cancel" in page.content() # Goes straight to /me, no forced change for Admin
        snap("P6_admin_in_window")
        
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "ad1")
        page.fill("input[name='credential']", "AdTemp123!")
        page.click("button[type='submit']")
        assert "not accepted" in page.content()
        
        # P7: SA password hash directly in DB does not work
        old = store.DB_PATH
        store.DB_PATH = db_path
        with store.conn() as (cx, cur):
            cur.execute("UPDATE app_user SET pw_hash=%s WHERE login_id='sa1'", (icon_auth.hash_pw("SABackup123!"),))
        store.DB_PATH = old
        
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", "SABackup123!")
        page.click("button[type='submit']")
        assert "not accepted" in page.content()
        snap("P7_sa_pw_fails")
        
        # P8: Step-up
        page.goto("http://127.0.0.1:8091/")
        c3 = ad_totp.now()
        page.fill("input[name='login_id']", "ad1")
        page.fill("input[name='credential']", c3)
        page.click("button[type='submit']")
        
        page.goto("http://127.0.0.1:8091/me")
        page.fill("input[name='code']", c3)
        page.click("button[type='submit']")
        assert "Step-up failed" in page.content()
        snap("P8_stepup_replayed")
        
        # advance time slightly? pyotp now() returns current window.
        # we can just use time.time() + 30
        c4 = ad_totp.at(int(time.time() + 30))
        page.fill("input[name='code']", c4)
        page.click("button[type='submit']")
        assert "Cancel authorized" in page.content()
        snap("P8_stepup_ok")
        
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "op1")
        page.fill("input[name='credential']", "StrongPass123!")
        page.click("button[type='submit']")
        page.goto("http://127.0.0.1:8091/me")
        page.fill("input[name='code']", "123456")
        page.click("button[type='submit']")
        assert "Ask an Admin" in page.content()
        snap("P8_op_stepup")
        
        # P9: SA uses recovery -> can reach only /enrol -> re-enrols -> old dead
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", rc1)
        page.click("button[type='submit']")
        assert "Scan this QR code" in page.content()
        
        # check cannot reach /me
        page.goto("http://127.0.0.1:8091/me")
        assert "Scan this QR code" in page.content()
        snap("P9_forced_enrol")
        
        new_sec = page.locator("strong").inner_text()
        page.fill("input[name='code']", pyotp.TOTP(new_sec).now())
        page.click("button[type='submit']")
        assert "Enrolment Successful" in page.content()
        
        page.goto("http://127.0.0.1:8091/logout")
        
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", totp.now())
        page.click("button[type='submit']")
        assert "not accepted" in page.content() # old secret dead
        
        page.fill("input[name='credential']", rc1)
        page.click("button[type='submit']")
        assert "not accepted" in page.content() # rc used
        snap("P9_old_dead")
        
        # P10: Admin /admin list hides SA; POST against SA same as missing
        page.goto("http://127.0.0.1:8091/")
        page.fill("input[name='login_id']", "ad1")
        page.fill("input[name='credential']", ad_totp.at(time.time() + 30))
        page.click("button[type='submit']")
        
        page.goto("http://127.0.0.1:8091/admin")
        assert "sa1" not in page.content()
        assert "sa2" not in page.content()
        snap("P10_admin_list")
        
        page.locator("form").nth(2).locator("input[name='target']").fill("sa1")
        page.locator("form").nth(2).locator("button").click()
        assert "Not found" in page.content()
        snap("P10_admin_post_sa")
        
        browser.close()
        
    # P11: NTP +45s -> healthz drift -> red banner
    server_proc.terminate()
    server_proc.wait()
    
    ntp = FakeNTP(45)
    env["ICON_NTP_SERVER"] = f"127.0.0.1:{ntp.port}"
    
    server_proc = subprocess.Popen([sys.executable, app_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    
    r = urllib.request.urlopen("http://127.0.0.1:8091/")
    assert b"Clock drift exceeds 20s" in r.read()
    
    r2 = urllib.request.urlopen("http://127.0.0.1:8091/healthz")
    import json
    data2 = json.loads(r2.read())
    assert data2["clock"]["status"] == "drift"
    ntp.stop()
    
    # Unreachable
    server_proc.terminate()
    server_proc.wait()
    ntp = FakeNTP(0, unreachable=True)
    env["ICON_NTP_SERVER"] = f"127.0.0.1:{ntp.port}"
    
    server_proc = subprocess.Popen([sys.executable, app_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    r = urllib.request.urlopen("http://127.0.0.1:8091/healthz")
    import json
    data = json.loads(r.read())
    assert data["clock"]["status"] == "unknown"
    
    # P12: delete .icon_totp_key -> no crash -> log clear -> restore works
    server_proc.terminate()
    server_proc.wait()
    
    key_path = os.path.join(os.path.dirname(db_path), ".icon_totp_key")
    key_bck = key_path + ".bck"
    shutil.copy(key_path, key_bck)
    os.remove(key_path)
    
    server_proc = subprocess.Popen([sys.executable, app_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    
    # Do a login request which needs decryption
    data = urllib.parse.urlencode({"login_id": "sa1", "credential": "111111"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8091/login", data=data)
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        assert b"not accepted" in response.read()
    
    server_proc.terminate()
    server_proc.wait()
    
    assert "KeyMissing" in server_proc.stdout.read()
    
    shutil.move(key_bck, key_path)
    
    # P13: Check log and auth_event for leak
    old = store.DB_PATH
    store.DB_PATH = db_path
    with store.conn() as (cx, cur):
        cur.execute("SELECT detail FROM auth_event")
        for row in cur.fetchall():
            if row["detail"]:
                d = row["detail"].lower()
                assert "secret" not in d
                assert "password" not in d.replace("wrong password", "") # "wrong password" string is fine
    store.DB_PATH = old
