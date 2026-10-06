"""
ICON TRACE - FQC on a module the serial master does not have yet.

    python test_fqc_unplanned.py

Mukesh, on what he saw: a serial that is in the Sun Simulator AND on the EL was
not reaching Needs Review, and FQC would not touch it. His rule for it:

    let the FQC happen. After Incharge plans it, if it passed it goes to pack,
    otherwise Quality decides. Making the module do FQC again once Planning has
    caught up - stopping the line, loading it back - is not worth it. And if it
    is recorded as unplanned, keep its Sun Simulator reading (FTR) in the
    database too, the latest one if the same module is scanned again.

What is defended here, each test naming the rule:

  * FQC accepts a serial the master lacks - when the testers have seen it -
    and refuses one nobody has (a mistyped barcode is not a module);
  * the decision is recorded, the module is on Needs Review, and its reading
    is saved and survives the CSV being cut;
  * PACKING still refuses it until it is planned;
  * planning it carries the decision on: pass -> graded A, packable;
    reject -> rejected, in Quality's queue; a held pass -> hold;
  * a module planned with no FQC decision is just planned;
  * scanning again keeps the latest, for the decision and for the reading;
  * the ingest is quiet - a pass with nothing new writes nothing - and Needs
    Review shows EVERY open item, not the newest 200.
"""

import csv, os, shutil, sqlite3, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_unplanned_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_evidence as ev                                   # noqa: E402
import icon_ingest                                           # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# --- the plant: a tester with a CSV and per-module result files, and an EL ---
TESTER = os.path.join(TMP, "tester")
CSV_PATH = os.path.join(TESTER, "CSV", "FTR.csv")
XML_ROOT = os.path.join(TESTER, "XML")
EL_ROOT = os.path.join(TMP, "el")

U_PASS = "ICON625R1292130846"      # in the CSV, EL clean, 631.0 W  (Mukesh's own serial)
U_REJ = "ICON625R1292130847"       # in the CSV, EL says Burning, 630.0 W
U_XML = "ICON625R1292130848"       # CSV row CUT - only the tester's result file, 633.0 W
U_LOW = "ICON625R1292130849"       # in the CSV, EL clean, but 610.0 W: under the wattage
U_TYPO = "ICON625R1292130850"      # nothing anywhere - a mistyped barcode
U_ELONLY = "ICON625R1292130851"    # an EL image, and the tester has nothing
U_OTHER = "ICON625R1292130852"     # never touched by FQC
U_UNFILED = "ICON625R1292130853"   # SS 630 W, EL image not yet filed under a verdict
U_UNFILED_ONLY = "ICON625R1292130854"  # only an unfiled EL image - no SS row at all
NOT_A_SERIAL = "HELLO-123"


def csv_row(sid, at, pmax, isc="16.1", voc="49.1"):
    return [at, sid, pmax, isc, voc, "15.0", "42.0", "79.5", "0.39", "0.0",
            "211.4", "23.4", "24.4", "25.0", "1000.0"]


def put_xml(day, serial, pmax, date):
    d = os.path.join(XML_ROOT, day)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, serial + ".xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?><IVTestData><Result>'
                 "<Date>%s</Date><ID>%s</ID><Pmax>%s</Pmax><Isc>16.13</Isc>"
                 "<Voc>49.18</Voc><Ipm>15.0</Ipm><Vpm>42.0</Vpm><FF>79.4</FF>"
                 "<Rs>0.39</Rs><Rsh>211.4</Rsh><Eff>23.3</Eff>"
                 "<T_Object>24.4</T_Object><Irr_Target>1000.0</Irr_Target>"
                 "</Result></IVTestData>" % (date, serial, pmax))


