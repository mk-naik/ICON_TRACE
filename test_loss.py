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

import datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_loss_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import icon_clock as clock                                   # noqa: E402
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


def minutes_ago(n):
    """HH:MM on the IST clock n minutes ago - a Live event starts about now
    (one whose start is more than 12 hours back is refused)."""
    return (clock.now() - datetime.timedelta(minutes=n)).strftime("%H:%M")


def open_event(c, line="A", mach="Laminator-2", reason="LOP-MACH",
              kind="P", start=None, mode="Live", linked_event_id=None,
              date="2026-09-18", shift="B", end=None):
    start = start or minutes_ago(5)
    return c.post("/api/loss_event", json={
        "line": line, "mach": mach, "reason": reason, "kind": kind,
        "start": start, "mode": mode, "date": date, "shift": shift,
        "linked_event_id": linked_event_id, "end": end})


def opened_at(r, at):
    """As if the event had been opened at `at` (IST). The server stamps an
    event's date and shift from the clock when it is opened, whatever the
    form sends, and the list counts it on the factory day of that moment -
    so a test of the filters sets the moment itself."""
    eid = r.get_json()["event_id"]
    h = int(at[11:13])
    letter = "A" if 6 <= h < 14 else "B" if 14 <= h < 22 else "C"
    # the factory day: 01:30 on the 18th is C shift of the 17th
    day = (datetime.datetime.fromisoformat(at) - datetime.timedelta(hours=6)).date().isoformat()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE loss_event SET created_at=%s, event_date=%s, shift=%s "
                    "WHERE event_id=%s", (at, day, letter, eid))
    return r


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
    eid = open_event(c, start=minutes_ago(20)).get_json()["event_id"]
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
    opened_at(open_event(c, line="A", mach="Laminator-2", reason="LOP-MACH"),
              "2026-09-18T09:00:00")                          # A shift
    opened_at(open_event(c, line="B", mach="Stringer-5", reason="LOP-POWER"),
              "2026-09-17T15:00:00")                          # B shift

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
    opened_at(open_event(c, line="A", mach="Laminator-2", reason="LOP-MACH"),
              "2026-09-15T10:00:00")
    # 01:30 on the 18th is C shift of the 17th - it counts on the 17th
    opened_at(open_event(c, line="A", mach="Stringer-5", reason="LOP-POWER"),
              "2026-09-18T01:30:00")
    opened_at(open_event(c, line="B", mach="Glass loader-1", reason="LOP-MAT"),
              "2026-09-20T10:00:00")

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


import contextlib


@contextlib.contextmanager
def at_clock(iso):
    """The IST clock reads `iso` for the length of the block."""
    real = clock.now
    clock.now = lambda: datetime.datetime.fromisoformat(iso)
    try:
        yield
    finally:
        clock.now = real


@test("a Live stop opened at 01:30 belongs to C shift of the DAY BEFORE - "
      "the factory day, not the calendar date (it used to be filed next day)")
def t_live_is_on_the_factory_day():
    c = setup()
    with at_clock("2026-09-18T01:30:00"):
        r = open_event(c, start="01:20")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert (d["event_date"], d["shift"], d["mode"]) == ("2026-09-17", "C", "Live"), d
    on17 = c.get("/api/loss_events?date=2026-09-17&shift=C").get_json()["events"]
    assert [e["event_id"] for e in on17] == [d["event_id"]], on17
    assert on17[0]["recorded_shift"] == "C" and on17[0]["created_at"].startswith("2026-09-18")


@test("a Live start more than 12 hours back is refused - that stop is over; "
      "record it as Retro with its date and shift")
def t_live_start_long_ago_refused():
    c = setup()
    with at_clock("2026-09-18T09:00:00"):
        r = open_event(c, start="14:05")        # v4's own default, 19 h back
    assert r.status_code == 400, r.get_json()
    assert "Retro" in r.get_json()["why"], r.get_json()
    assert event_count() == 0


@test("a Retro event is recorded FOR the production date and shift it names, "
      "closed at once, minutes from its two times; it is listed on that day "
      "and shift, with the time it was typed beside it (Mukesh, 6 Oct)")
