import pytest
import tempfile
import os
import subprocess
import urllib.request
import time
import sys
import shutil

@pytest.fixture(scope="module")
def lab_env():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    tmpdir = tempfile.mkdtemp()
    
    env = dict(os.environ)
    env["ICON_DB_FILE"] = db_path
    env["ICON_AUTH_MAX_FAILS"] = "3"
    env["ICON_AUTH_LOCK_SECONDS"] = "15"
    
    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon_auth_cli.py")
    # Remove stale key from a previous aborted run before creating a new one
    stale_key = os.path.join(os.path.dirname(db_path), ".icon_totp_key")
    if os.path.exists(stale_key):
        os.remove(stale_key)
    subprocess.run([sys.executable, cli_path, "init-key"], env=env, check=True)
    
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_lab", "lab_app.py")
    
    proc = subprocess.Popen([sys.executable, app_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    for _ in range(30):
        try:
            time.sleep(1)
            res = urllib.request.urlopen("http://127.0.0.1:8091/healthz")
            data = res.read().decode()
            if '"ok":true' in data or '"ok": true' in data:
                break
        except:
            pass
        time.sleep(0.5)
        
    yield db_path, tmpdir, proc, env, app_path
    
    proc.terminate()
    proc.wait()
    
    out = proc.stdout.read()
    if out:
        with open("server_debug.log", "w") as f:
            f.write(out)
        print("Wrote server_debug.log")
        
    os.remove(db_path)
    shutil.rmtree(tmpdir)
    key_path = os.path.join(os.path.dirname(db_path), ".icon_totp_key")
    if os.path.exists(key_path):
        os.remove(key_path)