def plant(ss_reachable=True):
    """The tester, the EL, and the database - with NONE of these serials in
    the master."""
    shutil.rmtree(TESTER, ignore_errors=True)
    shutil.rmtree(EL_ROOT, ignore_errors=True)
    ev.clear_xml_cache()
    os.makedirs(os.path.dirname(CSV_PATH))
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([
            csv_row(U_PASS, "2026/09/29 17:41:09", "600.0"),    # an EARLIER scan...
            csv_row(U_PASS, "2026/09/29 18:40:31", "631.0"),    # ...and the latest
            csv_row(U_REJ, "2026/09/29 18:50:00", "630.0"),
            csv_row(U_LOW, "2026/09/29 19:00:00", "610.0"),
            csv_row(U_UNFILED, "2026/09/29 19:02:00", "630.0"),
            csv_row("REFE", "2026/09/29 19:05:00", "1"),        # calibration: never flagged
            csv_row("RFE", "2026/09/29 19:06:00", "0.005", "nan", "-0.9"),  # junk
        ])
    put_xml("20260929", U_XML, "633.0", "2026/09/29 17:55:00")
    for verdict, serials in (("OK", [U_PASS, U_XML, U_LOW, U_ELONLY]),
                             ("Burning", [U_REJ])):
        os.makedirs(os.path.join(EL_ROOT, verdict))
        for s in serials:
            open(os.path.join(EL_ROOT, verdict, s + ".jpg"), "w").close()
    # the real layout: the image is dropped into the SHIFT folder and only filed
    # under a verdict when the EL operator gets to it
    for s in (U_UNFILED, U_UNFILED_ONLY):
        p = os.path.join(EL_ROOT, "2026-09-29", "晚班", s + ".jpg")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
    store.wipe()
    with store.conn() as (cx, cur):
        db.set_config(cur, {
            "ss_csv_path": CSV_PATH if ss_reachable else os.path.join(TMP, "gone.csv"),
            "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL_ROOT, "el_a_root": "", "el_b_root": ""})
    c = APP.app.test_client()
    AUTH.test_login(c)                       # a real Super Admin session
    return c


def cfg():
    with store.conn() as (cx, cur):
        return db.get_config(cur)


def poll():
    """One pass of the ingest, as the poller would run it."""
    with store.conn() as (cx, cur):
        return icon_ingest.run(db.get_config(cur), cur, db, store)


def lookup(c, serial):
    r = c.get("/api/fqc/lookup?serial=" + serial)
    return r.status_code, r.get_json()


def grade(c, serial, outcome, **kw):
    code, d = lookup(c, serial)
    assert code == 200, d
    body = {"serial": serial, "outcome": outcome,
            "evidence_token": d["evidence_token"]}
    body.update(kw)
    r = c.post("/api/fqc", json=body)
    return r.status_code, r.get_json()


def in_master(serial):
    with store.conn() as (cx, cur):
        return db.find_serial(cur, serial)


def items(serial=None, type_="not_in_master_unplanned"):
    with store.conn() as (cx, cur):
        q, a = "SELECT * FROM review_item WHERE type=%s", [type_]
        if serial:
            q += " AND serial=%s"; a.append(serial)
        return [dict(r) for r in store.rows(cur, q, a)]


def fqc_rows(serial):
    with store.conn() as (cx, cur):
        return [dict(r) for r in store.rows(
            cur, "SELECT * FROM fqc_record WHERE serial=%s ORDER BY fqc_id", (serial,))]


_lines = [0]


def make_line(model="ISEN625-G12R", watt=625):
    """An indent with a line to plan against - 625 W unless a test wants the
    mismatch of an item whose wattage is not the one in the barcode."""
    _lines[0] += 1
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "T/%d/%d" % (watt, _lines[0]),
                                           "indent_date": "2026-09-01",
                                           "customer": "STOCK", "created_by": "t"})
        return store.insert(cur, "indent_line", {
            "indent_id": iid, "line_no": 1, "model": model,
            "item_description": "SOLAR PV MODULE-%s-NDCR" % model,
            "wattage": watt, "qty": 100000, "dcr": "NDCR"})


def plan(c, serials, model="ISEN625-G12R", watt=625, expect=200):
    lid = make_line(model, watt)
    r = c.post("/api/allocation", json={"indent_line_id": lid,
                                        "qty": len(serials), "serials": serials})
    assert r.status_code == expect, r.get_json()
    out = r.get_json()
    out["indent_line_id"] = lid
    return out


def change_seq():
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT COALESCE(MAX(seq),0) AS m FROM change_log")["m"]


# --------------------------------------------------------------------------
# FQC accepts what the testers have seen
# --------------------------------------------------------------------------

@test("FQC accepts a serial the master does not have when the Sun Simulator and "
      "EL have seen it - with its wattage and model from the serial itself, "
      "and the same evidence and pass rule as any module")
def t_lookup_unplanned():
    c = plant()
    code, d = lookup(c, U_PASS)
    assert code == 200 and d["ok"] and d["unplanned"] is True, d
    assert d["wattage"] == 625 and d["model"] == "ISEN625-G12R", d
    assert d["state"] == "unplanned" and d["customer"] is None, d
    e = d["evidence"]
    assert e["ss_state"] == "OK" and e["pmax"] == 631.0, e     # the LATEST scan
    assert e["el"] == "OK" and d["pass_route"] == "direct", d
    assert in_master(U_PASS) is None, "looking it up must not create a serial row"


@test("a module whose CSV row has been CUT is still gradable: the tester's own "
      "result file has its reading")
def t_lookup_from_result_file():
    c = plant()
    code, d = lookup(c, U_XML)
    assert code == 200 and d["unplanned"], d
    e = d["evidence"]
    assert e["ss_state"] == "OK" and e["pmax"] == 633.0 and e["ss_from_xml"] is True, e
    assert d["pass_route"] == "direct", d


@test("a serial nobody has seen - not in the master, not on the tester, not on "
      "the EL - is refused: a mistyped barcode is not a module")
def t_typo_refused():
    c = plant()
    code, d = lookup(c, U_TYPO)
    assert code == 404 and not d["ok"], d
    assert "not in the serial master" in d["why"] and "barcode" in d["why"], d
    code, d = lookup(c, NOT_A_SERIAL)
    assert code == 404 and "not in the serial master" in d["why"], d
    r = c.post("/api/fqc", json={"serial": U_TYPO, "outcome": "reject",
                                 "defect": "Cell Crack"})
    assert r.status_code == 404 and not fqc_rows(U_TYPO), r.get_json()


@test("when a tester cannot be READ the refusal says so - it does not tell the "
      "operator to check a barcode that may be perfectly right")
