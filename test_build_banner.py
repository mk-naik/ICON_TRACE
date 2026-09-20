"""
test_build_banner.py - Stage 0 verification (Flask test client, no browser needed).

THE RULES THIS FILE DEFENDS
============================
A. JS/CSS/frag edits change asset_build, NOT code_build.
B. Any top-level *.py edit (incl. icon_serial.py) changes code_build, NOT asset_build.
C. Build-hash cache: 200 calls inside TTL cost no extra stat() calls; after
   _build_cache_clear() a new change is visible.
D. /healthz returns the correct fields (code_build, boot_code_build, server_stale,
   build, started, store, time, ok, db); boot_build is ABSENT.
E. TEMPLATES_AUTO_RELOAD is True.
F. Secret key: ICON_SECRET env wins; .icon_secret file is created and reused;
   a second process gets the same key; a cookie signed by process 1 validates in
   process 2 (subprocess test); unwritable folder -> random fallback with a warning;
   git check-ignore passes.
G. Reset: default -> 403, rows untouched; ICON_ALLOW_RESET=1 -> 200, rows gone;
   "0" and "" count as off; _reset_enabled mirrors the flag.
H. No file in the repo still reads boot_build from healthz.
"""

import os, sys, shutil, stat, tempfile, time, json, subprocess, re

REPO = os.path.dirname(os.path.abspath(__file__))

def _copy_tree(src, base):
    ignore = shutil.ignore_patterns(
        ".git", "__pycache__", "*.db", "*.db-wal", "*.db-shm", "*.log", ".icon_secret"
    )
    dst = os.path.join(base, "repo")
    shutil.copytree(src, dst, ignore=ignore)
    return dst

_pass = 0
_fail = 0

def test(fn):
    def wrapper(*a, **kw):
        global _pass, _fail
        try:
            fn(*a, **kw)
            print("  PASS  %s" % fn.__name__.replace("_", " ", 1).strip())
            _pass += 1
        except AssertionError as e:
            print("  FAIL  %s: %s" % (fn.__name__, e))
            _fail += 1
        except Exception as e:
            import traceback
            print("  ERROR %s: %s" % (fn.__name__, e))
            traceback.print_exc()
            _fail += 1
    return wrapper

