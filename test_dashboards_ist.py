"""
ICON TRACE - tests for when things count.

    python test_dashboards_ist.py

THE RULES THIS FILE DEFENDS

    One clock. Everything is stored as the calendar date and IST time it
    happened, whatever the server is set to - including the columns SQLite
    used to fill with UTC.

    Everything counts by when it happened in the system - a scan, an entry,
    a record being created - on the factory day, 06:00 to 06:00: C shift
    runs past midnight, so 26-09-2026 01:12:56 is C shift of the 25th. What
    is stored stays the calendar time; only the counting shifts.

    The date and shift printed in a serial number count for nothing. A
    range printed for the 24th and produced on the 25th is the 25th's
    production. A production entry's, an allocation's and a downtime
    event's date and shift are when they were recorded, not what a form or
    a barcode says.

    A running number is unique only inside one printed batch. Production
    Entry works inside the start serial's batch and nowhere else: 0778-1000
    of one run is 223 modules, not 446 because another run also has them.

Each test names the rule it defends, so a failure says which decision broke.
"""

import datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_dash_ist_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
import icon_models as models                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


MODEL, WATT = "ISEN625-G12R", 625


def setup():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


def printed(day, shift, first, last):
    """Serials as Planning's generator prints them - ICON625R 12 9 24
    <shift> <seq:4> for a run printed for 24 Sep 2026."""
    y, m, d = day.split("-")
    body = "%02d%s%s%d" % (int(y) - 2014, "123456789ABC"[int(m) - 1], d, shift)
    return ["ICON%dR%s%04d" % (WATT, body, n) for n in range(first, last + 1)]


def allocate(cur, serials, at, state="planned", grade=None, customer="ICON STOCK"):
    """An allocation Planning issued at `at`, holding these serials. The
    serials keep the date and shift printed in them - which nothing may
    count by."""
    ind = store.one(cur, "SELECT indent_id FROM indent LIMIT 1")
    if not ind:
        iid = store.insert(cur, "indent", {"indent_no": "T/1", "indent_date": "2026-09-01",
                                           "customer": "STOCK", "created_by": "t"})
        lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
            "item_description": "SOLAR PV MODULE-%s-NDCR" % MODEL, "model": MODEL,
            "wattage": WATT, "qty": 100000, "dcr": "NDCR"})
    else:
        lid = store.one(cur, "SELECT indent_line_id FROM indent_line LIMIT 1")["indent_line_id"]
    aid = store.insert(cur, "allocation", {
        "indent_line_id": lid, "model": MODEL, "wattage": WATT, "customer": customer,
        "date_produced": at[:10], "shift": clock.shift_of(int(at[11:13])),
        "qty": len(serials), "seq_from": 0, "seq_to": 0, "created_at": at,
        "created_by": "t"})
    for s in serials:
        store.insert(cur, "serial", {
            "serial": s, "build_instance": 1, "alloc_id": aid, "indent_line_id": lid,
            "model": MODEL, "wattage": WATT, "customer": customer, "dcr": "NDCR",
            "format_version": 2, "date_produced": "20%s-%s-%s" % (
                int(s[8:10]) + 14, "%02d" % ("123456789ABC".index(s[10]) + 1), s[11:13]),
            "shift": int(s[13]), "sequence": int(s[-4:]), "state": state, "grade": grade})
    return aid


def inspect(cur, serial, at, outcome="pass", defect=None, by="Suryansh Verma"):
    store.insert(cur, "fqc_record", {
        "serial": serial, "outcome": outcome, "grade": "A" if outcome == "pass" else None,
        "mode": "confirmed", "decided_by": by, "at": at, "defect": defect})
    db.set_serial(cur, serial, state="graded" if outcome == "pass" else "rejected",
                  grade="A" if outcome == "pass" else None)


def state_of(s):
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT * FROM serial WHERE serial=%s", (s,))


def dash(c, day, shift=""):
    return c.get("/api/prod/dashboard?from=%s&to=%s%s" % (
        day, day, "&shift=" + shift if shift else "")).get_json()


# --------------------------------------------------------------------------
# one clock, one counting day
# --------------------------------------------------------------------------

@test("the clock is IST whatever the machine is set to; the counting day "
      "runs 06:00 to 06:00, so 01:12:56 on the 26th is C shift of the 25th")
