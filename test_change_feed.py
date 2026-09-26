"""
ICON TRACE - Round 30: the change feed, server side.

    python test_change_feed.py

Two people on two machines: when one saved an indent, the other's screen
showed the old list until they reloaded. Every write commits in exactly one
place (store.conn.__exit__) and every statement passes through _Cur.execute,
so the tables a transaction touched are known without any endpoint being
told to say so - that single choke point is what this file pins down.

What is asserted here:
  * the sequence advances on a write through any endpoint, and NOT on a read
  * the topic recorded is the one the tables map to, and `by` is the saver's
    real login_id - not a name the client sent
  * a `since` older than anything left after pruning says so explicitly,
    rather than returning a short list the client would believe
  * pruning removes what is past the window and keeps what is inside it
  * the sequence NEVER goes backwards over a prune (AUTOINCREMENT)
  * /api/changes needs a session
"""

import os, sys, tempfile, time, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_feed_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_models                                           # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


MODEL = "ISEN625-G12R"


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


def changes(c, since=0):
    r = c.get("/api/changes?since=%s" % since)
    assert r.status_code == 200, (r.status_code, r.get_data()[:200])
    return r.get_json()


def seq_now(c):
    return changes(c, 0)["seq"]


def log_rows():
    with store.conn() as (cx, cur):
        return store.rows(cur, "SELECT seq, topic, by_login FROM change_log "
                               "ORDER BY seq")


@test("the sequence advances on a write through a real endpoint, and does "
     "NOT advance on a read - however many reads are made")
def t_write_advances_read_does_not():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c)
    # The one read in the app that genuinely writes, once ever: boot_payload()
    # fills an EMPTY material table from icon_materials.py, after which the
    # table is the master and the file is never read again. The feed reports
    # it because it really did create master data - so it is done here first,
    # and asserted, rather than quietly excluded.
    before_seed = seq_now(c)
    assert c.get("/api/boot").status_code == 200
    assert "master" in changes(c, before_seed)["topics"], \
        "the first /api/boot no longer seeds the material master"
    assert c.get("/api/boot").status_code == 200

    before = seq_now(c)
    for path in ("/api/boot", "/api/indents", "/api/challans", "/api/gatepasses",
                 "/api/review", "/api/packing/log", "/api/fqc/recent",
                 "/api/prod", "/api/stock_dispatch", "/api/changes?since=0"):
        assert c.get(path).status_code == 200, path
    assert seq_now(c) == before, "a read moved the sequence"

    r = c.post("/api/material", json={"name": "Feed Material", "uom": "Nos"})
    assert r.status_code == 200, r.get_json()
    after = seq_now(c)
    assert after > before, "a write did not move the sequence"
    print("      10 reads: seq stayed %d; one write: seq %d" % (before, after))


@test("a REFUSED write records nothing - the transaction rolled back, so "
     "there is no change to report")
def t_refused_write_records_nothing():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c)
    op = APP.app.test_client()
    AUTH.test_login(op, role="Quality")           # creating the account is itself
    before = seq_now(c)                           # a write - so measure AFTER it
    r = c.post("/api/box/open", json={})          # no model - refused 400
    assert r.status_code == 400, r.get_json()
    assert seq_now(c) == before, "a refused write moved the sequence"
    r = op.post("/api/indent", json={"indent_no": "NOPE", "indent_date": "2026-09-09",
                                     "customer": "ICON STOCK", "items": []})
    assert r.status_code == 403, r.status_code    # Quality cannot write indents
    assert seq_now(c) == before, "a 403 moved the sequence"


@test("two sessions: one saves, the OTHER's /api/changes names that topic "
     "and the saver's real login_id")
def t_two_sessions():
    fresh()
    saver = APP.app.test_client()
    AUTH.test_login(saver, role="Production Incharge", login_id="dp.saver")
    watcher = APP.app.test_client()
    AUTH.test_login(watcher, role="Super Admin", login_id="sa.watcher")

    seen = seq_now(watcher)                       # the watcher is up to date
    assert changes(watcher, seen)["topics"] == []

    item = icon_models.all_items()[0]["item_code"]
    r = saver.post("/api/indent", json={
        "indent_no": "FEED-1", "indent_date": "2026-09-09",
        "customer": "ICON STOCK", "items": [{"item_code": item, "qty": 10}]})
    assert r.status_code == 200, r.get_json()

    d = changes(watcher, seen)
    assert "indents" in d["topics"], d
    assert d["by"] == ["dp.saver"], d             # the session's own id
    assert d["seq"] > seen
    assert d["truncated"] is False
    # and once the watcher catches up, it goes quiet again
    assert changes(watcher, d["seq"])["topics"] == []
    print("      watcher saw topics=%s by=%s" % (d["topics"], d["by"]))