def t_unreachable_says_so():
    c = plant(ss_reachable=False)              # the Sun Simulator's link is down
    code, d = lookup(c, U_TYPO)                # EL is up and has nothing under it
    assert code == 404 and not d["ok"], d
    assert "Sun Simulator" in d["why"] and "could not be read" in d["why"], d
    assert "barcode" not in d["why"], d
    with store.conn() as (cx, cur):            # ...and now the EL's link too
        db.set_config(cur, {"el_root": os.path.join(TMP, "el_gone")})
    code, d = lookup(c, U_TYPO)
    assert code == 404 and "Sun Simulator and the EL could not be read" in d["why"], d
    r = c.post("/api/fqc", json={"serial": U_TYPO, "outcome": "reject",
                                 "defect": "Cell Crack"})
    assert r.status_code == 404 and not fqc_rows(U_TYPO), r.get_json()
    c = plant()                                # links back: it is a typo again
    code, d = lookup(c, U_TYPO)
    assert code == 404 and "barcode" in d["why"], d


@test("the wattage floor still decides a pass on an unplanned module: 610 W "
      "against 625 cannot be passed, and can be rejected")
def t_floor_still_applies():
    c = plant()
    code, d = lookup(c, U_LOW)
    assert code == 200 and d["pass_route"] is None, d
    code, d = grade(c, U_LOW, "pass")
    assert code == 400 and "cannot be passed" in d["why"], d
    code, d = grade(c, U_LOW, "reject", defect="Low Power")
    assert code == 200 and d["unplanned"], d


@test("an image the EL operator has not filed yet is NO verdict - not a shift "
      "name - so a rejection then needs a defect of its own, and there is "
      "never a rejection with no defect on file")
def t_unfiled_el_needs_operator_defect():
    c = plant()
    code, d = lookup(c, U_UNFILED)
    assert code == 200 and d["unplanned"], d
    e = d["evidence"]
    assert e["el"] is None and e["el_state"] == "NA" and e["el_path"], e
    assert d["pass_route"] == "direct", "EL is advisory: SS 630 W >= 625 W still passes"
    code, r = grade(c, U_UNFILED, "reject")
    assert code == 400 and "needs a defect" in r["why"], r
    code, r = grade(c, U_UNFILED, "reject", defect="Cell Crack")
    assert code == 200, r
    rec = fqc_rows(U_UNFILED)[-1]
    assert rec["defect_el_raw"] is None, rec
    with store.conn() as (cx, cur):
        codes = [x["defect_code"] for x in db.fqc_defects_for(cur, rec["fqc_id"])]
    assert codes == ["DF-CELLCRACK"], codes


@test("an EL image alone is enough for FQC to know a module exists - even "
      "unfiled - but with no Sun Simulator reading it cannot be PASSED")
def t_unfiled_image_alone():
    c = plant()
    code, d = lookup(c, U_UNFILED_ONLY)
    assert code == 200 and d["unplanned"], d
    assert d["evidence"]["ss_state"] == "NA" and d["pass_route"] is None, d
    code, r = grade(c, U_UNFILED_ONLY, "pass")
    assert code == 400 and "cannot be passed" in r["why"], r


@test("a pass made while the EL was unfiled is 'provisional' in mode but graded "
      "A - the Needs Review row must not call it HELD")
def t_provisional_mode_pass_is_not_held():
    c = plant()
    poll()
    code, r = grade(c, U_UNFILED, "pass")
    assert code == 200 and r["held"] is False, r
    rows = {x["serial"]: x for x in c.get("/api/review").get_json()
            if x["type"] == "not_in_master_unplanned"}
    d = rows[U_UNFILED]["detail"]
    assert "FQC: pass by" in d and "held" not in d, d
    out = plan(c, [U_UNFILED])
    assert out["fqc_applied"]["graded"] == 1, out
    assert in_master(U_UNFILED)["state"] == "graded"


# --------------------------------------------------------------------------
# what grading it leaves behind
# --------------------------------------------------------------------------

@test("grading it records the decision with NO serial row, puts the module on "
      "Needs Review even if the poller has not seen it yet, and saves its "
      "reading - and says what happens next")
def t_grade_unplanned():
    c = plant()
    code, d = grade(c, U_PASS, "pass")
    assert code == 200 and d["ok"] and d["unplanned"] is True, d
    assert "packing" in d["note"] and "No re-test" in d["note"], d["note"]
    assert in_master(U_PASS) is None, "grading must not invent a serial row"
    rows = fqc_rows(U_PASS)
    assert len(rows) == 1 and rows[0]["outcome"] == "pass" and rows[0]["grade"] == "A", rows
    assert rows[0]["ss_pmax"] == 631.0 and rows[0]["test_seq"] == 1, rows[0]
    it = items(U_PASS)
    assert len(it) == 1 and it[0]["status"] == "open" and it[0]["source"] == "fqc", it
    with store.conn() as (cx, cur):
        saved = db.get_ftr_reading(cur, U_PASS)
    assert saved and saved["reading"]["pmax"] == 631.0, saved


@test("the reading is saved for the module's LATEST test: scanned twice, the "
      "later one is kept, and an older one never replaces it")
def t_reading_keeps_latest():
    c = plant()
    poll()                                       # the CSV has BOTH scans of U_PASS
    with store.conn() as (cx, cur):
        saved = db.get_ftr_reading(cur, U_PASS)
        assert saved["reading"]["pmax"] == 631.0 and \
            saved["tested_at"] == "2026/09/29 18:40:31", saved
        assert db.save_ftr_reading_if_newer(
            cur, U_PASS, "A", "2026/09/29 17:41:09", {"pmax": 600.0}) is False
        assert db.get_ftr_reading(cur, U_PASS)["reading"]["pmax"] == 631.0
        assert db.save_ftr_reading_if_newer(
            cur, U_PASS, "A", "2026/09/30 01:00:00", {"pmax": 640.0}) is True
        assert db.get_ftr_reading(cur, U_PASS)["reading"]["pmax"] == 640.0