def t_clock():
    utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    gap = (clock.now() - utc).total_seconds()
    assert abs(gap - 19800) < 5, "IST is UTC+05:30, got a %ss gap" % gap
    assert [clock.shift_of(h) for h in (5, 6, 13, 14, 21, 22, 23, 0)] == \
        [3, 1, 1, 2, 2, 3, 3, 3]
    night = datetime.datetime(2026, 9, 26, 1, 12, 56)
    assert clock.shift_day(night) == datetime.date(2026, 9, 25)
    assert clock.shift_of(night.hour) == 3
    assert clock.shift_day(datetime.datetime(2026, 9, 26, 6, 0, 0)) == \
        datetime.date(2026, 9, 26)
    assert [clock.shift_number(v) for v in ("A", "b", "Shift C", "2", 3, "D", None)] == \
        [1, 2, 3, 2, 3, None, None]


@test("a column SQLite used to default to UTC is written in IST, calendar "
      "date and time as it happened")
def t_default_timestamp_is_ist():
    setup()
    with store.conn() as (cx, cur):
        cur.execute("INSERT INTO dispatch_audit (actor, action, entity) "
                    "VALUES ('t', 't', 't')")
        at = store.one(cur, "SELECT at FROM dispatch_audit "
                            "ORDER BY rowid DESC LIMIT 1")["at"]
    assert "T" in at, "still the UTC default's form: %r" % at
    got = datetime.datetime.fromisoformat(at)
    assert abs((got - clock.now()).total_seconds()) < 120, (at, clock.stamp())


@test("rows stamped in UTC before the fix are moved to IST once, and a "
      "restart does not move them again")
def t_backfill_once():
    setup()
    with store.conn() as (cx, cur):
        cur.execute("DROP TRIGGER ist_dispatch_audit_at")
        cur.execute("INSERT INTO dispatch_audit (at, actor, action, entity) "
                    "VALUES ('2026-09-25 05:07:24', 't', 't', 't')")
        cur.execute("DELETE FROM app_config WHERE k='clock.ist_backfill'")
    store._ready = False
    store.ensure()
    store._ready = False
    store.ensure()
    with store.conn() as (cx, cur):
        at = store.one(cur, "SELECT at FROM dispatch_audit WHERE actor='t'")["at"]
    assert at == "2026-09-25T10:37:24", at


# --------------------------------------------------------------------------
# Production Entry
# --------------------------------------------------------------------------

@test("a range whose running numbers also exist in another printed batch "
      "records only its own - 223, not 446 - and leaves the other alone")
def t_range_is_one_batch():
    c = setup()
    b_run = printed("2026-09-24", 2, 778, 1000)
    c_run = printed("2026-09-24", 3, 1, 1137)
    with store.conn() as (cx, cur):
        allocate(cur, b_run, "2026-09-25T10:37:24")
        allocate(cur, c_run, "2026-09-25T10:39:42")
    r = c.post("/api/prodentry", json={
        "incharge": "RAJESH KUMAR", "line": "A-Line",
        "start_serial": b_run[0], "end_serial": b_run[-1]})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["qty"] == 223, r.get_json()
    assert state_of(b_run[0])["state"] == "produced"
    twin = c_run[777]
    assert twin.endswith("0778"), twin
    got = state_of(twin)
    assert got["state"] == "planned" and got["prod_entry_id"] is None, \
        "the other run's 0778 was recorded too: %r" % got


@test("a production entry is dated and shifted when it is recorded, "
      "whatever the form and the barcode say; the serial's own printed date "
      "and shift are left alone")
def t_entry_stamped_from_clock():
    c = setup()
    s = printed("2026-09-24", 2, 1, 5)
    with store.conn() as (cx, cur):
        allocate(cur, s, "2026-09-25T10:37:24")
    before = clock.now()
    r = c.post("/api/prodentry", json={
        "date": "2026-08-21", "shift": "B", "incharge": "X",
        "start_serial": s[0], "end_serial": s[-1]})
    assert r.get_json()["ok"], r.get_json()
    with store.conn() as (cx, cur):
        e = store.one(cur, "SELECT prod_date, shift, created_at FROM production_entry")
    assert e["prod_date"] == before.date().isoformat(), e
    assert e["shift"] == clock.SHIFT_LETTER[clock.shift_of(before.hour)], e
    assert e["created_at"][:10] == before.date().isoformat(), e
    row = state_of(s[0])
    assert (row["date_produced"], row["shift"]) == ("2026-09-24", 2), row


