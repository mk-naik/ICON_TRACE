"""
ICON TRACE - tests for what an FQC decision is allowed to contain.

    python test_fqc.py

THE RULES THIS FILE DEFENDS

  1. The operator supplies the JUDGEMENT - pass or reject, and the reason
     when it differs from the proposal. The MEASUREMENT is read from the
     tester by the server and is never accepted from the browser. A record
     has to say what the Sun Simulator actually reported; if the request
     body can supply it, the BAD block is decorative and fqc_record can
     hold a Pmax no tester ever produced.

  2. FQC does not grade. It records PASS or REJECT. A pass is grade A, and
     A means Pmax at or above its rated wattage with a clean EL.

  3. A PASS CANNOT BE OVERRULED. A module that measures short goes back to
     the Sun Simulator; no reason text turns it into a full-power module.
     Rejecting is always allowed - a person may see what the evidence does
     not.

  4. A reject has NO GRADE until Quality calls it GY or BGY, and no grade is
     what keeps it out of a box.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_fqc_")
# before importing the app: it reads the path once, at import
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_evidence as ev                                   # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH


def as_role(c, role):
    """A REAL session in `role` on this client, and no headers at all -
    X-User-Role was the spoofable thing Round 23 removed, so this test
    proves the gate with a genuine account rather than a claim to one."""
    AUTH.test_login(c, role=role)
    return {}


_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


WATT = 625
DEAD_S = "ICON625R1290220483"      # tested twice, never read
FULL = "ICON625R1290220484"        # makes nameplate, EL clean
SHORT = "ICON625R1290220485"       # clean EL, but below nameplate
CRACKED = "ICON625R1290220486"     # makes nameplate, EL says Cell Crack


# 0 time  1 id  2 Pmax  3 Isc  4 Voc  5 Ipm  6 Vpm  7 FF  8 Rs  9 Rs_M
# 10 Rsh  11 Eff  12 T_Object  13 T_Target  14 Irr
def row(sid, at, pmax, isc="12.1", voc="48.9"):
    return [at, sid, pmax, isc, voc, "11.8", "52.5", "96.1", "0.41", "0.4",
            "210.0", "23.1", "25.0", "25.0", "1000.0"]


# the real signature of a probe that was not connected
DEAD = [row(DEAD_S, "2026-09-07 09:00:00", "0.0055", "nan", "-0.898"),
        row(DEAD_S, "2026-09-07 09:30:00", "0.0061", "nan", "-0.902")]
ROWS = DEAD + [
    row(FULL, "2026-09-07 10:00:00", "628.4"),      # >= 625
    row(SHORT, "2026-09-07 10:05:00", "620.5"),     # <  625
    row(CRACKED, "2026-09-07 10:10:00", "631.0"),   # >= 625, but cracked
]

SS = os.path.join(TMP, "ss.csv")
EL_ROOT = os.path.join(TMP, "el")
for verdict, serials in (("OK", [FULL, SHORT]), ("Cell Crack", [CRACKED])):
    os.makedirs(os.path.join(EL_ROOT, verdict))
    for s in serials:
        open(os.path.join(EL_ROOT, verdict, s + ".jpg"), "w").close()


def write_ss(rows):
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def setup(ss_rows=None, ss_path=None):
    """A clean database with the serials in the master, and a configured
    tester unless the test wants an unreachable one."""
    store.wipe()
    write_ss(ss_rows if ss_rows is not None else ROWS)
    with store.conn() as (cx, cur):
        db.set_config(cur, {
            "ss_csv_path": SS if ss_path is None else ss_path,
            "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL_ROOT, "el_a_root": "", "el_b_root": ""})
        for i, s in enumerate((DEAD_S, FULL, SHORT, CRACKED)):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-07",
                "shift": 1, "sequence": 483 + i, "state": "planned"})
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


def fqc_row(serial):
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in db.fqc_recent(cur, 50)]
    return next((r for r in rows if r["serial"] == serial), None)


def serial_row(serial):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, serial) or {})


def token_for(c, serial):
    return c.get("/api/fqc/lookup?serial=" + serial).get_json()["evidence_token"]


# --------------------------------------------------------------------------
# A is Pmax >= nameplate, with a clean EL
# --------------------------------------------------------------------------

@test("a module at or above its wattage with a clean EL is proposed a pass")
def t_proposes_pass():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + FULL).get_json()
    assert d["evidence"]["proposed"] == "pass", d["evidence"]
    assert "628.4" in d["evidence"]["why"], d["evidence"]["why"]


@test("a module below its wattage is proposed a rejection, however close")
def t_short_is_reject():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + SHORT).get_json()
    assert d["evidence"]["proposed"] == "reject", d["evidence"]
    # 620.5 of 625 is 99.3% - under the old 97% band this passed
    assert "below" in d["evidence"]["why"], d["evidence"]["why"]


@test("full power with a defective EL is still a rejection")
def t_cracked_is_reject():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + CRACKED).get_json()
    assert d["evidence"]["proposed"] == "reject", d["evidence"]
    assert "Cell Crack" in d["evidence"]["why"], d["evidence"]["why"]


@test("a pass is recorded as grade A and is ready to pack")
def t_pass_is_A():
    c = setup()
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    rec, s = fqc_row(FULL), serial_row(FULL)
    assert rec["outcome"] == "pass" and rec["grade"] == "A", rec
    assert s["grade"] == "A" and s["state"] == "graded", s


# --------------------------------------------------------------------------
# a pass cannot be overruled
# --------------------------------------------------------------------------

@test("a module below its wattage cannot be passed, reason or not")
def t_no_override_to_pass():
    c = setup()
    for body in ({"serial": SHORT, "outcome": "pass"},
                 {"serial": SHORT, "outcome": "pass",
                  "reason": "OV-CUST — customer accepts this condition"},
                 {"serial": SHORT, "outcome": "pass",
                  "reason": "OV-OTHER — other", "note": "looks fine to me"}):
        r = c.post("/api/fqc", json=body)
        assert r.status_code == 400, \
            "a module short of its wattage was passed with %r" % (body.get("reason"),)
        assert "Retest" in (r.get_json().get("why") or ""), r.get_json()
    assert fqc_row(SHORT) is None, "a refused pass left a record behind"
    assert serial_row(SHORT)["state"] == "planned"


@test("an EL-only rejection CAN be overruled - the verdict is a person's call")
def t_el_override_allowed():
    c = setup()
    # 631 W on a 625 W module: the power is there, only the EL objects, and
    # the EL verdict is the name of the folder somebody filed the image in
    r = c.post("/api/fqc", json={"serial": CRACKED, "outcome": "pass",
                                 "reason": "OV-IMAGE — image reviewed"})
    assert r.status_code == 200, r.get_json()
    rec = fqc_row(CRACKED)
    assert rec["outcome"] == "pass" and rec["grade"] == "A", rec
    assert rec["proposed"] == "reject", "the record keeps what was proposed"
    assert rec["reason"].startswith("OV-IMAGE"), rec


@test("overruling the EL still costs a reason")
def t_el_override_needs_reason():
    c = setup()
    r = c.post("/api/fqc", json={"serial": CRACKED, "outcome": "pass"})
    assert r.status_code == 400, "the EL was overruled silently"
    assert "reason" in (r.get_json().get("why") or "").lower(), r.get_json()
    assert fqc_row(CRACKED) is None


@test("a short reading is not overruled by a reason about the image")
def t_short_not_saved_by_el_reason():
    c = setup()
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "pass",
                                 "reason": "OV-IMAGE — image reviewed"})
    assert r.status_code == 400, \
        "a module below its wattage was passed on an EL argument"
    assert "Retest" in (r.get_json().get("why") or ""), r.get_json()


@test("a module the evidence would pass can still be rejected, with a reason")
def t_reject_against_proposal():
    c = setup()
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "reject"})
    assert r.status_code == 400, "rejecting against the proposal needs a reason"
    r = c.post("/api/fqc", json={
        "serial": FULL, "outcome": "reject",
        "reason": "OV-IMAGE — image reviewed, verdict wrong",
        "defect": "Cell Crack"})
    assert r.status_code == 200, r.get_json()
    assert fqc_row(FULL)["outcome"] == "reject"


@test("a module with no evidence cannot be passed on nothing - it needs a "
      "coded reason, and it is only ever a provisional pass")
def t_no_evidence_no_pass():
    c = setup(ss_path=os.path.join(TMP, "gone.csv"))
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert r.status_code == 400, \
        "a module was passed while the tester was unreachable"
    why = (r.get_json().get("why") or "").lower()
    assert "evidence" in why and "reason" in why, r.get_json()
    assert fqc_row(FULL) is None and serial_row(FULL)["state"] == "planned"


@test("but it can be rejected with the tester unreachable, provisionally")
def t_provisional_reject():
    c = setup(ss_path=os.path.join(TMP, "gone.csv"))
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "defect": "No Power"})
    assert r.status_code == 200, r.get_json()
    rec = fqc_row(SHORT)
    assert rec["mode"] == "provisional", rec["mode"]
    assert rec["ss_state"] == ev.NC, rec["ss_state"]


# --------------------------------------------------------------------------
# a reject has no grade until Quality gives it one
# --------------------------------------------------------------------------

@test("a rejected module has no grade and is not packable")
def t_reject_has_no_grade():
    c = setup()
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})
    rec, s = fqc_row(SHORT), serial_row(SHORT)
    assert rec["outcome"] == "reject" and rec["grade"] is None, rec
    assert s["state"] == "rejected", s["state"]
    assert s["grade"] is None, \
        "a rejected module carries a grade before Quality has called it"


@test("the EL verdict becomes the defect when the operator names none")
def t_defect_from_el():
    c = setup()
    c.post("/api/fqc", json={"serial": CRACKED, "outcome": "reject"})
    assert fqc_row(CRACKED)["defect"] == "Cell Crack", fqc_row(CRACKED)


@test("a named defect wins over the EL verdict")
def t_defect_named():
    c = setup()
    c.post("/api/fqc", json={"serial": CRACKED, "outcome": "reject",
                             "defect": "Bussing Miss"})
    assert fqc_row(CRACKED)["defect"] == "Bussing Miss"


@test("Quality turns a reject into GY or BGY, and only then is it packable")
def t_quality_grades():
    c = setup()
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})
    pending = c.get("/api/quality/pending").get_json()
    assert [p["serial"] for p in pending] == [SHORT], pending
    assert pending[0]["ss_pmax"] == 620.5, "Quality needs the SS reading"

    r = c.post("/api/quality", json={"serial": SHORT, "grade": "GY",
                                     "note": "edge chip, cosmetic"})
    assert r.status_code == 200, r.get_json()
    s = serial_row(SHORT)
    assert s["grade"] == "GY" and s["state"] == "graded", s
    assert fqc_row(SHORT)["quality_grade"] == "GY"
    assert not c.get("/api/quality/pending").get_json(), "still pending"


@test("Quality has to say why it chose that grade")
def t_quality_needs_reasoning():
    c = setup()
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})
    r = c.post("/api/quality", json={"serial": SHORT, "grade": "BGY"})
    assert r.status_code == 400, \
        "a grade was recorded with no reasoning behind it"
    assert "why" in (r.get_json().get("why") or "").lower(), r.get_json()
    assert serial_row(SHORT)["state"] == "rejected", "it was graded anyway"


@test("Quality can pass a module back to A when the image was the objection")
def t_quality_can_pass():
    c = setup()
    # full power, rejected on the EL verdict alone
    c.post("/api/fqc", json={"serial": CRACKED, "outcome": "reject"})
    r = c.post("/api/quality", json={"serial": CRACKED, "grade": "A",
                                     "note": "image shows a handling mark, "
                                             "not a cell crack"})
    assert r.status_code == 200, r.get_json()
    s = serial_row(CRACKED)
    assert s["grade"] == "A" and s["state"] == "graded", s


@test("but not one that measured short - A is a measurement, not a judgement")
def t_quality_cannot_pass_short():
    c = setup()
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})
    r = c.post("/api/quality", json={"serial": SHORT, "grade": "A",
                                     "note": "looks fine to me"})
    assert r.status_code == 400,         "a module below its wattage was made an A by review"
    assert "retest" in (r.get_json().get("why") or "").lower(), r.get_json()
    assert serial_row(SHORT)["state"] == "rejected"


@test("Quality cannot grade a module FQC passed")
def t_quality_only_rejects():
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    r = c.post("/api/quality", json={"serial": FULL, "grade": "GY"})
    assert r.status_code == 400, r.status_code


# --------------------------------------------------------------------------
# the measurement is the server's, never the client's
# --------------------------------------------------------------------------

@test("the server reads BAD for a module the tester never read")
def t_lookup_is_bad():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + DEAD_S).get_json()
    assert d["evidence"]["ss_state"] == ev.BAD, d["evidence"]["ss_state"]


@test("a BAD module cannot be judged, whatever the request body claims")
def t_bad_cannot_be_graded():
    c = setup()
    r = c.post("/api/fqc", json={
        "serial": DEAD_S, "outcome": "pass",
        "evidence": {"ss_state": "OK", "proposed": "pass", "pmax": 631.0}})
    assert r.status_code == 400, \
        "a body claiming OK got past the BAD block - the block is decorative"
    assert "BAD" in (r.get_json().get("why") or ""), r.get_json()
    assert fqc_row(DEAD_S) is None, "a refused decision left a record behind"
    assert serial_row(DEAD_S)["state"] == "planned"


@test("fqc_record holds what the server read, not what was posted")
def t_record_is_server_evidence():
    c = setup()
    r = c.post("/api/fqc", json={
        "serial": FULL, "outcome": "pass",
        "evidence": {"ss_state": "OK", "proposed": "pass", "pmax": 999.9,
                     "el": "Cell Crack", "el_state": "OK"}})
    assert r.status_code == 200, r.get_json()
    rec = fqc_row(FULL)
    assert rec["ss_pmax"] == 628.4, \
        "the posted Pmax was stored - the record claims a reading no tester " \
        "produced (got %r)" % rec["ss_pmax"]
    assert rec["el_verdict"] == "OK", \
        "the posted EL verdict was stored (got %r)" % rec["el_verdict"]


@test("the proposal recorded is the server's, not the body's")
def t_proposal_is_servers():
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass",
                             "evidence": {"proposed": "reject"}})
    assert fqc_row(FULL)["proposed"] == "pass", fqc_row(FULL)["proposed"]


@test("mode is a property of the evidence, not a field the client sets")
def t_mode_not_client_set():
    c = setup(ss_path=os.path.join(TMP, "gone.csv"))
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "mode": "confirmed"})
    assert r.status_code == 200, r.get_json()
    assert fqc_row(SHORT)["mode"] == "provisional", \
        "a client claimed its decision was confirmed while the tester was " \
        "unreachable"


# --------------------------------------------------------------------------
# the note, and the reason that needs one
# --------------------------------------------------------------------------

@test("a coded reason of OTHER is not a reason until the note says what")
def t_other_needs_note():
    c = setup()
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                                 "reason": "OV-OTHER — other"})
    assert r.status_code == 400, "OTHER was accepted with nothing written"
    assert "Note" in (r.get_json().get("why") or ""), r.get_json()

    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                                 "reason": "OV-OTHER — other",
                                 "note": "frame bent in handling"})
    assert r.status_code == 200, r.get_json()
    assert fqc_row(FULL)["note"] == "frame bent in handling"


@test("the note is optional for any other reason")
def t_note_optional():
    c = setup()
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                                 "reason": "OV-QUALITY — quality instruction"})
    assert r.status_code == 200, r.get_json()
    assert fqc_row(FULL)["note"] is None


# --------------------------------------------------------------------------
# the paths that must not regress
# --------------------------------------------------------------------------

@test("a serial that is not in the master is refused")
def t_unknown_serial():
    c = setup()
    r = c.post("/api/fqc", json={"serial": "ICON625R1299999999",
                                 "outcome": "pass"})
    assert r.status_code == 404, r.status_code


@test("the decision itself has to be a pass or a rejection")
def t_outcome_validated():
    c = setup()
    for bad in ("A", "GY", "EXCELLENT", ""):
        r = c.post("/api/fqc", json={"serial": FULL, "outcome": bad})
        assert r.status_code == 400, "%r was accepted as an outcome" % bad


@test("a reading that changed since the screen loaded refuses the decision")
def t_stale_screen_refused():
    c = setup()
    token = token_for(c, FULL)
    # retested while the operator was deciding, and it read differently
    write_ss(ROWS + [row(FULL, "2026-09-07 11:00:00", "626.1")])
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass",
                                 "evidence_token": token})
    assert r.status_code == 409, \
        "a stale screen decided against a reading that had already changed"
    assert "626.1" in (r.get_json().get("why") or ""), r.get_json()
    assert fqc_row(FULL) is None


@test("a screen still showing the current reading decides normally")
def t_fresh_screen_passes():
    c = setup()
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass",
                                 "evidence_token": token_for(c, FULL)})
    assert r.status_code == 200, r.get_json()


@test("the lookup carries what the panel shows beside the reading")
def t_panel_fields():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + FULL).get_json()
    e = d["evidence"]
    # these were all reaching the screen as "—"
    for k in ("voc", "isc", "ff"):
        assert e.get(k) is not None, "%s is missing from the lookup" % k
    assert e.get("wattage") == WATT, "the reading is shown against this"
    assert "instance" in d and "customer" in d, d.keys()


@test("the EL image is served for a serial that has one")
def t_el_image_served():
    c = setup()
    r = c.get("/api/el/image?serial=" + FULL)
    assert r.status_code == 200, \
        "the viewer had nothing to show for a module whose verdict was read"
    r = c.get("/api/el/image?serial=ICON625R1299999999")
    assert r.status_code == 404, "a missing image should say so, not error"


@test("how a batch was allocated is recorded and comes back")
def t_alloc_type():
    c = setup()
    assert APP._alloc_type("pre") == "pre"
    assert APP._alloc_type("post") == "post"
    assert APP._alloc_type("sideways") is None, \
        "only pre-shared and post-shared exist"
    assert APP._alloc_type(None) is None


@test("judging a module again supersedes the first decision, never doubles it")
def t_retest_supersedes():
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "reason": "OV-RETEST — retested, value differs",
                             "defect": "Cell Crack"})
    with store.conn() as (cx, cur):
        history = [dict(r) for r in db.fqc_history(cur, FULL)]
        live = [dict(r) for r in db.fqc_recent(cur, 50)]
    assert len(history) == 2, "the earlier decision should be kept as history"
    assert history[0]["superseded_by"] is None, "the newest is the live one"
    assert history[1]["superseded_by"] == history[0]["fqc_id"], \
        "the earlier one should point at what replaced it"
    assert [r["serial"] for r in live] == [FULL], \
        "a module judged twice is listed twice"


@test("a module judged twice is counted once")
def t_counted_once():
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "reason": "OV-RETEST — retested, value differs"})
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["inspected"] == 1, "counted %s inspections of one module" % t["inspected"]
    assert t["passed"] == 0 and t["rejected"] == 1, t


@test("the quality queue lists a module once, on its live decision")
def t_queue_not_doubled():
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "reason": "OV-IMAGE — image reviewed"})
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "reason": "OV-RETEST — retested, value differs",
                             "defect": "No Power"})
    q = c.get("/api/quality/pending").get_json()
    assert len(q) == 1, "one module appeared %d times in the queue" % len(q)
    assert q[0]["defect"] == "No Power", "the queue should show the live one"


@test("the module journey says what happened at FQC, not 'None'")
def t_journey_reads():
    c = setup()

    # Since 921e029 (13 Sep) the journey reads FQC as the outcome - Pass or
    # Reject - and Quality's call as a stage of its own, rather than one FQC
    # stage carrying the grade. This test was not updated with it; it
    # asserts that design now, and still its original point: a rejected
    # module never reads "None" anywhere, and Quality's grade shows once
    # given.
    def stage(s, name):
        d = c.get("/api/trace/serial/" + s).get_json()
        hits = [j for j in d["journey"] if j["stage"] == name]
        return hits[0] if hits else None

    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert stage(FULL, "FQC")["value"] == "Pass", stage(FULL, "FQC")
    assert stage(FULL, "Quality Decision") is None, "a pass has no quality step"

    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})
    assert stage(SHORT, "FQC")["value"] == "Reject", stage(SHORT, "FQC")
    q = stage(SHORT, "Quality Decision")
    assert q["value"] == "—" and q["done"] is False, q
    assert q["detail"] == ["awaiting a quality decision"], q
    for j in c.get("/api/trace/serial/" + SHORT).get_json()["journey"]:
        assert "None" not in str(j["value"]), j

    c.post("/api/quality", json={"serial": SHORT, "grade": "GY",
                                 "note": "edge chip, cosmetic"})
    q = stage(SHORT, "Quality Decision")
    assert q["value"] == "GY" and q["done"] is True, q

    assert stage(CRACKED, "FQC")["done"] is False, "never judged, but shown as done"


@test("a packed module is never silently re-judged where it stands")
def t_packed_not_rejudged():
    # Superseded by the duplicate-scan feature (see test_review.py): a
    # packed module graded again is no longer a flat 400. It is compared
    # against the record packing already acted on, and only a DISAGREEMENT
    # raises anything - but even then the box, the state and the grade are
    # left exactly as they were until a person resolves it.
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    b = c.post("/api/box/open", json={"grade": "A", "model": "ISEN625-G12R",
                                      "capacity": 36}).get_json()
    c.post("/api/box/%d/scan" % b["box_id"], json={"serial": FULL})
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                                 "reason": "OV-RETEST — retested"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json().get("duplicate_scan") is True, r.get_json()
    assert r.get_json().get("agree") is False, r.get_json()
    assert serial_row(FULL)["state"] == "packed", "its state moved anyway"
    assert serial_row(FULL)["grade"] == "A", "its grade moved anyway"


@test("a failed retest is not a change - the latest valid row still wins")
def t_failed_retest_is_not_stale():
    c = setup()
    token = token_for(c, FULL)
    write_ss(ROWS + [row(FULL, "2026-09-07 11:00:00", "0.0055", "nan", "-0.9")])
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass",
                                 "evidence_token": token})
    assert r.status_code == 200, \
        "a routine failed retest blocked a decision it should not have: %s" \
        % r.get_json()


# --------------------------------------------------------------------------
# the dashboard's numbers are the same filtered set everywhere they appear
#
# The screen offers From/To, Shift, Customer, Model and Result - and until
# now none of them reached the server. The filter bar overwrote a real,
# unfiltered total with a FABRICATED one from v4's own sample rows, which is
# worse than doing nothing: it looked like the screen had answered a
# question it had not. Every number below - the totals, the day/shift/model
# breakdown, and the defect breakdown - comes from ONE endpoint reading ONE
# filter, so a card and a table footer can never disagree about what they
# are both supposed to be counting.
# --------------------------------------------------------------------------

D1, D2 = "2026-09-05", "2026-09-08"


def dash_setup():
    """Six modules spread across two days, two shifts, two customers, two
    models and both outcomes - varied enough that a filter which does
    nothing cannot hide behind a coincidence."""
    store.wipe()
    with store.conn() as (cx, cur):
        rows = [
            # serial,                day,  shift, customer, model,          outcome, defect
            ("ICON625R1290510001", D1, 1, "STOCK",  "ISEN625-G12R", "pass",   None),
            ("ICON625R1290510002", D1, 1, "STOCK",  "ISEN625-G12R", "reject", "Cell Crack"),
            ("ICON625R1290510003", D1, 2, "SGMEDA", "ISEN625-G12R", "pass",   None),
            ("ICON630R1290510004", D2, 1, "SGMEDA", "ISEN630-G12R", "reject", "Cell Crack"),
            ("ICON630R1290510005", D2, 2, "STOCK",  "ISEN630-G12R", "reject", "Micro Crack"),
            ("ICON630R1290510006", D2, 2, "STOCK",  "ISEN630-G12R", "pass",   None),
        ]
        for i, (s, day, shift, cust, model, outcome, defect) in enumerate(rows):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": model,
                "wattage": 625, "customer": cust, "dcr": "DCR",
                "format_version": 2, "date_produced": day,
                "shift": shift, "sequence": 510 + i,
                "state": "graded" if outcome == "pass" else "rejected",
                "grade": "A" if outcome == "pass" else None})
            store.insert(cur, "fqc_record", {
                "serial": s, "outcome": outcome,
                "grade": "A" if outcome == "pass" else None,
                "mode": "confirmed", "decided_by": "operator",
                "at": day + " 10:00:00", "defect": defect})
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


@test("with no filter, the dashboard counts every live record")
def t_dash_no_filter():
    c = dash_setup()
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["inspected"] == 6, t
    assert t["passed"] == 3 and t["rejected"] == 3, t


@test("the date range only counts inspections that fall inside it")
def t_dash_date_range():
    c = dash_setup()
    t = c.get("/api/fqc/dashboard?from=%s&to=%s" % (D1, D1)).get_json()["totals"]
    assert t["inspected"] == 3, "day one has 3 records, got %s" % t["inspected"]
    t2 = c.get("/api/fqc/dashboard?from=%s&to=%s" % (D2, D2)).get_json()["totals"]
    assert t2["inspected"] == 3, t2


@test("the shift filter counts only that shift's records")
def t_dash_shift():
    c = dash_setup()
    t = c.get("/api/fqc/dashboard?shift=2").get_json()["totals"]
    assert t["inspected"] == 3, t
    assert t["passed"] == 2 and t["rejected"] == 1, t


@test("the customer filter counts only that customer's modules")
def t_dash_customer():
    c = dash_setup()
    t = c.get("/api/fqc/dashboard?customer=SGMEDA").get_json()["totals"]
    assert t["inspected"] == 2, t
    assert t["passed"] == 1 and t["rejected"] == 1, t


@test("the model filter counts only that model")
def t_dash_model():
    c = dash_setup()
    t = c.get("/api/fqc/dashboard?model=ISEN630-G12R").get_json()["totals"]
    assert t["inspected"] == 3, t


@test("result=pass and result=reject each count only their own outcome")
def t_dash_result():
    c = dash_setup()
    tp = c.get("/api/fqc/dashboard?result=pass").get_json()["totals"]
    assert tp["inspected"] == 3 and tp["rejected"] == 0, tp
    tr = c.get("/api/fqc/dashboard?result=reject").get_json()["totals"]
    assert tr["inspected"] == 3 and tr["passed"] == 0, tr


@test("filters combine, not just apply one at a time")
def t_dash_filters_combine():
    c = dash_setup()
    t = c.get("/api/fqc/dashboard?customer=STOCK&result=reject").get_json()["totals"]
    # STOCK rejects: 002 (day1) and 005 (day2) - SGMEDA's reject (004) excluded
    assert t["inspected"] == 2, t


@test("the shift/model breakdown rows obey the same filter as the totals")
def t_dash_rows_match_totals():
    c = dash_setup()
    d = c.get("/api/fqc/dashboard?shift=1").get_json()
    row_sum = sum(r["inspected"] for r in d["rows"])
    assert row_sum == d["totals"]["inspected"], \
        "the table (%d) and the total (%d) counted different things" % \
        (row_sum, d["totals"]["inspected"])


@test("top rejection reasons are real defects, grouped, under the same filter")
def t_dash_by_defect():
    c = dash_setup()
    d = c.get("/api/fqc/dashboard").get_json()
    by = {r["defect"]: r["qty"] for r in d["by_defect"]}
    assert by.get("Cell Crack") == 2, by
    assert by.get("Micro Crack") == 1, by

    filtered = c.get("/api/fqc/dashboard?customer=SGMEDA").get_json()
    by2 = {r["defect"]: r["qty"] for r in filtered["by_defect"]}
    assert by2 == {"Cell Crack": 1}, \
        "the defect breakdown ignored the customer filter: %s" % by2


@test("a filter matching nothing returns real zeros, not the last query's")
def t_dash_empty_result():
    c = dash_setup()
    t = c.get("/api/fqc/dashboard?customer=NOBODY").get_json()["totals"]
    assert (t.get("inspected") or 0) == 0, t


# --------------------------------------------------------------------------
# a decision made without the tester: held, then reconciled when it is back
#
#   NC (the Sun Simulator is unreachable) - the operator may pass or reject on
#   what is in front of them. A PASS is held (state 'hold', no grade, not
#   packable) in Hold & Deviation. When the reading is available: it agrees ->
#   confirmed, released, packable, automatically; it disagrees -> Needs Review
#   for Quality. Nothing is packed on a reading nobody has seen.
# --------------------------------------------------------------------------

GONE = os.path.join(TMP, "gone.csv")
REASON = "OV-EVIDENCE — evidence missing, judged visually"


def tester_back(rows=None):
    """The link returns: the file is readable again."""
    write_ss(rows if rows is not None else ROWS)
    with store.conn() as (cx, cur):
        db.set_config(cur, {
            "ss_csv_path": SS, "ss_a_csv_path": "", "ss_b_csv_path": "",
            "el_root": EL_ROOT, "el_a_root": "", "el_b_root": ""})


def live_records(serial):
    with store.conn() as (cx, cur):
        return [dict(r) for r in store.rows(
            cur, "SELECT * FROM fqc_record WHERE serial=%s ORDER BY fqc_id", (serial,))]


def hold(c):
    """The Hold list, read through its own Super Admin client: the caller's
    session may be a role that cannot view Hold (Quality, since Round 28's
    read gates), and this is scenery, not the thing under test."""
    reader = APP.app.test_client()
    AUTH.test_login(reader)
    return reader.get("/api/hold").get_json()


@test("with the tester unreachable a PASS is recorded provisionally and the "
      "module is HELD: no grade, state 'hold', on the Hold list, not packable")
def t_provisional_pass_is_held():
    c = setup(ss_path=GONE)
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass", "reason": REASON,
                                 "note": "Sun Simulator down; EL clean, seen on the line"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["held"] is True and r.get_json()["grade"] is None, r.get_json()
    s = serial_row(FULL)
    assert (s["state"], s["grade"]) == ("hold", None), s
    rec = fqc_row(FULL)
    assert (rec["outcome"], rec["mode"], rec["ss_state"], rec["grade"]) == \
        ("pass", "provisional", ev.NC, None), rec
    h = hold(c)
    assert [(x["serial"], x["status"], x["outcome"], x["waiting_for"]) for x in h["rows"]] == \
        [(FULL, "awaiting", "pass", "Sun Simulator")], h
    assert h["reconciled"] == {"confirmed": 0, "flagged": 0, "waiting": 1}, h["reconciled"]

    b = c.post("/api/box/open", json={"grade": "A", "model": "ISEN625-G12R",
                                      "capacity": 36, "customer": "STOCK"}).get_json()
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": FULL})
    assert r.status_code == 400 and "on hold" in r.get_json()["why"], r.get_json()


@test("the tester comes back and AGREES: the held pass is confirmed by itself - "
      "a new confirmed record supersedes the provisional one - and the module "
      "is graded A and can be packed")
def t_reconcile_agree():
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass", "reason": REASON})
    assert hold(c)["reconciled"]["waiting"] == 1
    assert serial_row(FULL)["state"] == "hold"

    tester_back()                                   # FULL reads 628.4, EL clean
    h = hold(c)
    assert h["reconciled"]["confirmed"] == 1 and h["rows"] == [], h
    s = serial_row(FULL)
    assert (s["state"], s["grade"]) == ("graded", "A"), s
    recs = live_records(FULL)
    assert [(r["mode"], r["superseded_by"] is not None) for r in recs] == \
        [("provisional", True), ("confirmed", False)], recs
    assert recs[1]["ss_pmax"] == 628.4 and recs[1]["decided_by"] == "system"

    b = c.post("/api/box/open", json={"grade": "A", "model": "ISEN625-G12R",
                                      "capacity": 36, "customer": "STOCK"}).get_json()
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": FULL})
    assert r.status_code == 200, r.get_json()
    assert hold(c)["confirmed_this_month"] == 1


@test("while the tester is still away nothing moves: the hold stays and "
      "nothing is confirmed or flagged")
def t_reconcile_waits():
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass", "reason": REASON})
    for _ in range(3):
        assert hold(c)["reconciled"] == {"confirmed": 0, "flagged": 0, "waiting": 1}
    assert serial_row(FULL)["state"] == "hold" and len(live_records(FULL)) == 1


@test("the tester comes back and DISAGREES: nothing picks a side - the module "
      "stays held, Needs Review gets an item for Quality, once")
def t_reconcile_disagree():
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "pass", "reason": REASON})
    tester_back()                                   # SHORT reads 620.5 < 625
    h = hold(c)
    assert h["reconciled"]["flagged"] == 1, h
    assert [(x["status"], x["outcome"], x["evidence_says"]) for x in h["rows"]] == \
        [("review", "pass", "reject")], h["rows"]
    assert serial_row(SHORT)["state"] == "hold", serial_row(SHORT)
    for _ in range(3):                              # opening the list again flags nothing more
        assert hold(c)["reconciled"]["flagged"] == 0
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                           "type='provisional_mismatch'")["n"]
    assert n == 1, "%d review items for one module" % n

    items = [i for i in c.get("/api/review").get_json() if i["type"] == "provisional_mismatch"]
    assert len(items) == 1 and items[0]["serial"] == SHORT, items
    assert items[0]["evidence"]["original"]["outcome"] == "pass"
    assert items[0]["evidence"]["evidence"]["outcome"] == "reject"

    # a module in Needs Review is not re-judged at the FQC desk
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})
    assert r.status_code == 400 and "Needs Review" in r.get_json()["why"], r.get_json()


@test("Quality resolves it: keeping the evidence rejects the module, keeping "
      "the decision passes it as A - each needs a reason, only Quality may, "
      "and the other record is superseded, not deleted")
def t_resolve_provisional_mismatch():
    for choice, want_state, want_grade in (("keep_evidence", "rejected", None),
                                           ("keep_decision", "graded", "A")):
        c = setup(ss_path=GONE)
        c.post("/api/fqc", json={"serial": SHORT, "outcome": "pass", "reason": REASON})
        tester_back()
        rid = [i for i in c.get("/api/review").get_json()
               if i["type"] == "provisional_mismatch"][0]["id"]
        body = {"type": "provisional_mismatch", "id": rid, "resolution": choice,
                "reason": "looked at the image and the flash report"}

        r = c.post("/api/review/resolve", json=body, headers=as_role(c, "FQC Operator"))
        assert r.status_code == 403, "an operator resolved a Quality decision"
        r = c.post("/api/review/resolve", json=dict(body, reason=""),
                   headers=as_role(c, "Quality"))
        assert r.status_code == 400, "resolved with no reason"
        r = c.post("/api/review/resolve", json=body, headers=as_role(c, "Quality"))
        assert r.status_code == 200, r.get_json()

        s = serial_row(SHORT)
        assert (s["state"], s["grade"]) == (want_state, want_grade), (choice, s)
        recs = live_records(SHORT)
        assert len(recs) == 2 and sum(1 for x in recs if x["superseded_by"] is None) == 1, \
            "one live decision expected, kept both rows: %s" % recs
        assert hold(c)["rows"] == [], "still on the Hold list after resolving"
        r = c.post("/api/review/resolve", json=body, headers=as_role(c, "Quality"))
        assert r.status_code == 400, "resolved twice"


@test("a provisional REJECT is confirmed by agreeing evidence - and sent to "
      "Needs Review if the evidence says it was a good module")
def t_provisional_reject_reconciles():
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})     # will agree
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject"})      # will not
    assert sorted(x["serial"] for x in hold(c)["rows"]) == sorted([SHORT, FULL])
    assert serial_row(SHORT)["state"] == serial_row(FULL)["state"] == "rejected"

    tester_back()
    h = hold(c)
    assert h["reconciled"] == {"confirmed": 1, "flagged": 1, "waiting": 0}, h["reconciled"]
    assert (serial_row(SHORT)["state"], fqc_row(SHORT)["mode"]) == ("rejected", "confirmed")
    assert serial_row(FULL)["state"] == "hold"
    assert [(x["serial"], x["status"]) for x in h["rows"]] == [(FULL, "review")]


@test("BAD (a probe fault) and NA (the tester is up and has nothing) can never "
      "be passed - they are quality signals - and a short reading still cannot, "
      "with or without the tester")
def t_pass_route_refusals():
    c = setup()                       # DEAD_S is BAD; NA = a serial the tester never saw
    r = c.post("/api/fqc", json={"serial": DEAD_S, "outcome": "pass", "reason": REASON})
    assert r.status_code == 400 and "BAD" in r.get_json()["why"], r.get_json()

    c = setup(ss_rows=[row(SHORT, "2026-09-07 10:05:00", "620.5")])     # FULL: reachable, absent
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass", "reason": REASON})
    assert r.status_code == 400 and "nothing for this serial" in r.get_json()["why"], r.get_json()
    assert serial_row(FULL)["state"] == "planned"


@test("the lookup says which way a pass could go: direct, EL-only override, "
      "provisional, or not at all - and why not")
def t_lookup_pass_route():
    c = setup()
    got = {s: c.get("/api/fqc/lookup?serial=" + s).get_json() for s in (FULL, SHORT, CRACKED)}
    assert got[FULL]["pass_route"] == "direct", got[FULL]["pass_route"]
    assert got[CRACKED]["pass_route"] == "el_only", got[CRACKED]["pass_route"]
    assert got[SHORT]["pass_route"] is None and "Retest" in got[SHORT]["pass_why"], got[SHORT]
    c = setup(ss_path=GONE)
    away = c.get("/api/fqc/lookup?serial=" + FULL).get_json()
    assert away["pass_route"] == "provisional" and "Hold & Deviation" in away["pass_why"], away


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