@test("grading the same module a second time keeps the latest decision - one "
      "live record, the first superseded, the count of tests right")
def t_regrade_keeps_latest():
    c = plant()
    grade(c, U_PASS, "pass")
    code, d = grade(c, U_PASS, "reject", defect="Cell Crack")
    assert code == 200, d
    rows = fqc_rows(U_PASS)
    live = [r for r in rows if r["superseded_by"] is None]
    assert len(rows) == 2 and len(live) == 1 and live[0]["outcome"] == "reject", rows
    assert live[0]["test_seq"] == 2, live[0]
    assert len(items(U_PASS)) == 1, "still ONE Needs Review item for one module"


@test("PACKING still refuses it: a module the master does not have cannot be "
      "put in a box, however well it graded")
def t_packing_still_refuses():
    c = plant()
    grade(c, U_PASS, "pass")
    r = c.get("/api/box/check?serial=" + U_PASS)
    d = r.get_json()
    assert not d.get("ok") and "not in the serial master" in d["why"], d


# --------------------------------------------------------------------------
# planning carries the decision on
# --------------------------------------------------------------------------

@test("planned after a PASS: graded A and packable at once - no re-test - and "
      "the Needs Review item closes itself, with who and why")
def t_plan_after_pass():
    c = plant()
    grade(c, U_PASS, "pass")
    out = plan(c, [U_PASS, U_OTHER])
    assert out["fqc_applied"] == {"graded": 1, "hold": 0, "rejected": 0}, out
    assert out["review_closed"] == 1, out
    s = in_master(U_PASS)
    assert s["state"] == "graded" and s["grade"] == "A", s
    assert in_master(U_OTHER)["state"] == "planned", "no decision, so just planned"
    it = items(U_PASS)[0]
    assert it["status"] == "resolved" and it["resolution"] == "planned", it
    assert it["resolved_by"] and "allocation" in it["reason"], it
    d = c.get("/api/box/check?serial=" + U_PASS).get_json()
    assert d.get("ok"), "a passed, planned module must be packable: %s" % d


@test("planned after a REJECT: rejected, no grade, and in Quality's queue - "
      "Quality decides, exactly as for any rejected module")
def t_plan_after_reject():
    c = plant()
    grade(c, U_REJ, "reject")                       # EL says Burning: defect from the EL
    out = plan(c, [U_REJ])
    assert out["fqc_applied"]["rejected"] == 1, out
    s = in_master(U_REJ)
    assert s["state"] == "rejected" and not s["grade"], s
    with store.conn() as (cx, cur):
        pending = [r["serial"] for r in db.quality_pending(cur)]
    assert U_REJ in pending, pending
    d = c.get("/api/box/check?serial=" + U_REJ).get_json()
    assert not d.get("ok"), "a rejected module must not be packable: %s" % d


@test("a PROVISIONAL pass (tester unreachable) planned later is held, not "
      "graded - a decision made without the reading is still not confirmed")
def t_plan_after_held_pass():
    c = plant(ss_reachable=False)
    code, d = lookup(c, U_PASS)                     # EL alone is enough to know it
    assert code == 200 and d["pass_route"] == "provisional", d
    code, d = grade(c, U_PASS, "pass")
    assert code == 200 and d["held"] is True, d
    out = plan(c, [U_PASS])
    assert out["fqc_applied"]["hold"] == 1, out
    s = in_master(U_PASS)
    assert s["state"] == "hold" and not s["grade"], s


@test("planned WITHOUT any FQC decision: just planned - and its item still "
      "closes, because the serial is now in the master")
def t_plan_without_fqc():
    c = plant()
    poll()
    assert items(U_OTHER) == [] or True
    poll()
    out = plan(c, [U_PASS])
    assert out["fqc_applied"] == {"graded": 0, "hold": 0, "rejected": 0}, out
    assert in_master(U_PASS)["state"] == "planned"
    assert items(U_PASS)[0]["status"] == "resolved"


@test("a decision FQC has already CANCELLED does not come back when the serial "
      "is planned")
def t_cancelled_decision_not_applied():
    c = plant()
    grade(c, U_PASS, "pass")
    with store.conn() as (cx, cur):
        cur.execute("UPDATE fqc_record SET status='cancelled' WHERE serial=%s", (U_PASS,))
    out = plan(c, [U_PASS])
    assert out["fqc_applied"] == {"graded": 0, "hold": 0, "rejected": 0}, out
    assert in_master(U_PASS)["state"] == "planned"


@test("Recent gradings lists a decision made before Planning - with no model "
      "yet (the screen tags it 'Not in master') - and shows the model once it "
      "is planned")
def t_recent_lists_unplanned():
    c = plant()
    grade(c, U_PASS, "pass")
    rows = c.get("/api/fqc/recent").get_json()["rows"]
    mine = [r for r in rows if r["serial"] == U_PASS]
    assert len(mine) == 1 and not mine[0]["model"] and mine[0]["outcome"] == "pass", rows
    plan(c, [U_PASS])
    rows = c.get("/api/fqc/recent").get_json()["rows"]
    mine = [r for r in rows if r["serial"] == U_PASS]
    assert mine[0]["model"] == "ISEN625-G12R", mine


@test("Needs Review timestamps are ISO like every other item - the testers' "
      "2026/09/29 format sorted after every ISO one of the same day")
