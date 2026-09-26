"""
ICON TRACE - tests for Production Entry.

    python test_production.py

THE RULE THIS FILE DEFENDS

    A production entry can claim any range of serials that were genuinely
    planned and not skipped - not, any more, only ones still literally in
    state 'planned'. FQC can legitimately reach a module before its shift's
    paperwork is filed (a module cannot be graded at all unless it was
    made), so a serial FQC already graded/rejected is proof of production,
    not a conflict with recording it. The one real conflict is a serial
    already recorded under an EARLIER production entry, tracked by its own
    `prod_entry_id` column - independent of `state`, which FQC and packing
    keep moving long after production entry's own job here is done. The
    range is validated by its real, parsed sequence numbers (never by
    comparing the serial strings themselves); every serial still 'planned'
    in it moves to 'produced' together, while one FQC already graded stays
    exactly where FQC left it.

Each test names the rule it defends, so a failure says which decision broke.
"""

import datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_production_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH

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
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


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


@test("a range overlapping a serial already recorded under an earlier "
     "production entry is refused entirely - partial recording is not an "
     "option")
def t_already_produced_in_range_refused():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 5)
    # a real prior entry, the only thing that actually marks a serial
    # recorded - not a hand-set state, which FQC can also set on its own
    r0 = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[2], "end_serial": serials[2]})
    assert r0.get_json()["ok"], r0.get_json()
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[0], "end_serial": serials[4]})
    assert r.status_code == 400, r.get_json()
    assert "already recorded" in r.get_json()["why"].lower(), r.get_json()
    assert entry_count() == 1
    with store.conn() as (cx, cur):
        # the one serial that WAS already recorded stays that way - refusing
        # the request must not also silently "fix" what it found
        row = store.one(cur, "SELECT state FROM serial WHERE serial=%s", (serials[2],))
        assert row["state"] == "produced"
        # and the ones either side of it are untouched, still planned
        row0 = store.one(cur, "SELECT state FROM serial WHERE serial=%s", (serials[0],))
        assert row0["state"] == "planned"


@test("a serial FQC already graded before the shift's paperwork was filed "
     "does not block the entry, and is not regressed back to 'produced'")
def t_fqc_ahead_of_paperwork_does_not_block_or_regress():
    """The practical sequence is Indent -> Planning -> Production Entry ->
    FQC, but a module physically reaches the FQC station whenever it reaches
    it - often before the shift-end paperwork is filed for the batch it was
    part of. A module cannot be graded at all unless it was made, so a
    serial FQC already touched is proof it was produced, not a conflict with
    recording that it was."""
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 5)
        # FQC reached one of these first - graded/rejected, never through
        # Production Entry, so prod_entry_id is still NULL
        cur.execute("UPDATE serial SET state='rejected' WHERE serial=%s",
                   (serials[2],))
    r = c.post("/api/prodentry", json={
        "date": "2026-09-17", "shift": "A", "incharge": "TEST INCHARGE",
        "start_serial": serials[0], "end_serial": serials[4]})
    assert r.get_json()["ok"], r.get_json()
    assert r.get_json()["qty"] == 5, r.get_json()
    assert entry_count() == 1
    with store.conn() as (cx, cur):
        # FQC's own decision is not overwritten by the paperwork catching up
        rejected = store.one(cur, "SELECT state, prod_entry_id FROM serial "
                                  "WHERE serial=%s", (serials[2],))
        assert rejected["state"] == "rejected", rejected
        # but it IS now recorded, same as its four siblings - a second entry
        # covering it must still be refused as a duplicate
        assert rejected["prod_entry_id"], rejected
        for s in (serials[0], serials[1], serials[3], serials[4]):
            row = store.one(cur, "SELECT state, prod_entry_id FROM serial "
                                 "WHERE serial=%s", (s,))
            assert row["state"] == "produced", (s, row)
            assert row["prod_entry_id"], (s, row)


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


# --------------------------------------------------------------------------
# When it was PRODUCED vs when it was TYPED (reported by Mukesh, 26-09-2026)
#
# A shift report is written after the shift ends - which is the next shift,
# and for C shift the next calendar day. The server used to ignore the form's
# date and shift and stamp clock.now() into prod_date/shift, so a C shift of
# the 25th filed at 06:15 on the 26th was recorded as A shift of the 26th,
# and the only way to file it under its own name was to make the form lie.
# --------------------------------------------------------------------------

def _entry(eid=None):
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT * FROM production_entry "
                              "ORDER BY entry_id DESC LIMIT 1")


