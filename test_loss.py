"""
ICON TRACE - tests for Loss of Production (downtime events).

    python test_loss.py

THE RULE THIS FILE DEFENDS

    An event is opened, then closed - its duration is always derived from
    the two real timestamps the server itself records, never typed as a
    total. An induced stop must name a real, currently-open primary event
    (a real foreign key, checked against the database) or it is refused -
    an induced stop with nowhere to be excluded from silently double-counts
    the same stoppage the primary event already accounts for.

Each test names the rule it defends, so a failure says which decision broke.
"""

import os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_loss_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def setup():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


def open_event(c, line="A", mach="Laminator-2", reason="LOP-MACH",
              kind="P", start="14:05", mode="Live", linked_event_id=None,
              date="2026-09-18", shift="B"):
    return c.post("/api/loss_event", json={
        "line": line, "mach": mach, "reason": reason, "kind": kind,
        "start": start, "mode": mode, "date": date, "shift": shift,
        "linked_event_id": linked_event_id})


def event_count():
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT COUNT(*) AS n FROM loss_event")["n"]


@test("opening a primary event writes a real row, open (end_time NULL), "
     "and returns a display id resolving back to it")
def t_open_primary():
    c = setup()
    r = open_event(c)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["ok"] and d["event_id"] and d["id"] == "DT-%d" % d["event_id"]
    assert event_count() == 1

    lst = c.get("/api/loss_events").get_json()["events"]
    assert len(lst) == 1
    assert lst[0]["end"] is None, "a freshly opened event was not left open"
    assert lst[0]["minutes"] is None


@test("closing an open event derives minutes from the two real "
     "timestamps - never accepts a typed duration")
def t_close_derives_minutes():
    c = setup()
    eid = open_event(c, start="09:20").get_json()["event_id"]
    r = c.post("/api/loss_event/%d/close" % eid, json={})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["ok"] and d["end"] and isinstance(d["minutes"], int)

    lst = c.get("/api/loss_events").get_json()["events"]
    row = [e for e in lst if e["event_id"] == eid][0]
    assert row["end"] == d["end"]
    assert row["minutes"] == d["minutes"]


@test("closing an already-closed event is refused, not silently re-timed")
def t_close_twice_refused():
    c = setup()
    eid = open_event(c).get_json()["event_id"]
    r1 = c.post("/api/loss_event/%d/close" % eid, json={})
    first_end = r1.get_json()["end"]
    r2 = c.post("/api/loss_event/%d/close" % eid, json={})
    assert r2.status_code == 400, r2.get_json()
    lst = c.get("/api/loss_events").get_json()["events"]
    row = [e for e in lst if e["event_id"] == eid][0]
    assert row["end"] == first_end, "a second close silently re-timed the event"


@test("closing a nonexistent event is refused, not a 500")
def t_close_nonexistent():
    c = setup()
    r = c.post("/api/loss_event/999999/close", json={})
    assert r.status_code == 404, r.get_json()


@test("an induced stop with no linked primary is refused, naming why - "
     "matching v4's own original wording exactly")
def t_induced_without_link_refused():
    c = setup()
    r = open_event(c, kind="I", linked_event_id=None)
    assert r.status_code == 400, r.get_json()
    assert "double-count" in r.get_json()["why"], r.get_json()
    assert event_count() == 0


@test("an induced stop linked to an event that is not open (or not "
     "primary) is refused - the link must be real and currently live")
def t_induced_link_must_be_open_primary():
    c = setup()
    # link to a nonexistent event
    r = open_event(c, kind="I", linked_event_id=999999)
    assert r.status_code == 400, r.get_json()
    assert event_count() == 0

    # link to a real event that is already closed
    primary = open_event(c, kind="P").get_json()["event_id"]
    c.post("/api/loss_event/%d/close" % primary, json={})
    r2 = open_event(c, kind="I", linked_event_id=primary)
    assert r2.status_code == 400, r2.get_json()
    assert event_count() == 1, "the induced event was written despite the closed primary"


@test("an induced stop linked to a genuinely open primary event succeeds, "
     "and the listing resolves the link back to that primary's own "
     "display id")
def t_induced_link_succeeds():
    c = setup()
    primary = open_event(c, mach="Laminator-2", kind="P").get_json()
    r = open_event(c, mach="Framing machine-1", kind="I",
                   linked_event_id=primary["event_id"])
    assert r.status_code == 200, r.get_json()

    lst = c.get("/api/loss_events").get_json()["events"]
    induced = [e for e in lst if e["kind"] == "I"][0]
    assert induced["link"] == primary["id"], (induced, primary)
    assert induced["linked_event_id"] == primary["event_id"]


@test("the landing list filters by date, shift and a text search across "
     "line/machine/reason, server-side")
def t_list_filters():
    c = setup()
    open_event(c, line="A", mach="Laminator-2", reason="LOP-MACH",
              date="2026-09-18", shift="A")
    open_event(c, line="B", mach="Stringer-5", reason="LOP-POWER",
              date="2026-09-17", shift="B")

    by_date = c.get("/api/loss_events?date=2026-09-18").get_json()["events"]
    assert len(by_date) == 1 and by_date[0]["mach"] == "Laminator-2"

    by_shift = c.get("/api/loss_events?shift=B").get_json()["events"]
    assert len(by_shift) == 1 and by_shift[0]["mach"] == "Stringer-5"

    by_q = c.get("/api/loss_events?q=Stringer").get_json()["events"]
    assert len(by_q) == 1 and by_q[0]["mach"] == "Stringer-5"

    by_q_reason = c.get("/api/loss_events?q=POWER").get_json()["events"]
    assert len(by_q_reason) == 1 and by_q_reason[0]["reason"] == "LOP-POWER"


@test("date_from/date_to filter a real range, independent of the exact-match date param")
def t_list_date_range():
    c = setup()
    open_event(c, line="A", mach="Laminator-2", reason="LOP-MACH", date="2026-09-15")
    open_event(c, line="A", mach="Stringer-5", reason="LOP-POWER", date="2026-09-17")
    open_event(c, line="B", mach="Glass loader-1", reason="LOP-MAT", date="2026-09-20")

    in_range = c.get("/api/loss_events?date_from=2026-09-16&date_to=2026-09-18").get_json()["events"]
    assert len(in_range) == 1 and in_range[0]["mach"] == "Stringer-5", in_range

    from_only = c.get("/api/loss_events?date_from=2026-09-17").get_json()["events"]
    assert len(from_only) == 2, from_only
    assert set(r["mach"] for r in from_only) == {"Stringer-5", "Glass loader-1"}

    to_only = c.get("/api/loss_events?date_to=2026-09-17").get_json()["events"]
    assert len(to_only) == 2, to_only
    assert set(r["mach"] for r in to_only) == {"Laminator-2", "Stringer-5"}


@test("missing required fields (line, machine, reason, start) are "
     "refused before anything is written")
def t_missing_fields_refused():
    c = setup()
    r = c.post("/api/loss_event", json={"reason": "LOP-MACH", "start": "09:00"})
    assert r.status_code == 400, r.get_json()
    assert event_count() == 0


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