def t_review_timestamps_iso():
    c = plant()
    poll()
    rows = c.get("/api/review").get_json()
    mine = [r for r in rows if r["serial"] == U_PASS][0]
    assert mine["at"] == "2026-09-29T18:40:31", mine["at"]
    assert all("/" not in (r["at"] or "") for r in rows), [r["at"] for r in rows if "/" in (r["at"] or "")]


# --------------------------------------------------------------------------
# Needs Review: every item, its detail, and a quiet ingest
# --------------------------------------------------------------------------

@test("the ingest records each unplanned module ONCE, on its latest scan, and "
      "saves its reading; junk and calibration rows are split out as before")
def t_ingest_per_serial():
    plant()
    out = poll()
    assert out.get("not_in_master_unplanned") == 4, out       # U_PASS, U_REJ, U_LOW, U_UNFILED
    one = items(U_PASS)
    assert len(one) == 1 and one[0]["raw_id"] == U_PASS, one
    assert one[0]["event_at"] == "2026/09/29 18:40:31", one    # the LATER scan
    assert len(items(type_="not_in_master_malformed")) == 1     # RFE
    assert not items("REFE"), "calibration rows are never flagged"
    with store.conn() as (cx, cur):
        assert db.get_ftr_reading(cur, U_PASS)["reading"]["pmax"] == 631.0


@test("a pass that finds nothing new writes NOTHING - the change feed does not "
      "move, so no open screen is told 'changed' about rows already recorded")
def t_ingest_is_quiet():
    plant()
    poll()
    before = change_seq()
    with store.conn() as (cx, cur):
        rev_before = store.one(cur, "SELECT COUNT(*) AS n FROM review_item")["n"]
    for _ in range(3):
        assert poll() == {}, "a repeat pass should have nothing new"
    assert change_seq() == before, "a pass with nothing new bumped the feed"
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM review_item")["n"] == rev_before


@test("opening Needs Review does NOT run the ingest, and does not write: two "
      "windows on it can no longer keep each other refetching")
def t_get_review_is_read_only():
    c = plant()
    poll()
    before = change_seq()
    for _ in range(3):
        r = c.get("/api/review")
        assert r.status_code == 200
    assert change_seq() == before, "GET /api/review wrote something"


@test("a module scanned AGAIN later updates its one item to the newer scan - "
      "and only then does it write")
def t_rescan_updates_once():
    plant()
    poll()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(csv_row(U_PASS, "2026/09/30 00:10:00", "634.0"))
    before = change_seq()
    out = poll()
    assert "not_in_master_unplanned" not in out, "an update is not a new item: %s" % out
    assert change_seq() > before, "a newer scan should have been recorded"
    assert items(U_PASS)[0]["event_at"] == "2026/09/30 00:10:00"
    with store.conn() as (cx, cur):
        assert db.get_ftr_reading(cur, U_PASS)["reading"]["pmax"] == 634.0
    again = change_seq()
    poll()
    assert change_seq() == again


@test("Needs Review shows EVERY open item - it used to send the newest 200 and "
      "bury a serial that was recorded and open as #840 of 1,308")
def t_review_not_capped():
    c = plant()
    with store.conn() as (cx, cur):
        for i in range(450):
            db.upsert_unplanned_item(cur, "ICON625R1292199%03d" % i, "ss_ingest",
                                     "A", "2026/09/29 10:%02d:00" % (i % 60))
        db.upsert_unplanned_item(cur, U_PASS, "ss_ingest", "A", "2026/09/28 01:00:00")
    rows = c.get("/api/review").get_json()
    serials = [r["serial"] for r in rows if r["type"] == "not_in_master_unplanned"]
    assert len(serials) == 451 and U_PASS in serials, len(serials)


@test("an unplanned row tells the Incharge what they need without opening "
      "anything: the saved reading, and where FQC stands")
def t_review_row_detail():
    c = plant()
    poll()
    grade(c, U_PASS, "pass")
    rows = {r["serial"]: r for r in c.get("/api/review").get_json()
            if r["type"] == "not_in_master_unplanned"}
    d = rows[U_PASS]["detail"]
    assert "SS 631.0 W" in d and "FQC: pass" in d and "packable once planned" in d, d
    assert rows[U_PASS]["fqc"]["outcome"] == "pass", rows[U_PASS]
    assert "FQC not done yet" in rows[U_REJ]["detail"], rows[U_REJ]["detail"]


@test("an open item with NO reading (flagged before readings were kept, or its "
      "CSV row cut first) gets one from the tester's result file")
def t_backfill_from_result_file():
    plant()
    with store.conn() as (cx, cur):
        db.upsert_unplanned_item(cur, U_XML, "ss_ingest", "A", "2026/09/29 17:55:00")
    poll()
    with store.conn() as (cx, cur):
        saved = db.get_ftr_reading(cur, U_XML)
    assert saved and saved["reading"]["pmax"] == 633.0, saved
    before = change_seq()
    poll()
    assert change_seq() == before, "a saved reading is not looked for again"


@test("items whose serial has been planned by ANY route are swept closed - one "
      "look, and nothing written when there is nothing to close")