@test("the shift the operator states is what is recorded - C shift of the "
      "25th, filed the next morning, is stored as C shift of the 25th and "
      "not as the shift the form happened to be typed in")
def t_records_the_shift_that_ran():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 4)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    r = c.post("/api/prodentry", json={
        "date": yesterday, "shift": "C", "incharge": "NIGHT INCHARGE",
        "start_serial": serials[0], "end_serial": serials[3]})
    assert r.status_code == 200, r.get_json()
    row = _entry()
    assert row["prod_date"] == yesterday, row
    assert row["shift"] == "C", row
    # and when it was typed is still recorded, separately - a late entry
    # stays visible as a late entry
    assert row["created_at"][:10] == datetime.date.today().isoformat(), row
    print("      prod_date=%s shift=%s, typed %s" % (row["prod_date"],
                                                     row["shift"], row["created_at"]))


@test("the list finds that entry on the day it RAN, not on the day it was "
      "typed - the filter that used to read created_at")
def t_listed_on_the_day_it_ran():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 4)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    today = datetime.date.today().isoformat()
    assert c.post("/api/prodentry", json={
        "date": yesterday, "shift": "C", "incharge": "NIGHT INCHARGE",
        "start_serial": serials[0], "end_serial": serials[3]}).status_code == 200

    on_run_day = c.get("/api/prodentries?from=%s&to=%s" % (yesterday, yesterday))
    assert len(on_run_day.get_json()["entries"]) == 1, on_run_day.get_json()
    on_typed_day = c.get("/api/prodentries?from=%s&to=%s" % (today, today))
    assert on_typed_day.get_json()["entries"] == [], on_typed_day.get_json()
    by_shift = c.get("/api/prodentries?shift=C")
    assert len(by_shift.get_json()["entries"]) == 1, by_shift.get_json()


@test("a shift that has not started yet is refused - you cannot report a "
      "shift that has not run - while a shift still running may be filed")
def t_future_shift_refused():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 6)
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    r = c.post("/api/prodentry", json={
        "date": tomorrow, "shift": "A", "incharge": "X",
        "start_serial": serials[0], "end_serial": serials[1]})
    assert r.status_code == 400, r.get_json()
    assert "has not started yet" in r.get_json()["why"], r.get_json()

    # the shift running right now IS acceptable
    now = clock.now()
    running = clock.SHIFT_LETTER[clock.shift_of(now.hour)]
    r = c.post("/api/prodentry", json={
        "date": clock.shift_day(now).isoformat(), "shift": running,
        "incharge": "X", "start_serial": serials[0], "end_serial": serials[1]})
    assert r.status_code == 200, r.get_json()


@test("a date far enough back to be a wrong-year typo is refused, naming "
      "how far back it is - ordinary catching-up is not")
def t_backdate_limit():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 6)
    old = (datetime.date.today() -
           datetime.timedelta(days=APP.PROD_BACKDATE_DAYS + 5)).isoformat()
    r = c.post("/api/prodentry", json={
        "date": old, "shift": "A", "incharge": "X",
        "start_serial": serials[0], "end_serial": serials[1]})
    assert r.status_code == 400, r.get_json()
    assert "days back" in r.get_json()["why"], r.get_json()

    ok_day = (datetime.date.today() -
              datetime.timedelta(days=APP.PROD_BACKDATE_DAYS - 1)).isoformat()
    r = c.post("/api/prodentry", json={
        "date": ok_day, "shift": "B", "incharge": "X",
        "start_serial": serials[0], "end_serial": serials[1]})
    assert r.status_code == 200, r.get_json()
    print("      %s refused, %s accepted" % (old, ok_day))


@test("a missing or unreadable date or shift is refused by name, rather "
      "than being quietly replaced with the current one")
def t_bad_date_or_shift_refused():
    c = setup()
    with store.conn() as (cx, cur):
        serials = plan_serials(cur, 4)
    base = {"incharge": "X", "start_serial": serials[0], "end_serial": serials[1]}
    for body, expect in (
            (dict(base, shift="A"), "Pick the date"),
            (dict(base, date="", shift="A"), "Pick the date"),
            (dict(base, date="not-a-date", shift="A"), "is not a date"),
            (dict(base, date=datetime.date.today().isoformat()), "Pick the shift"),
            (dict(base, date=datetime.date.today().isoformat(), shift="Z"), "Pick the shift")):
        r = c.post("/api/prodentry", json=body)
        assert r.status_code == 400, (body, r.status_code)
        assert expect in r.get_json()["why"], (body, r.get_json())
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM production_entry")["n"] == 0


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
