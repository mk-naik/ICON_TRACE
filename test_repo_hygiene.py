
import os, subprocess, glob

def test_no_nul_bytes_in_tracked_text_files():
    tracked = subprocess.check_output(['git', 'ls-files']).decode('utf-8').splitlines()
    exts = ('.md', '.py', '.js', '.html', '.txt', '.sql', '.gitignore')
    for f in tracked:
        if f.endswith(exts) and os.path.exists(f):
            with open(f, 'rb') as fb:
                content = fb.read()
                assert b'\x00' not in content, f'{f} contains NUL bytes'

def test_git_check_ignore():
    for f in ('.icon_totp_key', '.icon_secret', 'test.db', 'auth_lab/lab.db'):
        res = subprocess.run(['git', 'check-ignore', f], capture_output=True)
        assert res.returncode == 0, f'{f} is not ignored'

def test_no_routes_txt():
    tracked = subprocess.check_output(['git', 'ls-files']).decode('utf-8').splitlines()
    assert 'routes.txt' not in tracked, 'routes.txt is tracked'


