"""
ICON TRACE - Needs Review: scan items that can be DISCARDED.

    python test_review_discard.py          (the last test needs Playwright)

Mukesh: "not in master there is not one option - resolve by planning - but there
are some errors which can't be resolved by planning, like ICON625R1293022642- or
"ICON625R1293022642, no way to discard them." and "FQC redesign: probe / zig error
or testing error goes to anomaly, but now it goes to not in master - after planning
do they go to the anomaly section?"

THE RULES THIS FILE DEFENDS

  1. A scan that is not a serial at all (a stray "-" or quote after one) and a
     serial-shaped scan that nobody will plan can be DISCARDED, with a reason.
     A failed reading, a skipped tester, an undecided lookup cannot - they are
     about a real module and are acknowledged.
  2. One tester row raised twice ("Not in master - malformed" AND "FTR anomaly -
     junk ID") is ONE decision: closing either closes its twin.
  3. A discard sticks: the same row still sitting in the tester's file does not
     bring it back; a LATER scan of the same unplanned serial does.
  4. A serial that IS in the master has nothing to discard (it closes itself); an
     unplanned one cannot be "resolved" without planning - discard is the other way.
  5. A bad reading (probe / jig / polarity) is an ANOMALY whether or not the serial
     is planned; an unplanned one is ALSO under Not in master, says so, and planning
     closes only that twin.
  6. THE SCREEN: Discard beside Plan it / Resolve, a bar to discard the junk IDs
     together, a reason required.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import csv, os, sys, tempfile, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_ingest                                           # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
TMP = tempfile.mkdtemp(prefix="icontrace_discard_")
SS = os.path.join(TMP, "ss.csv")
_results = []

IN_MASTER = "ICON625R1290220001"
PLANNED_BAD = "ICON625R1290220002"          # planned, probe error
UNPL_BAD = "ICON625R1290220998"             # not planned, probe error
UNPL_OK = "ICON625R1290220999"              # not planned, a good reading
JUNK1 = "ICON625R1290220997-"               # a stray "-"
JUNK2 = '"ICON625R1290220996'               # a stray quote
JUNK3 = "ICON625R129022099"                 # one digit short
T0 = "2026/09/29 10:00:00"


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def row(sid, at, pmax, isc="12.1", voc="48.9"):
    return [at, sid, pmax, isc, voc, "11.8", "52.5", "96.1", "0.41",
            "0.4", "210.0", "23.1", "25.0", "25.0", "1000.0"]


def write(rows):
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def base_rows():
    return [row(IN_MASTER, "2026/09/29 10:00:00", "628.4"),
            row(PLANNED_BAD, "2026/09/29 10:01:00", "0.0055", "nan", "-0.898"),
            row(UNPL_BAD, "2026/09/29 10:02:00", "0.0055", "nan", "-0.898"),
            row(UNPL_OK, "2026/09/29 10:03:00", "610.0"),
            row(JUNK1, "2026/09/29 10:04:00", "610.0"),
            row(JUNK2, "2026/09/29 10:05:00", "610.0"),
            row(JUNK3, "2026/09/29 10:06:00", "610.0")]


def world():
    store.wipe()
    write(base_rows())
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS, "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_root": "", "el_a_root": "", "el_b_root": "", "ss_xml_root": ""})
        for i, s in enumerate((IN_MASTER, PLANNED_BAD)):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R", "wattage": 625,
                "customer": "STOCK", "dcr": "DCR", "format_version": 2,
                "date_produced": "2026-09-29", "shift": 1, "sequence": 1 + i, "state": "planned"})
    ingest()
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def ingest():
    with store.conn() as (cx, cur):
        return icon_ingest.run(db.get_config(cur), cur, db, store)


def items(**where):
    sql = "SELECT * FROM review_item"
    if where:
        sql += " WHERE " + " AND ".join("%s=%%s" % k for k in where)
    with store.conn() as (cx, cur):
        return [dict(r) for r in store.rows(cur, sql + " ORDER BY review_id", tuple(where.values()))]


def one(type_, serial):
    r = [x for x in items(type=type_) if x["serial"] == serial]
    assert len(r) == 1, (type_, serial, r)
    return r[0]


def resolve(c, rid, type_, resolution="", reason="a scanner misfire"):
    return c.post("/api/review/resolve", json={"type": type_, "id": rid, "reason": reason,
                                               "resolution": resolution})


@test("the same tester row is raised twice - Not in master (malformed) and FTR anomaly "
      "(junk ID); discarding either closes BOTH, and the discard is audited")
def t_twin_closed():
    c = world()
    a, b = one("not_in_master_malformed", JUNK1), one("ftr_junk", JUNK1)
    assert a["status"] == b["status"] == "open"
    r = resolve(c, a["review_id"], "not_in_master_malformed", "discard").get_json()
    assert r["ok"] and r["resolution"] == "discarded" and r["twins_closed"] == 1, r
    a, b = one("not_in_master_malformed", JUNK1), one("ftr_junk", JUNK1)
    assert a["status"] == b["status"] == "resolved" and a["resolution"] == b["resolution"] == "discarded"
    assert a["reason"] == b["reason"] == "a scanner misfire"
    # the other junk scans are untouched
    assert one("ftr_junk", JUNK2)["status"] == "open" and one("not_in_master_malformed", JUNK3)["status"] == "open"
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM dispatch_audit WHERE action='review.resolve'")["n"]
    assert n == 1, "the discard was not audited"
    # acknowledging the junk-ID half closes the malformed half the same way
    r = resolve(c, one("ftr_junk", JUNK2)["review_id"], "ftr_junk", "").get_json()
    assert r["resolution"] == "acknowledged" and r["twins_closed"] == 1, r
    assert one("not_in_master_malformed", JUNK2)["status"] == "resolved"


@test("a discard sticks: the row is still in the tester's file and nothing is raised again")
def t_sticks():
    c = world()
    for s in (JUNK1, JUNK3):
        resolve(c, one("not_in_master_malformed", s)["review_id"], "not_in_master_malformed", "discard")
    before = [(x["review_id"], x["status"]) for x in items()]
    ingest()
    ingest()
    assert [(x["review_id"], x["status"]) for x in items()] == before, "a discard came back"


@test("an unplanned serial can be discarded; it stays discarded for the same scan and "
      "comes back only when the module is scanned AGAIN later")
def t_unplanned_discard():
    c = world()
    it = one("not_in_master_unplanned", UNPL_OK)
    # "resolve" without planning is still refused, and says discard is the other way
    r = resolve(c, it["review_id"], "not_in_master_unplanned", "").get_json()
    assert not r["ok"] and "plan it" in r["why"] and "discard" in r["why"], r
    r = resolve(c, it["review_id"], "not_in_master_unplanned", "discard", "typed wrong, not a module").get_json()
    assert r["ok"] and r["resolution"] == "discarded" and r["twins_closed"] == 0, r
    ingest()
    assert one("not_in_master_unplanned", UNPL_OK)["status"] == "resolved", "the same scan reopened it"
    write(base_rows() + [row(UNPL_OK, "2026/09/29 11:30:00", "611.0")])      # scanned again, later
    ingest()
    assert one("not_in_master_unplanned", UNPL_OK)["status"] == "open", "a later scan did not bring it back"


@test("what cannot be discarded: a failed reading, a skipped tester - real modules, acknowledged; "
      "a serial already in the master has nothing to discard; a reason is mandatory")
def t_refusals():
    c = world()
    f = one("ftr_failed", PLANNED_BAD)
    r = resolve(c, f["review_id"], "ftr_failed", "discard").get_json()
    assert not r["ok"] and "cannot be discarded" in r["why"], r
    assert resolve(c, f["review_id"], "ftr_failed", "").get_json()["resolution"] == "acknowledged"
    # a serial that has since been planned: the item closes itself, nothing to discard
    it = one("not_in_master_unplanned", UNPL_OK)
    with store.conn() as (cx, cur):
        store.insert(cur, "serial", {"serial": UNPL_OK, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": 625, "customer": "STOCK", "dcr": "DCR", "format_version": 2,
            "date_produced": "2026-09-29", "shift": 1, "sequence": 9, "state": "planned"})
    r = resolve(c, it["review_id"], "not_in_master_unplanned", "discard").get_json()
    assert not r["ok"] and "closes itself" in r["why"], r
    r = c.post("/api/review/resolve", json={"type": "not_in_master_malformed",
                                            "id": one("not_in_master_malformed", JUNK3)["review_id"],
                                            "resolution": "discard", "reason": "  "})
    assert r.status_code == 400 and "Say why" in r.get_json()["why"], r.get_json()
    anon = APP.app.test_client()
    assert anon.post("/api/review/resolve", json={"type": "ftr_junk", "id": 1, "reason": "x"}).status_code == 401
    assert anon.post("/api/review/discard-many", json={"ids": [1], "reason": "x"}).status_code == 401


@test("discard-many: one reason, every junk scan on the list; the twins of ones already "
      "discarded are skipped, not an error; nothing else is touched")
def t_many():
    c = world()
    junk = [x["review_id"] for x in items() if x["type"] in ("not_in_master_malformed", "ftr_junk")]
    assert len(junk) == 6, junk
    r = c.post("/api/review/discard-many", json={"ids": junk, "reason": "scanner misfires"}).get_json()
    assert r == {"ok": True, "discarded": 3, "skipped": 3}, r
    assert all(x["status"] == "resolved" and x["resolution"] == "discarded"
               for x in items() if x["type"] in ("not_in_master_malformed", "ftr_junk"))
    assert one("not_in_master_unplanned", UNPL_OK)["status"] == "open" and one("ftr_failed", UNPL_BAD)["status"] == "open"
    assert c.post("/api/review/discard-many", json={"ids": junk, "reason": ""}).status_code == 400
    assert c.post("/api/review/discard-many", json={"ids": [], "reason": "x"}).status_code == 400
    # a failed reading is not discardable, even asked for in bulk
    r = c.post("/api/review/discard-many", json={"ids": [one("ftr_failed", UNPL_BAD)["review_id"]],
                                                 "reason": "x"})
    assert r.status_code == 400 and "cannot be discarded" in r.get_json()["why"], r.get_json()


@test("a bad reading is an ANOMALY planned or not: the Tester Anomalies list and Scan events hold "
      "both; the unplanned one is also under Not in master and says its reading failed; planning "
      "closes only that twin")
def t_anomaly_flow():
    c = world()
    an = c.get("/api/fqc/anomalies").get_json()
    assert sorted(f["serial"] for f in an["failed"]) == [PLANNED_BAD, UNPL_BAD], an["failed"]
    assert sorted(j["id"] for j in an["junk"]) == sorted([JUNK1, JUNK2, JUNK3])
    rows = c.get("/api/review").get_json()
    kinds = {(r["type"], r["serial"]) for r in rows}
    assert ("ftr_failed", PLANNED_BAD) in kinds and ("ftr_failed", UNPL_BAD) in kinds
    assert ("not_in_master_unplanned", UNPL_BAD) in kinds
    bad = [r for r in rows if r["type"] == "not_in_master_unplanned" and r["serial"] == UNPL_BAD][0]
    good = [r for r in rows if r["type"] == "not_in_master_unplanned" and r["serial"] == UNPL_OK][0]
    assert "FAILED" in bad["detail"] and "Scan events" in bad["detail"], bad["detail"]
    assert "FAILED" not in good["detail"], good["detail"]
    # now Planning catches up with the module whose reading failed
    with store.conn() as (cx, cur):
        store.insert(cur, "serial", {"serial": UNPL_BAD, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": 625, "customer": "STOCK", "dcr": "DCR", "format_version": 2,
            "date_produced": "2026-09-29", "shift": 1, "sequence": 8, "state": "planned"})
    ingest()
    assert one("not_in_master_unplanned", UNPL_BAD)["status"] == "resolved"
    assert one("ftr_failed", UNPL_BAD)["status"] == "open", "the anomaly went away with the planning"
    an = c.get("/api/fqc/anomalies").get_json()
    assert UNPL_BAD in [f["serial"] for f in an["failed"]]


@test("on Needs Review: Discard beside Plan it and Resolve, a bar to discard the junk IDs "
      "together, a reason required, and the rows go")
def t_screen():
    world()
    with H.browser() as b:
        pg = H.open_page(b, "review")
        pg.wait_for_selector("#rvRows tr", timeout=8000)
        pg.click("#v-review .card-h .seg button:has-text('Not in master')")
        pg.wait_for_timeout(400)
        rows = pg.inner_text("#rvRows")
        assert "ICON625R1290220997-" in rows and UNPL_OK in rows, rows[:400]
        un = pg.locator("#rvRows tr", has_text=UNPL_OK)
        assert un.locator("button:has-text('Plan it')").count() == 1
        assert un.locator("button:has-text('Discard')").count() == 1
        ju = pg.locator("#rvRows tr", has_text="ICON625R1290220997-").first
        assert ju.locator("button:has-text('Resolve')").count() == 1
        assert ju.locator("button:has-text('Discard')").count() == 1
        assert "Discard these" in pg.inner_text("#rvBulk")
        # a single discard needs a reason
        ju.locator("button:has-text('Discard')").click()
        pg.wait_for_selector("#revWhy", timeout=4000)
        pg.click("#mdlGeneric button:has-text('Discard')")
        pg.wait_for_timeout(300)
        assert "Say why" in pg.inner_text("body")
        pg.fill("#revWhy", "stray dash after the serial")
        pg.click("#mdlGeneric button:has-text('Discard')")
        pg.wait_for_function("() => !document.getElementById('rvRows').innerText.includes('ICON625R1290220997-')",
                             timeout=6000)
        # the unplanned one: discard it too
        pg.locator("#rvRows tr", has_text=UNPL_OK).locator("button:has-text('Discard')").click()
        pg.fill("#revWhy", "typed wrong")
        pg.click("#mdlGeneric button:has-text('Discard')")
        pg.wait_for_function("(s) => !document.getElementById('rvRows').innerText.includes(s)", arg=UNPL_OK, timeout=6000)
        # the rest of the junk, together
        pg.click("#rvBulkBtn")
        pg.wait_for_selector("#revWhy", timeout=4000)
        pg.fill("#revWhy", "scanner misfires")
        pg.click("#mdlGeneric button:has-text('Discard')")
        pg.wait_for_function("() => !document.getElementById('rvBulk')", timeout=6000)
        left = pg.inner_text("#rvRows")
        assert "ICON625R1290220996" not in left and "ICON625R129022099" not in left.replace("ICON625R1290220998", ""), left
        assert UNPL_BAD in left, "the unplanned module with the failed reading is still there"
        assert not pg.errors, pg.errors
    assert all(x["status"] == "resolved" for x in items() if x["type"] in ("not_in_master_malformed", "ftr_junk"))


@test("a scanner's invisible character in front of a serial is SHOWN, not hidden: what looks like "
      "a valid serial but is 'malformed' says why, in Needs Review and in the Tester Anomalies list")
def t_invisible_chars():
    world()
    dirty = "ICON625R1290220995"                          # Ctrl-V from the scanner, then a real serial
    write(base_rows() + [row(dirty, "2026/09/29 10:07:00", "610.0")])
    ingest()
    assert one("not_in_master_malformed", dirty)["status"] == "open"
    with H.browser() as b:
        pg = H.open_page(b, "review")
        pg.wait_for_selector("#rvRows tr", timeout=8000)
        pg.click("#v-review .card-h .seg button:has-text('Not in master')")
        pg.wait_for_timeout(400)
        rows = pg.inner_text("#rvRows")
        assert "‹0x16›ICON625R1290220995" in rows.replace("‹", "‹"), rows[:600]
        pg.locator("#rvRows tr", has_text="ICON625R1290220995").first.locator("button:has-text('Discard')").click()
        pg.wait_for_selector("#revWhy", timeout=4000)
        assert "0x16" in pg.inner_text("#mdlTitle"), pg.inner_text("#mdlTitle")
        assert not pg.errors, pg.errors


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            if only and not any(o in fn.__name__ for o in only):
                continue
            try:
                fn()
                print("  PASS  %-*s" % (width, name))
                passed += 1
            except Exception as e:
                print("  FAIL  %-*s  %s" % (width, name, str(e)[:600]))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