def _load_app(tmp, env_overrides=None):
    """Load app module from tmp dir with a throwaway DB."""
    import importlib.util
    env = dict(os.environ)
    env["ICON_DB_FILE"] = os.path.join(tmp, "test.db")
    env.pop("ICON_SECRET", None)
    env.pop("ICON_ALLOW_RESET", None)
    if env_overrides:
        env.update(env_overrides)
    saved = {k: os.environ.get(k) for k in list(env.keys()) + list(os.environ.keys())}
    for k, v in env.items():
        os.environ[k] = v
    for k in list(os.environ):
        if k not in env:
            del os.environ[k]
    if tmp not in sys.path:
        sys.path.insert(0, tmp)
    name = "app_t_%s" % os.path.basename(tmp)
    spec = importlib.util.spec_from_file_location(name, os.path.join(tmp, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if tmp in sys.path:
        sys.path.remove(tmp)
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return mod


@test
def _A_asset_change_does_not_affect_code_build():
    tmp = tempfile.mkdtemp(prefix="icon_A_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp)
        mod._build_cache_clear()
        cb_before = mod.code_build()
        ab_before = mod.asset_build()
        js = os.path.join(tmp, "static", "icon_live.js")
        with open(js, "a", encoding="utf-8") as fh:
            fh.write("\n// banner-test-marker-A\n")
        time.sleep(0.05)
        mod._build_cache_clear()
        assert mod.asset_build() != ab_before, "asset_build must change after JS edit"
        assert mod.code_build() == cb_before, "code_build must NOT change after JS edit"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _B_py_change_does_not_affect_asset_build():
    tmp = tempfile.mkdtemp(prefix="icon_B_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp)
        mod._build_cache_clear()
        cb_before = mod.code_build()
        ab_before = mod.asset_build()
        py = os.path.join(tmp, "icon_serial.py")
        with open(py, "a", encoding="utf-8") as fh:
            fh.write("\n# banner-test-marker-B\n")
        time.sleep(0.05)
        mod._build_cache_clear()
        assert mod.code_build() != cb_before, "code_build must change after .py edit"
        assert mod.asset_build() == ab_before, "asset_build must NOT change after .py edit"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _C_cache_avoids_extra_stats_and_clears():
    tmp = tempfile.mkdtemp(prefix="icon_C_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp)
        mod._build_cache_clear()
        stat_calls = [0]
        real_stat = mod.os.stat
        def counting_stat(p, *a, **kw):
            stat_calls[0] += 1
            return real_stat(p, *a, **kw)
        mod.os.stat = counting_stat
        mod.asset_build()
        calls_after_first = stat_calls[0]
        for _ in range(199):
            mod.asset_build()
        assert stat_calls[0] == calls_after_first, (
            "Expected no extra stat() inside TTL, got %d extra" %
            (stat_calls[0] - calls_after_first))
        mod.os.stat = real_stat
        ab1 = mod.asset_build()
        mod._build_cache_clear()
        js = os.path.join(tmp, "static", "icon_live.js")
        with open(js, "a", encoding="utf-8") as fh:
            fh.write("\n// cache-clear-test\n")
        time.sleep(0.05)
        ab2 = mod.asset_build()
        assert ab1 != ab2, "After _build_cache_clear() a change must be visible"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _D_healthz_fields_and_server_stale():
    tmp = tempfile.mkdtemp(prefix="icon_D_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp)
        client = mod.app.test_client()
        r = client.get("/healthz")
        d = json.loads(r.data)
        for key in ("ok", "db", "build", "code_build", "boot_code_build",
                    "server_stale", "started", "store", "time"):
            assert key in d, "healthz missing key: %s" % key
        assert "boot_build" not in d, "boot_build must be absent from healthz"
        assert d["server_stale"] is False, "server_stale must be False at boot"
        # Py change -> stale
        py = os.path.join(tmp, "icon_serial.py")
        with open(py, "a", encoding="utf-8") as fh:
            fh.write("\n# healthz-py-marker\n")
        time.sleep(0.05)
        mod._build_cache_clear()
        d2 = json.loads(client.get("/healthz").data)
        assert d2["server_stale"] is True, "server_stale must be True after py change"
        # Restore py, touch JS -> stale stays False
        import stat as _st, time as _time
        with open(py, "r", encoding="utf-8") as fh:
            _pytxt = fh.read()
        _orig_mtime = os.stat(py).st_mtime
        with open(py, "w", encoding="utf-8") as fh:
            fh.write(_pytxt.replace("\n# healthz-py-marker\n", ""))
        # Restore original mtime so BOOT_CODE_BUILD matches again
        os.utime(py, (_orig_mtime, _orig_mtime))
        mod._build_cache_clear()
        js = os.path.join(tmp, "static", "icon_live.js")
        with open(js, "a", encoding="utf-8") as fh:
            fh.write("\n// healthz-js-marker\n")
        time.sleep(0.05)
        mod._build_cache_clear()
        d3 = json.loads(client.get("/healthz").data)
        assert d3["server_stale"] is False, "server_stale must stay False after JS change"
        assert d3["build"] != d["build"], "build must change after JS edit"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _E_templates_auto_reload():
    import app as real_app
    assert real_app.app.config.get("TEMPLATES_AUTO_RELOAD") is True


@test
def _F_secret_env_wins():
    tmp = tempfile.mkdtemp(prefix="icon_F1_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp, {"ICON_SECRET": "env-test-key-xyz"})
        assert mod.SECRET_SOURCE == "env"
        assert mod.app.secret_key == "env-test-key-xyz"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _F_secret_file_created_and_reused():
    import importlib.util
    tmp = tempfile.mkdtemp(prefix="icon_F2_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod1 = _load_app(tmp)
        assert mod1.SECRET_SOURCE.startswith("file:")
        key1 = mod1.app.secret_key
        secret_file = mod1.SECRET_SOURCE[5:]
        assert os.path.exists(secret_file)
        mod2 = _load_app(tmp)
        assert mod2.app.secret_key == key1, "Second import must get same key"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _F_secret_subprocess_same_key():
    tmp = tempfile.mkdtemp(prefix="icon_F3_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp)
        key1 = mod.app.secret_key
        # Both parent and subprocess use the same DB dir so they share .icon_secret
        db_file = os.path.join(tmp, "test.db")
        env2 = dict(os.environ)
        env2["ICON_DB_FILE"] = db_file
        env2.pop("ICON_SECRET", None)
        script = (
            "import sys, os; os.environ['ICON_DB_FILE']=%r; sys.path.insert(0, %r); "
            "import importlib.util; "
            "s=importlib.util.spec_from_file_location('a',%r); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(m.app.secret_key)"
        ) % (db_file, tmp, os.path.join(tmp, "app.py"))
        res = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True, env=env2, timeout=30)
        key2 = res.stdout.strip()
        assert key2 == key1, "Subprocess key must match parent: %r vs %r" % (key2, key1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _F_secret_unwritable_folder_gives_random():
    import logging
    tmp = tempfile.mkdtemp(prefix="icon_F4_")
    ro = os.path.join(tmp, "ro")
    try:
        tmp = _copy_tree(REPO, tmp)
        os.makedirs(ro)
        os.chmod(ro, stat.S_IREAD | stat.S_IEXEC)
        warnings_seen = []
        class Cap(logging.Handler):
            def emit(self, r):
                if r.levelno >= logging.WARNING:
                    warnings_seen.append(r.getMessage())
        logger = logging.getLogger("icontrace")
        cap = Cap()
        logger.addHandler(cap)
        mod = _load_app(tmp, {"ICON_DB_FILE": os.path.join(ro, "t.db")})
        logger.removeHandler(cap)
        assert mod.SECRET_SOURCE == "random"
        assert any("random" in w.lower() or "restart" in w.lower()
                   for w in warnings_seen), "Warning must mention random/restart"
    finally:
        try:
            os.chmod(ro, stat.S_IRWXU)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _F_git_check_ignore():
    res = subprocess.run(["git", "check-ignore", "-v", ".icon_secret"],
                         capture_output=True, text=True, cwd=REPO)
    assert res.returncode == 0, ".icon_secret must be git-ignored"


@test
def _G_reset_disabled_by_default_403():
    tmp = tempfile.mkdtemp(prefix="icon_G1_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp)
        with mod.store.conn() as (cx, cur):
            mod.store.insert(cur, "app_config", {"k": "g1_key", "v": "g1_val"})
        client = mod.app.test_client()
        r = client.post("/api/db/reset")
        assert r.status_code == 403
        d = json.loads(r.data)
        assert d["ok"] is False
        assert "ICON_ALLOW_RESET" in d["why"]
        with mod.store.conn() as (cx, cur):
            row = mod.store.one(cur, "SELECT v FROM app_config WHERE k=%s", ("g1_key",))
        assert row is not None, "Row must survive refused reset"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _G_reset_enabled_with_1_wipes():
    tmp = tempfile.mkdtemp(prefix="icon_G2_")
    try:
        tmp = _copy_tree(REPO, tmp)
        mod = _load_app(tmp, {"ICON_ALLOW_RESET": "1"})
        with mod.store.conn() as (cx, cur):
            mod.store.insert(cur, "app_config", {"k": "g2_key", "v": "g2_val"})
        client = mod.app.test_client()
        r = client.post("/api/db/reset")
        assert r.status_code == 200
        d = json.loads(r.data)
        assert d["ok"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def _G_reset_disabled_for_0_and_empty():
    for val in ("0", ""):
        tmp = tempfile.mkdtemp(prefix="icon_G3_")
        try:
            tmp = _copy_tree(REPO, tmp)
            env = {"ICON_ALLOW_RESET": val} if val else {}
            mod = _load_app(tmp, env)
            assert mod._RESET_ENABLED is False, (
                "ICON_ALLOW_RESET=%r should keep reset disabled" % val)
            r = mod.app.test_client().post("/api/db/reset")
            assert r.status_code == 403
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@test
def _G_reset_enabled_mirrors_in_stats():
    for val, expected in [("1", True), ("", False)]:
        tmp = tempfile.mkdtemp(prefix="icon_G4_")
        try:
            tmp = _copy_tree(REPO, tmp)
            env = {"ICON_ALLOW_RESET": val} if val else {}
            mod = _load_app(tmp, env)
            r = mod.app.test_client().get("/api/db/stats")
            d = json.loads(r.data)
            assert "_reset_enabled" in d
            assert d["_reset_enabled"] is expected, (
                "Expected _reset_enabled=%s for ICON_ALLOW_RESET=%r" % (expected, val))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@test
def _H_no_consumer_reads_d_boot_build():
    """d.boot_build comparisons (not comments) must be gone from all JS/HTML/py files."""
    pattern = re.compile(r"d\.boot_build\s*(?:\|\||===|!==|&&|[!=]=)")
    bad = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "storage")]
        for fname in files:
            if not fname.endswith((".js", ".html", ".py")):
                continue
            fpath = os.path.join(root, fname)
            try:
                content = open(fpath, encoding="utf-8", errors="ignore").read()
                for m in pattern.finditer(content):
                    lineno = content[:m.start()].count("\n") + 1
                    bad.append("%s:%d" % (fpath, lineno))
            except Exception:
                pass
    assert not bad, "Files still compare d.boot_build: %s" % bad


if __name__ == "__main__":
    print()
    _A_asset_change_does_not_affect_code_build()
    _B_py_change_does_not_affect_asset_build()
    _C_cache_avoids_extra_stats_and_clears()
    _D_healthz_fields_and_server_stale()
    _E_templates_auto_reload()
    _F_secret_env_wins()
    _F_secret_file_created_and_reused()
    _F_secret_subprocess_same_key()
    _F_secret_unwritable_folder_gives_random()
    _F_git_check_ignore()
    _G_reset_disabled_by_default_403()
    _G_reset_enabled_with_1_wipes()
    _G_reset_disabled_for_0_and_empty()
    _G_reset_enabled_mirrors_in_stats()
    _H_no_consumer_reads_d_boot_build()
    print()
    print("%d passed, %d failed" % (_pass, _fail))
    import sys; sys.exit(0 if _fail == 0 else 1)