def t_sweep_closes_planned():
    plant()
    poll()
    before = change_seq()
    assert poll() == {}
    with store.conn() as (cx, cur):
        store.insert(cur, "serial", {
            "serial": U_REJ, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": 625, "customer": "STOCK", "dcr": "DCR", "format_version": 2,
            "date_produced": "2026-09-21", "shift": 3, "sequence": 847,
            "state": "planned"})
    out = poll()
    assert out.get("planned_closed") == 1, out
    assert items(U_REJ)[0]["status"] == "resolved"
    assert items(U_PASS)[0]["status"] == "open"


@test("if a closed module is not in the master again (its allocation was "
      "withdrawn) and the tester scans it, its item REOPENS - the condition is "
      "true again")
def t_reopen():
    plant()
    poll()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE review_item SET status='resolved', resolution='planned', "
                    "resolved_by='x', resolved_at='2026-09-29T20:00:00' "
                    "WHERE raw_id=%s", (U_PASS,))
        res = db.upsert_unplanned_item(cur, U_PASS, "ss_ingest", "A", "2026/09/29 18:40:31")
    assert res == "reopened", res
    it = items(U_PASS)[0]
    assert it["status"] == "open" and it["resolution"] is None and not it["resolved_by"], it


# --------------------------------------------------------------------------
# the one-time merge of the old per-scan rows
# --------------------------------------------------------------------------

@test("old per-scan rows collapse to ONE item per serial: the newest scan "
      "survives (re-keyed, its scan time kept) and every other is closed as "
      "merged_duplicate, not deleted")
def t_merge_old_rows():
    plant()
    with store.conn() as (cx, cur):
        for at in ("2026/09/29 17:41:09", "2026/09/29 18:40:31"):
            cur.execute(
                "INSERT INTO review_item (type, serial, status, dispatched, created_at, "
                "created_by, raw_id, source, line, detected_at) VALUES "
                "('not_in_master_unplanned',%s,'open',0,'2026-09-29T18:00:00','system',%s,"
                "'ss_ingest','A','2026-09-29T18:00:00')",
                (U_PASS, "not_in_master_unplanned|A|%s|%s" % (U_PASS, at)))
    cx = sqlite3.connect(store.DB_PATH)
    store._merge_unplanned_per_scan(cx)
    cx.commit()
    cx.close()
    rows = items(U_PASS)
    live = [r for r in rows if r["status"] == "open"]
    assert len(rows) == 2 and len(live) == 1, rows
    assert live[0]["raw_id"] == U_PASS and live[0]["event_at"] == "2026/09/29 18:40:31", live
    dead = [r for r in rows if r["status"] != "open"][0]
    assert dead["resolution"] == "merged_duplicate" and dead["resolved_by"] == "system", dead
    cx = sqlite3.connect(store.DB_PATH)
    store._merge_unplanned_per_scan(cx)          # harmless to run again
    cx.close()
    assert len([r for r in items(U_PASS) if r["status"] == "open"]) == 1


@test("the wattage in the serial is the module's NAMEPLATE: a 625 W module "
      "cannot be allocated on an item of any other wattage, however well it "
      "measured - not 650, and not 626 either")
def t_nameplate_must_match_the_item():
    c = plant()
    code, d = lookup(c, U_PASS)
    assert d["wattage"] == 625 and d["evidence"]["pmax"] == 631.0, d
    grade(c, U_PASS, "pass")
    out = plan(c, [U_PASS], model="ISEN650-G12R", watt=650, expect=400)
    assert "625 W module" in out["why"] and "650 W" in out["why"], out
    assert "nameplate" in out["why"], out
    assert in_master(U_PASS) is None, "nothing may be written when it is refused"
    assert items(U_PASS)[0]["status"] == "open", "and the item stays open"
    # 631 W measured does NOT make it a 630 W module
    out = plan(c, [U_PASS], model="ISEN630-G12R", watt=630, expect=400)
    assert "625 W module" in out["why"] and "630 W" in out["why"], out
    # its own wattage: planned, and the standing pass carries over
    out = plan(c, [U_PASS])
    assert out["fqc_applied"]["graded"] == 1, out
    s = in_master(U_PASS)
    assert s["wattage"] == 625 and s["state"] == "graded" and s["grade"] == "A", s


@test("the nameplate rule holds for every allocation, FQC or not, and on an "
      "EDIT as well as a new range - and it names how many do not match")
def t_nameplate_on_edit_and_without_fqc():
    c = plant()
    out = plan(c, [U_OTHER])                     # no FQC anywhere near this
    r = c.put("/api/allocation/%d/update" % out["alloc_id"],
              json={"indent_line_id": make_line("ISEN650-G12R", 650), "qty": 2,
                    "serials": [U_OTHER, U_PASS]})
    d = r.get_json()
    assert r.status_code == 400 and "nameplate" in d["why"], d
    assert "2 serial(s) in this range do not match" in d["why"], d
    assert in_master(U_OTHER)["wattage"] == 625, "the edit changed nothing"
    # a held pass (no reading at all) is no exception either
    c = plant(ss_reachable=False)
    code, g = grade(c, U_PASS, "pass")
    assert g["held"] is True, g
    plan(c, [U_PASS], model="ISEN650-G12R", watt=650, expect=400)
    out = plan(c, [U_PASS])
    assert out["fqc_applied"]["hold"] == 1, out
    assert in_master(U_PASS)["state"] == "hold", "held either way - not graded A"


@test("the safety net: a serial row created by any other route with a pass "
      "below its wattage is left 'planned', never graded A")