@test("a range across two printed batches is refused, naming both, and "
      "nothing is written")
def t_cross_batch_refused():
    c = setup()
    b = printed("2026-09-24", 2, 1, 5)
    cc = printed("2026-09-24", 3, 1, 5)
    with store.conn() as (cx, cur):
        allocate(cur, b + cc, "2026-09-25T10:37:24")
    r = c.post("/api/prodentry", json={"incharge": "X",
                                       "start_serial": b[0], "end_serial": cc[-1]})
    why = r.get_json()["why"]
    assert r.status_code == 400 and "same batch" in why, why
    assert b[0][:-4] in why and cc[0][:-4] in why, why
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM production_entry")["n"] == 0


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

@test("an allocation is dated and shifted when Planning issued it, not by "
      "the date and shift printed in its serials")
def t_allocation_stamped_from_clock():
    c = setup()
    item = next(i for i in models.all_items() if i.get("model") == MODEL)
    r = c.post("/api/indent", json={
        "indent_no": "IS2I/26/0099", "indent_date": "2026-09-25",
        "customer": "ICON STOCK",
        "items": [{"item_code": item["item_code"], "qty": 5}]})
    assert r.get_json().get("ok"), r.get_json()
    with store.conn() as (cx, cur):
        line = store.one(cur, "SELECT indent_line_id FROM indent_line")["indent_line_id"]
    before = clock.now()
    r = c.post("/api/allocation", json={
        "indent_line_id": line, "qty": 5, "serials": printed("2026-08-01", 3, 1, 5),
        "date_produced": "2026-08-01", "shift": "3"})
    assert r.get_json().get("ok"), r.get_json()
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT date_produced, shift FROM allocation")
    assert a["date_produced"] == before.date().isoformat(), a
    assert a["shift"] == clock.shift_of(before.hour), a


# --------------------------------------------------------------------------
# Production Dashboard counts what happened, when it happened
# --------------------------------------------------------------------------

@test("modules printed for the 24th, allocated and inspected on the 25th, "
      "count on the 25th - and nothing on the 24th")
def t_counts_by_when_it_happened():
    c = setup()
    run = printed("2026-09-24", 3, 1, 10)
    with store.conn() as (cx, cur):
        allocate(cur, run, "2026-09-25T10:37:24")
        for s in run[:3]:
            inspect(cur, s, "2026-09-25T11:58:29")
        for s in run[3:5]:
            inspect(cur, s, "2026-09-25T11:59:25", "reject", "low eff")
    k = dash(c, "2026-09-25")["kpi"]
    assert (k["alloc"], k["prod"], k["fqc"], k["passed"], k["rej"]) == (10, 5, 5, 3, 2), k
    assert k["awaiting_quality"] == 2 and k["running"] == 0 and k["remaining"] == 5, k
    assert dash(c, "2026-09-24")["kpi"]["alloc"] == 0, "counted by the printed date"
    a = dash(c, "2026-09-25", "A")["kpi"]
    assert (a["alloc"], a["fqc"]) == (10, 5), "10:37 and 11:58 are shift A: %r" % a


@test("01:12 on the 26th counts as C shift of the 25th, not the 26th")
def t_after_midnight_is_yesterdays_c():
    c = setup()
    run = printed("2026-09-25", 3, 1, 4)
    with store.conn() as (cx, cur):
        allocate(cur, run, "2026-09-25T22:30:00")
        for s in run:
            inspect(cur, s, "2026-09-26T01:12:56")
    k25 = dash(c, "2026-09-25", "C")["kpi"]
    assert (k25["alloc"], k25["fqc"]) == (4, 4), k25
    assert dash(c, "2026-09-26")["kpi"]["fqc"] == 0
    rows = c.get("/api/fqc/dashboard?from=2026-09-25").get_json()["rows"]
    assert [(r["day"], r["shift"]) for r in rows] == [("2026-09-25", 3)], rows
    assert c.get("/api/fqc/dashboard?from=2026-09-26").get_json()["totals"]["inspected"] == 0


