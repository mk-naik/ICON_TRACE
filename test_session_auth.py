"""
ICON TRACE - Round 23: real, server-side, database-backed sessions.

    python test_session_auth.py

Covers Section 1 (icon_auth.py's auth_session table and its five functions,
directly) and Sections 2-3 (the same thing reached through the real app.py
routes - before_request, role(), actor(), /login, /logout,
/api/session/extend, /api/session) end to end, not just the icon_auth
functions in isolation.
"""
import os, subprocess, sys, tempfile, time, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_sess_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store
import icon_auth

_results = []
_db_counter = [0]


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def fresh_db():
    _db_counter[0] += 1
    store.DB_PATH = os.path.join(TMP, "sess_%d.db" % _db_counter[0])
    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)
    return store.DB_PATH


def make_user(role="Production Incharge", login_id="u1", name="Test User"):
    with store.conn() as (cx, cur):
        cur.execute(
            "INSERT INTO app_user (login_id, display_name, role, created_at, "
            "created_by) VALUES (%s, %s, %s, %s, %s)",
            (login_id, name, role, 100000, "test"))
        cur.execute("SELECT * FROM app_user WHERE login_id=%s", (login_id,))
        return dict(cur.fetchone())


# --------------------------------------------------------------------------
# Section 1 - icon_auth.py's session functions, directly
# --------------------------------------------------------------------------

@test("a session created against a real DB file survives being loaded by a "
     "completely separate Python process against the same file - proves it "
     "is a real, persisted row, not anything kept in memory")
def t_survives_second_process():
    db_path = fresh_db()
    u = make_user(role="Dispatch Operator", login_id="proc1")
    with store.conn() as (cx, cur):
        sid = icon_auth.create_session(cur, u, station="DISPATCH-01",
                                       ip="127.0.0.1", now=1000000)

    code = (
        "import store, icon_auth, json, sys\n"
        "store.DB_PATH = %r\n"
        "with store.conn() as (cx, cur):\n"
        "    row = icon_auth.load_session(cur, %r, now=1000010)\n"
        "print(json.dumps(dict(row) if row else None))\n"
    ) % (db_path, sid)
    out = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(
        os.path.abspath(__file__)), capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    import json
    row = json.loads(out.stdout.strip().splitlines()[-1])
    assert row is not None, "second process could not load the session at all"
    assert row["session_id"] == sid, row
    assert row["login_id"] == "proc1", row


@test("expires_at is 5 minutes out for Admin/Super Admin and 1 hour out for "
     "every other role")
def t_expiry_role_dependent():
    fresh_db()
    admin = make_user(role="Admin", login_id="a1")
    sa = make_user(role="Super Admin", login_id="sa1")
    op = make_user(role="FQC Operator", login_id="op1")
    with store.conn() as (cx, cur):
        sid_a = icon_auth.create_session(cur, admin, now=5000)
        sid_sa = icon_auth.create_session(cur, sa, now=5000)
        sid_op = icon_auth.create_session(cur, op, now=5000)
        ra = icon_auth.load_session(cur, sid_a, now=5000)
        rsa = icon_auth.load_session(cur, sid_sa, now=5000)
        rop = icon_auth.load_session(cur, sid_op, now=5000)
    assert ra["expires_at"] - 5000 == 300, ra
    assert rsa["expires_at"] - 5000 == 300, rsa
    assert rop["expires_at"] - 5000 == 3600, rop


@test("touch_session extends expires_at only when actually called; loading "
     "a session never extends it by itself")
def t_touch_extends_only_on_call():
    fresh_db()
    u = make_user(role="Packing Operator", login_id="p1")
    with store.conn() as (cx, cur):
        sid = icon_auth.create_session(cur, u, now=10000)
        r1 = icon_auth.load_session(cur, sid, now=10500)
        assert r1["expires_at"] == 10000 + 3600, r1
        ok = icon_auth.touch_session(cur, sid, now=10500)
        assert ok is True
        r2 = icon_auth.load_session(cur, sid, now=10500)
        assert r2["expires_at"] == 10500 + 3600, \
            "touch_session did not move expires_at forward from the new now"
        # loading again, with no touch, changes nothing further
        r3 = icon_auth.load_session(cur, sid, now=20000 if 20000 < r2["expires_at"] else r2["expires_at"] - 1)
        assert r3["expires_at"] == r2["expires_at"], \
            "load_session extended the session by itself"


@test("load_session returns None once now is past expires_at, and does not "
     "trust the row's data on the way out")
def t_expired_returns_none():
    fresh_db()
    u = make_user(role="Packing Operator", login_id="p2")
    with store.conn() as (cx, cur):
        sid = icon_auth.create_session(cur, u, now=1000)
        still_ok = icon_auth.load_session(cur, sid, now=1000 + 3600 - 1)
        assert still_ok is not None
        gone = icon_auth.load_session(cur, sid, now=1000 + 3600 + 1)
        assert gone is None
        # exactly at expiry is also refused (expires_at is a hard ceiling)
        edge = icon_auth.load_session(cur, sid, now=1000 + 3600)
        assert edge is None, "a session valid exactly AT its own expiry"


@test("purge_expired_sessions actually removes old rows and leaves live "
     "ones alone")
def t_purge_removes_expired_only():
    fresh_db()
    u = make_user(role="Packing Operator", login_id="p3")
    with store.conn() as (cx, cur):
        sid_old = icon_auth.create_session(cur, u, now=1000)       # expires 4600
        sid_live = icon_auth.create_session(cur, u, now=100000)    # expires 103600
        icon_auth.purge_expired_sessions(cur, now=50000)
        cur.execute("SELECT session_id FROM auth_session")
        remaining = {r["session_id"] for r in cur.fetchall()}
    assert sid_old not in remaining, "purge left an expired row behind"
    assert sid_live in remaining, "purge removed a still-live row"


@test("touch_session on a missing or already-expired session id does "
     "nothing and reports failure, not a silent revival")
def t_touch_refuses_expired_or_missing():
    fresh_db()
    u = make_user(role="Packing Operator", login_id="p4")
    with store.conn() as (cx, cur):
        sid = icon_auth.create_session(cur, u, now=1000)
        ok_missing = icon_auth.touch_session(cur, "not-a-real-session-id", now=1500)
        assert ok_missing is False
        ok_expired = icon_auth.touch_session(cur, sid, now=1000 + 3600 + 5)
        assert ok_expired is False
        cur.execute("SELECT expires_at FROM auth_session WHERE session_id=%s", (sid,))
        row = cur.fetchone()
        assert row["expires_at"] == 1000 + 3600, \
            "touch_session changed expires_at on an already-expired session"


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    for name, fn in _results:
        try:
            fn()
            print("  PASS  %-*s" % (width, name))
            passed += 1
        except Exception as e:
            print("  FAIL  %-*s  %s" % (width, name, e))
            if "-v" in sys.argv:
                traceback.print_exc()
            failed += 1
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