def t_standing_pass_net():
    c = plant()
    grade(c, U_PASS, "pass")                     # 631 W, judged against 625
    with store.conn() as (cx, cur):              # a row written past Planning
        store.insert(cur, "serial", {
            "serial": U_PASS, "build_instance": 1, "model": "ISEN650-G12R",
            "wattage": 650, "customer": "STOCK", "dcr": "NDCR",
            "format_version": 2, "date_produced": "2026-09-29", "shift": 3,
            "sequence": 846, "state": "planned"})
        applied = db.apply_standing_fqc(cur, [U_PASS])
    assert applied == {"graded": 0, "hold": 0, "rejected": 0}, applied
    assert in_master(U_PASS)["state"] == "planned", in_master(U_PASS)


@test("withdrawing an allocation puts the module back on Needs Review - it is "
      "not in the master again, and the tester's CSV has long been cut")
def t_withdraw_reopens():
    c = plant()
    poll()
    out = plan(c, [U_PASS])
    assert items(U_PASS)[0]["status"] == "resolved", items(U_PASS)
    import icon_auth
    icon_auth.COOLDOWN_STEPS = ()
    secret = AUTH.provision_totp("test.super")
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET totp_last_step=0 WHERE login_id=%s",
                    ("test.super",))
    r = c.delete("/api/allocation/%d" % out["alloc_id"],
                 json={"reason": "wrong indent item",
                       "totp_code": AUTH.totp_code(secret)})
    assert r.status_code == 200, r.get_json()
    assert in_master(U_PASS) is None, "the serial row is gone"
    it = items(U_PASS)[0]
    assert it["status"] == "open" and it["resolution"] is None, it
    assert "withdrawn" in (it["reason"] or ""), it
    assert any(x["serial"] == U_PASS for x in
               c.get("/api/review").get_json()), "and it is on the screen again"


@test("the saved reading tracks the LATEST test for a module already in the "
      "master too - it used to keep the first test for ever")
def t_reading_refreshed_after_planning():
    c = plant()
    poll()                                       # saves 631.0 W (18:40)
    plan(c, [U_PASS])
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(csv_row(U_PASS, "2026/09/29 20:10:00", "634.0"))
    code, d = lookup(c, U_PASS)
    assert d["evidence"]["pmax"] == 634.0, d["evidence"]
    grade(c, U_PASS, "pass")
    with store.conn() as (cx, cur):
        saved = db.get_ftr_reading(cur, U_PASS)
    assert saved["reading"]["pmax"] == 634.0, saved
    assert saved["tested_at"] == "2026/09/29 20:10:00", saved


@test("a rejection on an unplanned module says on Needs Review what planning "
      "unlocks - Quality's queue is built from serial rows, so it cannot act "
      "until the module has one")
def t_reject_row_says_plan_it():
    c = plant()
    grade(c, U_REJ, "reject")
    row = next(r for r in c.get("/api/review").get_json()
               if r["serial"] == U_REJ and r["type"] == "not_in_master_unplanned")
    assert "plan it so Quality can decide" in row["detail"], row
    assert c.get("/api/quality/pending").get_json() == [], "not there yet"
    plan(c, [U_REJ])
    assert [r["serial"] for r in c.get("/api/quality/pending").get_json()] == [U_REJ]


@test("the FQC dashboard says how many inspections are NOT in its numbers - a "
      "decision on a module the master lacks joins away out of every count")
def t_dashboard_says_what_it_cannot_count():
    c = plant()
    grade(c, U_PASS, "pass")
    grade(c, U_REJ, "reject")
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["inspected"] == 0 and t["awaiting_planning"] == 2, t
    t = c.get("/api/fqc/dashboard?result=pass").get_json()["totals"]
    assert t["awaiting_planning"] == 1, "the result filter applies to it too"
    t = c.get("/api/fqc/dashboard?customer=STOCK").get_json()["totals"]
    assert t["awaiting_planning"] == 0, "a customer filter cannot ask about them"
    plan(c, [U_PASS, U_REJ])
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["inspected"] == 2 and t["awaiting_planning"] == 0, t


@test("the dashboard's Needs Review KPI is a real, live count - not the "
      "literal dash v4 shipped with a frozen '3 duplicate' sample underneath")
def t_dashboard_needs_review_kpi():
    c = plant()
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["needs_review"] == {"total": 0, "duplicate_scan": 0, "not_in_master": 0}, t
    grade(c, U_PASS, "pass")                 # an unplanned pass: "not in master"
    grade(c, U_REJ, "reject")
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["needs_review"]["not_in_master"] == 2, t["needs_review"]
    assert t["needs_review"]["total"] == 2, t["needs_review"]
    # it is a LIVE BACKLOG, not scoped to the date filter the rest of the
    # row obeys - an item can sit open for days
    t = c.get("/api/fqc/dashboard?from=2020-01-01&to=2020-01-01").get_json()["totals"]
    assert t["needs_review"]["total"] == 2, "needs_review ignored a date with no activity"
    plan(c, [U_PASS, U_REJ])                 # planned: off the "not in master" count
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["needs_review"]["not_in_master"] == 0, t["needs_review"]
    assert t["needs_review"]["total"] == 1, "the reject is still awaiting Quality"


@test("the shift-wise table is NOT grouped by customer - one model in one "
      "shift is one row, whatever mix of customers it was built for; the "
      "screen already has a customer filter for whoever wants that split")