@test("a production entry counts its range as produced when it was "
      "recorded, on that line and shift; an empty day names the last day "
      "anything happened")
def t_entry_counts_when_recorded():
    c = setup()
    run = printed("2026-09-20", 1, 1, 6)
    with store.conn() as (cx, cur):
        allocate(cur, run, "2026-09-24T09:00:00")
    r = c.post("/api/prodentry", json={"incharge": "X", "line": "B-Line",
                                       "start_serial": run[0], "end_serial": run[-1]})
    assert r.get_json()["ok"], r.get_json()
    today = clock.shift_day().isoformat()
    d = dash(c, today)
    assert d["kpi"]["prod"] == 6 and d["kpi"]["running"] == 6, d["kpi"]
    sh = clock.shift_of(clock.now().hour)
    assert d["lines"] == [{"line": "B-Line", "shift": sh, "produced": 6, "scrap": 0}], d["lines"]
    empty = dash(c, "2026-09-01")
    assert empty["kpi"]["prod"] == 0 and empty["latest"] == today, empty


# --------------------------------------------------------------------------
# FQC: the inspection's day and shift
# --------------------------------------------------------------------------

def fqc_setup():
    c = setup()
    run = printed("2026-09-24", 3, 637, 638)          # printed for C shift
    with store.conn() as (cx, cur):
        allocate(cur, run, "2026-09-25T09:00:00")
        inspect(cur, run[0], "2026-09-25T11:58:29", "reject", "low eff")
        inspect(cur, run[1], "2026-09-25T23:10:00", "reject", "low eff")
    return c, run


@test("a module inspected at 11:58 counts under shift A, the shift that "
      "time is in, whatever shift its serial was printed for")
def t_fqc_shift_is_inspection():
    c, run = fqc_setup()
    rows = c.get("/api/fqc/dashboard?from=2026-09-25").get_json()["rows"]
    assert sorted(r["shift"] for r in rows) == [1, 3], rows
    only_a = c.get("/api/fqc/dashboard?from=2026-09-25&shift=A").get_json()["totals"]
    assert only_a["inspected"] == 1, only_a
    mods = c.get("/api/fqc/dashboard/modules?from=2026-09-25&shift=1").get_json()
    assert [m["serial"] for m in mods] == [run[0]], mods
    m = mods[0]
    assert (m["shift"], m["day"], m["decided_by"]) == (1, "2026-09-25", "Suryansh Verma"), m
    assert "prod_date" not in m and "prod_shift" not in m, m


@test("Recent gradings' shift filter, sent as a letter, finds that shift")
def t_fqc_recent_shift_letter():
    c, run = fqc_setup()
    got = c.get("/api/fqc/recent?shift=A").get_json()["rows"]
    assert [r["serial"] for r in got] == [run[0]], got
    got = c.get("/api/fqc/recent?shift=C").get_json()["rows"]
    assert [r["serial"] for r in got] == [run[1]], got


# --------------------------------------------------------------------------
# Loss of Production
# --------------------------------------------------------------------------

@test("a downtime event is dated and shifted when it is opened, whatever "
      "the form sends, and one that runs past midnight has its real length")
def t_loss_stamped_and_crosses_midnight():
    c = setup()
    before = clock.now()
    r = c.post("/api/loss_event", json={"line": "A", "mach": "Laminator-1",
        "reason": "LOP-POWER", "start": "23:50", "date": "2026-08-21", "shift": "B"})
    assert r.get_json()["ok"], r.get_json()
    eid = r.get_json()["event_id"]
    with store.conn() as (cx, cur):
        e = store.one(cur, "SELECT event_date, shift FROM loss_event")
    assert e["event_date"] == before.date().isoformat(), e
    assert e["shift"] == clock.SHIFT_LETTER[clock.shift_of(before.hour)], e
    real_now = clock.now
    clock.now = lambda: datetime.datetime(2026, 9, 26, 0, 30, 0)
    try:
        r = c.post("/api/loss_event/%d/close" % eid)
    finally:
        clock.now = real_now
    assert r.get_json()["minutes"] == 40, r.get_json()


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