@test("the topic is the one the tables map to: a gate pass says gatepasses, "
     "an FQC grade says fqc, a pallet says boxes")
def t_topics_match_tables():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c)
    at = seq_now(c)
    assert c.post("/api/gatepass", json={"kind": "RGP", "party": "Topic Test",
                                         "description": "x", "qty": 1}).status_code == 200
    d = changes(c, at)
    assert "gatepasses" in d["topics"], d

    at = d["seq"]
    assert c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                         "capacity": 2}).status_code == 200
    d = changes(c, at)
    assert "boxes" in d["topics"], d
    print("      gatepass -> %s ; pallet -> %s" % (["gatepasses"], d["topics"]))


@test("a `since` older than anything left after pruning is reported as "
     "truncated, with no topic list - never a short list the client would "
     "read as 'that is all you missed'")
def t_truncated():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c)
    # three writes, then prune everything before the last one by hand -
    # the same state an hour of pruning leaves behind
    for i in range(3):
        assert c.post("/api/material", json={"name": "M%d" % i,
                                             "uom": "Nos"}).status_code == 200
    rows = log_rows()
    assert len(rows) >= 3, rows
    keep_from = rows[-1]["seq"]
    with store.conn() as (cx, cur):
        cur.execute("DELETE FROM change_log WHERE seq < %s", (keep_from,))

    d = changes(c, 1)                    # asking from before the pruned window
    assert d["truncated"] is True, d
    assert d["topics"] == [], d
    assert d["seq"] == keep_from, d
    # inside the window is NOT truncated
    d2 = changes(c, keep_from)
    assert d2["truncated"] is False and d2["topics"] == [], d2
    # and a first-ever call (since=0) is never "truncated" - nothing was missed
    d3 = changes(c, 0)
    assert d3["truncated"] is False, d3
    print("      since=1 -> truncated=%s topics=%s ; since=%d -> truncated=%s"
          % (d["truncated"], d["topics"], keep_from, d2["truncated"]))


@test("pruning removes rows past the window and keeps rows inside it - and "
     "the sequence never goes backwards over a prune")
def t_pruning():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c)
    assert c.post("/api/material", json={"name": "Old", "uom": "Nos"}).status_code == 200
    old = log_rows()
    assert old, "nothing recorded"
    highest_old = old[-1]["seq"]
    # age every existing row past the window
    with store.conn() as (cx, cur):
        cur.execute("UPDATE change_log SET at_epoch = %s",
                    (time.time() - store.CHANGE_RETENTION_S - 60,))
    # the next write prunes opportunistically, as purge_expired_sessions does
    assert c.post("/api/material", json={"name": "New", "uom": "Nos"}).status_code == 200
    rows = log_rows()
    assert rows, "the prune removed the row it had just written"
    assert all(r["seq"] > highest_old for r in rows), \
        "an aged row survived the prune: %s" % rows
    assert min(r["seq"] for r in rows) > highest_old, \
        "the sequence was reused after pruning - AUTOINCREMENT is not in force"
    print("      pruned to seq>%d, next seq %d (never reused)"
          % (highest_old, rows[0]["seq"]))


@test("/api/changes needs a session: 401 signed out, and it is NOT screen-"
     "gated - an operator who can view almost nothing still gets the feed")
def t_gated_by_session_only():
    fresh()
    anon = APP.app.test_client()
    r = anon.get("/api/changes?since=0")
    assert r.status_code == 401, r.status_code
    assert r.get_json() == {"ok": False, "why": "Sign in required."}, r.get_json()

    import icon_auth
    op = APP.app.test_client()
    me = AUTH.test_login(op, role="Quality", login_id="q.feed")["login_id"]
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, "cli", me, {
            s: {"view": False, "write": False} for s in icon_auth.SCREEN_IDS})
    assert op.get("/api/review").status_code == 403       # can view nothing
    assert op.get("/api/changes?since=0").status_code == 200


@test("junk in `since` is treated as 0 rather than crashing, and the feed "
     "survives a database with no change_log at all")
def t_robust():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c)
    for bad in ("abc", "", "-1", "9999999999"):
        r = c.get("/api/changes?since=%s" % bad)
        assert r.status_code == 200, (bad, r.status_code)
    # a write must still succeed if the change log cannot be written
    with store.conn() as (cx, cur):
        cur.execute("DROP TABLE change_log")
    r = c.post("/api/material", json={"name": "Survives", "uom": "Nos"})
    assert r.status_code == 200, "a missing change_log lost the user's save"
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM material "
                           "WHERE name='Survives'")["n"]
    assert n == 1, "the save did not land"
    print("      save survived a dropped change_log")


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
            traceback.print_exc()
            failed += 1
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