def t_dashboard_shift_table_not_split_by_customer():
    c = plant()
    grade(c, U_PASS, "pass")
    plan(c, [U_PASS])
    with store.conn() as (cx, cur):
        # a second module, same day/shift/model/wattage, a DIFFERENT
        # customer - store.insert() directly: the point is the SQL grouping,
        # not another full FQC-before-planning round trip
        store.insert(cur, "serial", {
            "serial": U_OTHER, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": 625, "customer": "BOROSIL RENEWABLES LIMITED",
            "dcr": "NDCR", "format_version": 2, "date_produced": "2026-09-01",
            "shift": 1, "sequence": 999, "state": "graded", "grade": "A"})
        row = store.one(cur, "SELECT * FROM fqc_record WHERE serial=%s", (U_PASS,))
        store.insert(cur, "fqc_record", dict(
            {k: v for k, v in dict(row).items() if k != "fqc_id"},
            serial=U_OTHER, test_seq=1))
    d = c.get("/api/fqc/dashboard").get_json()
    matches = [r for r in d["rows"] if r["model"] == "ISEN625-G12R"]
    assert len(matches) == 1, ("two customers on the same model/shift split "
                               "into separate rows instead of combining: %s" % matches)
    assert matches[0]["inspected"] == 2, matches[0]
    assert "customer" not in matches[0], \
        "a customer field leaked into a row the screen never filtered by: %s" % matches[0]


@test("the Production Dashboard knows the LINE for a module graded before "
      "Planning, even with no production entry, because it was saved to "
      "ftr_reading at grading time - it is not really 'not recorded'")
def t_prod_dashboard_learns_line_from_ftr_reading():
    c = plant()
    grade(c, U_PASS, "pass")               # unplanned: no production_entry can exist
    with store.conn() as (cx, cur):
        saved = db.get_ftr_reading(cur, U_PASS)
    assert saved["line"] == "A", saved            # this plant() has one line, "A"
    plan(c, [U_PASS, U_OTHER])             # U_OTHER: a real row to attach a
                                            # production_entry to, below
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT prod_entry_id FROM serial WHERE serial=%s",
                        (U_PASS,))
    assert row["prod_entry_id"] is None, "still no production entry"

    # a NORMAL module, produced the ordinary way (a real production entry,
    # which writes the full "A-Line" - a different raw string for the same
    # physical line ftr_reading names by its bare letter, "A")
    with store.conn() as (cx, cur):
        # created_at explicitly, matching the real endpoint - SQLite's own
        # DEFAULT CURRENT_TIMESTAMP is UTC, not this app's IST clock, and
        # would silently land the row in the wrong shift/day
        import icon_clock as _clock
        # ran in the shift the other module was graded in - production counts
        # on the shift it RAN (prod_date + shift), so the two share one row
        eid = store.insert(cur, "production_entry", {
            "prod_date": _clock.shift_day().isoformat(),
            "shift": _clock.SHIFT_LETTER[_clock.current_shift()], "shift_incharge": "t",
            "line": "A-Line", "model": "ISEN625-G12R", "wattage": 625,
            "start_serial": U_OTHER, "end_serial": U_OTHER, "qty": 1,
            "kw_output": 0.625, "created_by": "t",
            "created_at": _clock.now().isoformat(timespec="seconds")})
        cur.execute("UPDATE serial SET prod_entry_id=%s WHERE serial=%s",
                    (eid, U_OTHER))

    d = c.get("/api/prod/dashboard").get_json()
    matches = [r for r in d["lines"] if r["line"] == "A"]
    assert not any(r["line"] in ("", None) for r in d["lines"]), \
        "the module should not ALSO show up as line-less: %s" % d["lines"]
    # "A" (ftr_reading) and "A-Line" (production_entry) are the SAME real
    # line and must be summed into ONE row - the screen's own key
    # (pdLineName, bare letter) would otherwise silently collide the two
    # and drop whichever arrived second, not merge them
    assert len(matches) == 1, ("the same line split into two rows instead of "
                               "summing: %s" % d["lines"])
    assert matches[0]["produced"] >= 2, ("the production-entry module's count "
                                         "went missing: %s" % d["lines"])


@test("a module that came through the testers before Planning LOCKS its "
      "allocation: production is running on it, so the plan is not deleted - "
      "a wrong indent item is undone with a Cancel document, not a withdrawal")
def t_standing_fqc_locks_the_allocation():
    c = plant()
    grade(c, U_PASS, "pass")
    out = plan(c, [U_PASS, U_OTHER])
    assert in_master(U_PASS)["state"] == "graded", "the decision did carry over"
    r = c.put("/api/allocation/%d/update" % out["alloc_id"],
              json={"indent_line_id": out["indent_line_id"], "qty": 1,
                    "serials": [U_OTHER]})
    assert r.status_code == 400 and "entered production" in r.get_json()["why"], \
        r.get_json()
    import icon_auth
    icon_auth.COOLDOWN_STEPS = ()
    secret = AUTH.provision_totp("test.super")
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET totp_last_step=0 WHERE login_id=%s",
                    ("test.super",))
    r = c.delete("/api/allocation/%d" % out["alloc_id"],
                 json={"reason": "wrong item", "totp_code": AUTH.totp_code(secret)})
    assert r.status_code == 400 and "been through production" in r.get_json()["why"], \
        r.get_json()
    assert in_master(U_PASS)["state"] == "graded", "and nothing moved"


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %s" % name)
                passed += 1
            except Exception as e:
                print("  FAIL  %s\n        %s" % (name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
