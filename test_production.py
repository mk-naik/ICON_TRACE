"""
ICON TRACE - tests for Production Entry.

    python test_production.py

THE RULE THIS FILE DEFENDS

    A production entry can only claim a range of serials that are all
    genuinely 'planned' - not yet produced, not skipped, not already
    recorded under an earlier entry. The range is validated by its real,
    parsed sequence numbers (never by comparing the serial strings
    themselves), and every serial the range covers moves to 'produced'
    together, or none of them do.

Each test names the rule it defends, so a failure says which decision broke.
"""

import os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_production_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


MODEL = "ISEN590-G12R"
WATT = 590


def setup():
    store.wipe()
    return APP.app.test_client()


def plan_serials(cur, qty, model=MODEL, watt=WATT, start_seq=1):
    """Real serial rows in 'planned' state, sequence-numbered - the same
    real column production entry validates the range against, never the
    serial string."""
    serials = []
    for i in range(qty):
        seq = start_seq + i
        s = "ICON%dR12907100%02d" % (watt, seq)
        store.insert(cur, "serial", {
            "serial": s, "build_instance": 1, "model": model,
            "wattage": watt, "customer": None, "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-17",
            "shift": 1, "sequence": seq, "state": "planned"})
        serials.append(s)
    return serials


def entry_count():
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT COUNT(*) AS n FROM production_entry")["n"]


@test("a valid range of planned serials records one entry and moves "
     "every serial in it to 'produced', by its real sequence number")
def t_valid_range_produces():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 10)
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[0], "end_serial": serials[4]})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["ok"] is True
    assert d["qty"] == 5, d

    with store.conn() as (cx, cur):
        for s in serials[:5]:
            row = store.one(cur, "SELECT state FROM serial WHERE serial=%s", (s,))
            assert row["state"] == "produced", (s, row)
        for s in serials[5:]:
            row = store.one(cur, "SELECT state FROM serial WHERE serial=%s", (s,))
            assert row["state"] == "planned", \
                "a serial outside the range was moved too: " + s
    assert entry_count() == 1


@test("an end serial that was never planned is refused, naming it, and "
     "nothing is written")
def t_end_serial_not_found():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 5)
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[0], "end_serial": "ICON590R1290710099"})
    assert r.status_code == 400, r.get_json()
    assert not r.get_json()["ok"]
    assert "not found" in r.get_json()["why"].lower(), r.get_json()
    assert entry_count() == 0


@test("a range containing an already-produced serial is refused entirely "
     "- partial recording is not an option")
def t_already_produced_in_range_refused():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 5)
        cur.execute("UPDATE serial SET state='produced' WHERE serial=%s", (serials[2],))
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[0], "end_serial": serials[4]})
    assert r.status_code == 400, r.get_json()
    assert "already produced" in r.get_json()["why"].lower(), r.get_json()
    assert entry_count() == 0
    with store.conn() as (cx, cur):
        # the one serial that WAS already produced stays that way - refusing
        # the request must not also silently "fix" what it found
        row = store.one(cur, "SELECT state FROM serial WHERE serial=%s", (serials[2],))
        assert row["state"] == "produced"
        # and the ones either side of it are untouched, still planned
        row0 = store.one(cur, "SELECT state FROM serial WHERE serial=%s", (serials[0],))
        assert row0["state"] == "planned"


@test("start greater than end is refused before anything is queried "
     "against real state")
def t_start_after_end_refused():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 5)
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[4], "end_serial": serials[0]})
    assert r.status_code == 400, r.get_json()
    assert entry_count() == 0


@test("mismatched model/wattage between start and end serial is refused - "
     "a range can only span one model's own sequence")
def t_mixed_model_refused():
    c = setup()
    with store.conn() as (cx, cur):
        a = plan_serials(cur, 2, model=MODEL, watt=WATT, start_seq=1)
        b = plan_serials(cur, 2, model="ISEN625-G12R", watt=625, start_seq=1)
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": a[0], "end_serial": b[0]})
    assert r.status_code == 400, r.get_json()
    assert entry_count() == 0


@test("GET /api/prodentries lists a recorded entry back, with the "
     "customer resolved from the entry's own first serial - the real "
     "link, not a guessed text-range match against allocation")
def t_list_resolves_customer_from_first_serial():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 3)
        cur.execute("UPDATE serial SET customer=%s WHERE serial=%s",
                   ("C0001", serials[0]))
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[0], "end_serial": serials[2]})
    assert r.status_code == 200, r.get_json()

    r2 = c.get("/api/prodentries")
    assert r2.status_code == 200, r2.get_json()
    entries = r2.get_json()["entries"]
    assert len(entries) == 1, entries
    assert entries[0]["customer"] == "C0001", entries[0]
    assert entries[0]["qty"] == 3


if __name__ == "__main__":
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
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
    finally:
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