def t_retro_for_its_own_shift():
    c = setup()
    with at_clock("2026-09-18T09:00:00"):
        r = open_event(c, mode="Retro", date="2026-09-17", shift="B",
                       start="15:00", end="15:35")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert (d["event_date"], d["shift"], d["end"], d["minutes"]) == \
        ("2026-09-17", "B", "15:35", 35), d
    rows = c.get("/api/loss_events?date=2026-09-17&shift=B").get_json()["events"]
    assert len(rows) == 1 and rows[0]["mode"] == "Retro" and rows[0]["minutes"] == 35
    assert rows[0]["created_at"].startswith("2026-09-18T09:00"), rows[0]
    assert rows[0]["recorded_shift"] == "A"
    assert c.get("/api/loss_events?date=2026-09-18").get_json()["events"] == []
    # closing it again is refused - it is already closed
    assert c.post("/api/loss_event/%d/close" % d["event_id"], json={}).status_code == 400


@test("a Retro C shift stop across midnight: 23:40 to 00:20 is 40 minutes of "
      "C shift on the day it started")
def t_retro_c_shift_crosses_midnight():
    c = setup()
    with at_clock("2026-09-18T09:00:00"):
        r = open_event(c, mode="Retro", date="2026-09-17", shift="C",
                       start="23:40", end="00:20")
    assert r.status_code == 200, r.get_json()
    assert (r.get_json()["event_date"], r.get_json()["minutes"]) == ("2026-09-17", 40)


@test("a Retro event that cannot be true is refused, naming why, and nothing "
      "is written: outside its shift, ending before it starts, running past "
      "the shift's end, not over yet, or missing its end")
def t_retro_refusals():
    c = setup()
    cases = (
        (dict(date="2026-09-17", shift="B", start="09:00", end="09:30"), "outside B shift"),
        (dict(date="2026-09-17", shift="B", start="15:30", end="15:00"), "not after"),
        (dict(date="2026-09-17", shift="B", start="21:30", end="22:30"), "record the rest under the next shift"),
        (dict(date="2026-09-18", shift="A", start="08:00", end="09:30"), "has not come yet"),
        (dict(date="2026-09-18", shift="B", start="14:30", end="15:00"), "has not started"),
        (dict(date="2026-09-17", shift="B", start="15:00", end=""), "stopped and the time it restarted"),
        (dict(date="", shift="B", start="15:00", end="15:30"), "Pick the date"),
    )
    with at_clock("2026-09-18T09:00:00"):
        for kw, expect in cases:
            r = open_event(c, mode="Retro", **kw)
            assert r.status_code == 400, (kw, r.get_json())
            assert expect in r.get_json()["why"], (kw, r.get_json())
    assert event_count() == 0


@test("a Retro induced stop names a primary of the SAME date and shift - open "
      "or closed - and is refused against any other")
def t_retro_induced_link():
    c = setup()
    with at_clock("2026-09-18T09:00:00"):
        p = open_event(c, mode="Retro", date="2026-09-17", shift="B",
                       start="15:00", end="15:40").get_json()
        other = open_event(c, mode="Retro", date="2026-09-17", shift="A",
                           start="07:00", end="07:10").get_json()
        ok = open_event(c, mode="Retro", kind="I", linked_event_id=p["event_id"],
                        mach="Framing machine-1", date="2026-09-17", shift="B",
                        start="15:05", end="15:30")
        bad = open_event(c, mode="Retro", kind="I", linked_event_id=other["event_id"],
                         mach="Framing machine-1", date="2026-09-17", shift="B",
                         start="15:05", end="15:30")
    assert ok.status_code == 200, ok.get_json()
    assert bad.status_code == 400 and "B shift" in bad.get_json()["why"], bad.get_json()


@test("the Production Dashboard counts a loss on its own production date and "
      "shift, and the list's Shift dropdown offers what the other filters leave")
def t_dashboard_and_facets():
    c = setup()
    with at_clock("2026-09-18T09:00:00"):
        open_event(c, mode="Retro", date="2026-09-17", shift="B",
                   start="15:00", end="15:35", mach="Laminator-2")
    d = c.get("/api/prod/dashboard?from=2026-09-17&to=2026-09-17").get_json()
    assert [(x["date"], x["shift"], x["minutes"]) for x in d["loss"]] == \
        [("2026-09-17", 2, 35)], d["loss"]
    assert c.get("/api/prod/dashboard?from=2026-09-18&to=2026-09-18").get_json()["loss"] == []
    f = c.get("/api/loss_events?date=2026-09-17&shift=A").get_json()
    assert f["events"] == [] and f["facets"]["shift"] == ["B"], f


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
