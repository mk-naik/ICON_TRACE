"""
ICON TRACE - tests for Stage 5 event recording (icon_ingest.py).

    python test_icon_ingest.py

THE RULES THIS FILE DEFENDS

  1. NOT IN MASTER splits at detection: a scan that does not even look like
     a serial is MALFORMED; one that does, but is not in the master, is
     UNPLANNED.

  2. SS SKIP is a serial in the master with an EL image on file and NO Sun
     Simulator row anywhere - not a bad reading, a missing one.

  3. LOOKED UP, NO DECISION is a lookup old enough that it is not simply
     mid-decision, with no FQC record written for that serial since.

  4. INGEST IS IDEMPOTENT - running the same scan twice over the same CSV
     rows and EL files writes each event once, keyed on (type, raw_id).

  5. Resolving NOT_IN_MASTER_UNPLANNED is refused until the serial actually
     is in the master - Incharge plans it with an indent first.

  6. NOT_IN_MASTER_UNPLANNED IS ONE ROW PER SERIAL, LATEST WINS. A module
     rescanned five times before it is planned updates one open review item,
     not five - and its Sun Simulator reading (ftr_reading) is saved fresh
     each time, so whichever scan is the last one before Incharge plans it
     is the one still available afterwards.

  7. FQC FALLS BACK TO THE SAVED READING. Once Incharge has planned the
     serial, if the live Sun Simulator CSV (and its archive) no longer has
     the row - it rotated away while the item sat in Needs Review - FQC
     still gets Pmax from ftr_reading instead of coming back NA. The module
     was tested once; a stop-the-line re-test to satisfy bookkeeping that
     happened late is not worth it.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_ingest_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_ingest                                            # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


WATT = 625
IN_MASTER = "ICON625R1290220001"       # in master, has an SS row
NO_MASTER = "ICON625R1290220999"       # valid shape, not in master
SS_SKIP_S = "ICON625R1290220002"       # in master, EL image, no SS row
JUNK = "NOT-A-SERIAL"

SS = os.path.join(TMP, "ss.csv")
EL = os.path.join(TMP, "el")
XML = os.path.join(TMP, "XML")         # the tester's own result files


def ss_row(sid, at, pmax):
    return [at, sid, pmax, "12.1", "48.9", "11.8", "52.5", "96.1", "0.41",
            "0.4", "210.0", "23.1", "25.0", "25.0", "1000.0"]


def write_ss(rows):
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def put_xml(serial, day="20260929", pmax="630.0", at="2026/09/29 10:03:00"):
    """One of the tester's per-module result files - what says a module WAS
    tested after its CSV row was cut away."""
    d = os.path.join(XML, day)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, serial + ".xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?><IVTestData><Result>'
                 "<Date>%s</Date><ID>%s</ID><Pmax>%s</Pmax><Isc>12.1</Isc>"
                 "<Voc>48.9</Voc></Result></IVTestData>" % (at, serial, pmax))


def setup(xml_root=True):
    store.wipe()
    shutil.rmtree(EL, ignore_errors=True)
    shutil.rmtree(XML, ignore_errors=True)
    import icon_evidence as _ev
    _ev.clear_xml_cache()
    if xml_root:
        os.makedirs(XML, exist_ok=True)
    os.makedirs(os.path.join(EL, "2026-09-29", "早班", "Cell Crack"),
               exist_ok=True)
    open(os.path.join(EL, "2026-09-29", "早班", "Cell Crack",
                      SS_SKIP_S + ".jpg"), "w").close()
    write_ss([
        ss_row(IN_MASTER, "2026-09-29 10:00:00", "628.4"),
        ss_row(JUNK, "2026-09-29 10:01:00", "600.0"),
        ss_row(NO_MASTER, "2026-09-29 10:02:00", "610.0"),
    ])
    with store.conn() as (cx, cur):
        db.set_config(cur, {
            "ss_csv_path": SS, "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL, "el_a_root": "", "el_b_root": "",
            "ss_xml_root": XML if xml_root else ""})
        for i, s in enumerate((IN_MASTER, SS_SKIP_S)):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-29",
                "shift": 1, "sequence": 1 + i, "state": "planned"})
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def _two_hours_ago():
    """Past the 30-minute 'mid-decision' window and inside the 3-day look-back -
    a fixed date here expired on its own (it did, on 2026-10-03)."""
    import datetime, icon_clock
    return (icon_clock.now() - datetime.timedelta(hours=2)).isoformat(timespec="seconds")


def run_ingest(cur):
    cfg = db.get_config(cur)
    return icon_ingest.run(cfg, cur, db, store)


@test("a malformed scan and a valid-but-unplanned one are split at detection")
def t_not_in_master_split():
    setup()
    with store.conn() as (cx, cur):
        counts = run_ingest(cur)
    assert counts.get("not_in_master_malformed") == 1, counts
    assert counts.get("not_in_master_unplanned") == 1, counts
    with store.conn() as (cx, cur):
        rows = {r["type"]: r["serial"] for r in
               store.rows(cur, "SELECT type, serial FROM review_item")}
    assert rows["not_in_master_malformed"] == JUNK, rows
    assert rows["not_in_master_unplanned"] == NO_MASTER, rows


@test("a serial in master never shows up as not-in-master")
def t_in_master_not_flagged():
    setup()
    with store.conn() as (cx, cur):
        run_ingest(cur)
        rows = store.rows(cur, "SELECT serial FROM review_item WHERE "
                               "type LIKE 'not_in_master%'")
    assert IN_MASTER not in [r["serial"] for r in rows]


@test("SS skip: in master, an EL image on file, no Sun Simulator row anywhere")
def t_ss_skip():
    setup()
    with store.conn() as (cx, cur):
        counts = run_ingest(cur)
    assert counts.get("ss_skip") == 1, counts
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM review_item WHERE type='ss_skip'")
    assert row["serial"] == SS_SKIP_S, dict(row)
    assert row["source"] == "el_ingest", dict(row)


@test("a serial with a real SS row is never flagged SS skip")
def t_ss_skip_not_when_read():
    setup()
    write_ss([
        ss_row(IN_MASTER, "2026-09-29 10:00:00", "628.4"),
        ss_row(JUNK, "2026-09-29 10:01:00", "600.0"),
        ss_row(NO_MASTER, "2026-09-29 10:02:00", "610.0"),
        ss_row(SS_SKIP_S, "2026-09-29 10:03:00", "630.0"),
    ])
    with store.conn() as (cx, cur):
        counts = run_ingest(cur)
    assert "ss_skip" not in counts, counts


@test("SS skip is NOT claimed when the tester's own result file has the module - "
      "its CSV row was cut away, which is not the same as never tested")
def t_ss_skip_confirmed_against_result_file():
    setup()
    put_xml(SS_SKIP_S)                       # tested; the row has since been cut
    with store.conn() as (cx, cur):
        counts = run_ingest(cur)
    assert "ss_skip" not in counts, counts
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                              "type='ss_skip'")["n"] == 0


@test("with no way to confirm - no archive path and no result files - nothing is "
      "flagged SS skip at all: the cut CSV would make every module look skipped")
def t_ss_skip_needs_something_to_confirm_against():
    setup(xml_root=False)
    with store.conn() as (cx, cur):
        counts = run_ingest(cur)
    assert "ss_skip" not in counts, counts
    # and the rest of the pass still happens
    assert counts.get("not_in_master_unplanned") == 1, counts


@test("the EL day folders are chosen by the DATE they name, so a stray folder "
      "nobody dated does not take the day's place")
def t_el_days_by_date():
    setup()
    os.makedirs(os.path.join(EL, "New folder", "Burning"), exist_ok=True)
    os.makedirs(os.path.join(EL, "2026-09-28", "早班", "OK"), exist_ok=True)
    open(os.path.join(EL, "2026-09-28", "早班", "OK", IN_MASTER + ".jpg"), "w").close()
    picked = [e.name for e in icon_ingest._el_day_dirs(EL, days=2)]
    assert picked == ["2026-09-29", "2026-09-28"], picked
    assert [e.name for e in icon_ingest._el_day_dirs(EL, days=1)] == ["2026-09-29"]
    assert icon_ingest._el_day_name("New folder") is None
    assert icon_ingest._el_day_name("16-09-2026") == (2026, 9, 16)   # the real share has one
    assert icon_ingest._el_day_name("2026-09-29") == (2026, 9, 29)
    serials = {s for s, _c, _m, _p in icon_ingest._el_recent_files(EL, days=2)}
    assert serials == {SS_SKIP_S, IN_MASTER}, serials


@test("re-running the same scan over the same rows and files writes nothing new")
def t_idempotent():
    setup()
    with store.conn() as (cx, cur):
        first = run_ingest(cur)
        second = run_ingest(cur)
        n = store.one(cur, "SELECT COUNT(*) AS n FROM review_item")["n"]
    assert sum(first.values()) > 0, first
    assert second == {}, second
    assert n == sum(first.values()), \
        "the second pass added rows despite nothing new: %d vs %d" % \
        (n, sum(first.values()))


@test("an unplanned serial rescanned before it is planned is one review "
      "item, not one per scan - and the Sun Simulator reading saved is the "
      "latest one, not the first")
def t_unplanned_rescan_keeps_latest():
    setup()
    with store.conn() as (cx, cur):
        run_ingest(cur)
        # rescanned later with a different Pmax, before Incharge has planned it
        write_ss([
            ss_row(IN_MASTER, "2026-09-29 10:00:00", "628.4"),
            ss_row(JUNK, "2026-09-29 10:01:00", "600.0"),
            ss_row(NO_MASTER, "2026-09-29 10:02:00", "610.0"),
            ss_row(NO_MASTER, "2026-09-29 10:20:00", "615.5"),
        ])
        run_ingest(cur)
        rows = store.rows(cur, "SELECT review_id FROM review_item WHERE "
                               "type='not_in_master_unplanned' AND serial=%s",
                          (NO_MASTER,))
        assert len(rows) == 1, \
            "one row per scan instead of one per serial: %s" % [dict(r) for r in rows]
        ftr = db.get_ftr_reading(cur, NO_MASTER)
    assert ftr["reading"]["pmax"] == 615.5, \
        "the saved reading is not the latest scan: %s" % ftr["reading"]


@test("once planned, FQC uses the saved reading even if the live CSV has "
      "since moved on - no re-test, no stopping the line")
def t_fqc_falls_back_to_saved_reading():
    c = setup()
    with store.conn() as (cx, cur):
        run_ingest(cur)
        # Incharge plans it - now in the master
        store.insert(cur, "serial", {
            "serial": NO_MASTER, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-29",
            "shift": 1, "sequence": 50, "state": "planned"})
    # the CSV has since rotated - the row that first flagged it is gone
    write_ss([])
    d = c.get("/api/fqc/lookup?serial=" + NO_MASTER).get_json()
    assert d["evidence"]["ss_state"] == "OK", \
        "fell back to NA instead of the saved reading: %s" % d["evidence"]
    assert d["evidence"]["pmax"] == 610.0, d["evidence"]
    assert "Saved reading" in d["evidence"]["ss_note"], d["evidence"]
    # 610.0 W is genuinely below this module's 625 W wattage - the saved
    # reading is real evidence, not a free pass, so FQC still cannot pass it
    assert d["pass_route"] is None and "Retest" in d["pass_why"], d
    r = c.post("/api/fqc", json={"serial": NO_MASTER, "outcome": "reject",
                                 "defect": "Cell Crack"})
    assert r.status_code == 200, r.get_json()
    with store.conn() as (cx, cur):
        rec = store.one(cur, "SELECT ss_pmax, ss_state FROM fqc_record "
                             "WHERE serial=%s", (NO_MASTER,))
    assert rec["ss_pmax"] == 610.0 and rec["ss_state"] == "OK", dict(rec)


@test("a lookup with no decision, old enough not to be mid-decision, is caught")
def t_looked_up_no_decision():
    c = setup()
    r = c.get("/api/fqc/lookup?serial=" + IN_MASTER)
    assert r.status_code == 200, r.get_json()
    with store.conn() as (cx, cur):
        # backdate the lookup past the window - a fresh one must not fire
        cur.execute("UPDATE fqc_lookup_log SET at=%s "
                   "WHERE serial=%s", (_two_hours_ago(), IN_MASTER))
        counts = run_ingest(cur)
    assert counts.get("looked_up_no_decision") == 1, counts


@test("a lookup followed by a decision is not flagged")
def t_looked_up_then_decided():
    c = setup()
    c.get("/api/fqc/lookup?serial=" + IN_MASTER)
    with store.conn() as (cx, cur):
        cur.execute("UPDATE fqc_lookup_log SET at=%s "
                   "WHERE serial=%s", (_two_hours_ago(), IN_MASTER))
    r = c.post("/api/fqc", json={"serial": IN_MASTER, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    with store.conn() as (cx, cur):
        counts = run_ingest(cur)
    assert "looked_up_no_decision" not in counts, counts


@test("a fresh lookup (inside the window) is not flagged yet")
def t_looked_up_too_recent():
    c = setup()
    c.get("/api/fqc/lookup?serial=" + IN_MASTER)
    with store.conn() as (cx, cur):
        counts = run_ingest(cur)
    assert "looked_up_no_decision" not in counts, counts


@test("resolving not_in_master_unplanned is refused until the serial is "
      "actually in the master")
def t_resolve_unplanned_needs_master():
    c = setup()
    with store.conn() as (cx, cur):
        run_ingest(cur)
        rid = store.one(cur, "SELECT review_id FROM review_item WHERE "
                             "type='not_in_master_unplanned'")["review_id"]
    r = c.post("/api/review/resolve",
              json={"type": "not_in_master_unplanned", "id": rid,
                    "reason": "planning it now"},
              headers=_as_role(c, "Production Incharge"))
    assert r.status_code == 400, r.get_json()
    assert "not in the serial master" in r.get_json()["why"], r.get_json()

    with store.conn() as (cx, cur):
        store.insert(cur, "serial", {
            "serial": NO_MASTER, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-29",
            "shift": 1, "sequence": 99, "state": "planned"})
    r = c.post("/api/review/resolve",
              json={"type": "not_in_master_unplanned", "id": rid,
                    "reason": "planned with indent IND-1"},
              headers=_as_role(c, "Production Incharge"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["resolution"] == "planned", r.get_json()


@test("an ingest-found item needs a Production Shift Incharge or above to resolve")
def t_resolve_needs_incharge():
    c = setup()
    with store.conn() as (cx, cur):
        run_ingest(cur)
        rid = store.one(cur, "SELECT review_id FROM review_item WHERE "
                             "type='not_in_master_malformed'")["review_id"]
    r = c.post("/api/review/resolve",
              json={"type": "not_in_master_malformed", "id": rid,
                    "reason": "scanner misfire"},
              headers=_as_role(c, "FQC Operator"))
    assert r.status_code == 403, r.get_json()
    r = c.post("/api/review/resolve",
              json={"type": "not_in_master_malformed", "id": rid,
                    "reason": "scanner misfire"},
              headers=_as_role(c, "Production Incharge"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["resolution"] == "acknowledged", r.get_json()


@test("ingest items appear in the merged Needs Review feed")
def t_shows_in_feed():
    c = setup()
    with store.conn() as (cx, cur):
        run_ingest(cur)
    types = {i["type"] for i in c.get("/api/review").get_json()}
    assert "not_in_master_malformed" in types, types
    assert "not_in_master_unplanned" in types, types
    assert "ss_skip" in types, types


def _as_role(c, role):
    AUTH.test_login(c, role=role)
    return {}


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
