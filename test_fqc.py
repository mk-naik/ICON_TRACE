"""
ICON TRACE - tests for what an FQC decision is allowed to contain.

    python test_fqc.py

THE RULES THIS FILE DEFENDS

  1. The operator supplies the JUDGEMENT - pass or reject. The MEASUREMENT is
     read from the tester by the server and is never accepted from the
     browser. A record has to say what the Sun Simulator actually reported;
     if the request body can supply it, the BAD block is decorative and
     fqc_record can hold a Pmax no tester ever produced.

  2. FQC does not grade. It records PASS or REJECT. A pass is grade A.

  3. THE SS WATTAGE FLOOR IS THE ONLY THING PASS TURNS ON. A module below
     nameplate is never passable - Discard it back to the tester, or Reject
     it. EL is advisory: it can never block a pass, and it can never force a
     rejection either (Stage 3 removed the propose/confirm-overrule
     mechanism this project used to run on - SS sees power, EL sees two
     strings, and neither sees a frame dent, a corner chip, or whether a
     cell crack is minor or major).

  4. A REJECTION NEEDS A DEFECT. The EL's own verdict satisfies it when EL
     read something other than clean; if EL read OK, an operator defect is
     compulsory. A PASS's defect is always optional - and the EL verdict, if
     there is one, attaches automatically and cannot be left off the record
     just because the module passed.

  5. Operators cannot mint new defect names - only a code from defect_master
     is ever recorded. "Other" (+ a compulsory note) is the escape hatch for
     anything not on the list.

  6. A reject has NO GRADE until Quality calls it GY or BGY, and no grade is
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


def defect_codes(fqc_id, source=None):
    with store.conn() as (cx, cur):
        return [r["defect_code"] for r in db.fqc_defects_for(cur, fqc_id, source)]


def serial_row(serial):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, serial) or {})


def token_for(c, serial):
    return c.get("/api/fqc/lookup?serial=" + serial).get_json()["evidence_token"]


# --------------------------------------------------------------------------
# the SS wattage floor - the only thing a pass turns on
# --------------------------------------------------------------------------

@test("a module at or above its wattage can be passed directly")
def t_direct_pass_route():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + FULL).get_json()
    assert d["pass_route"] == "direct", d

    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    rec, s = fqc_row(FULL), serial_row(FULL)
    assert rec["outcome"] == "pass" and rec["grade"] == "A", rec
    assert s["grade"] == "A" and s["state"] == "graded", s


@test("a module below its wattage cannot be passed - Discard or Reject, never Pass")
def t_no_override_to_pass():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + SHORT).get_json()
    assert d["pass_route"] is None and "Retest" in d["pass_why"], d

    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "pass"})
    assert r.status_code == 400, "a module short of its wattage was passed"
    assert "Retest" in (r.get_json().get("why") or ""), r.get_json()
    assert fqc_row(SHORT) is None, "a refused pass left a record behind"
    assert serial_row(SHORT)["state"] == "planned"


@test("full power with a defective EL passes directly, no reason needed - and "
      "the EL defect still attaches to the record")
def t_el_never_blocks_pass():
    c = setup()
    d = c.get("/api/fqc/lookup?serial=" + CRACKED).get_json()
    assert d["pass_route"] == "direct", \
        "EL gated the pass - it is advisory only now: %s" % d

    r = c.post("/api/fqc", json={"serial": CRACKED, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    rec = fqc_row(CRACKED)
    assert rec["outcome"] == "pass" and rec["grade"] == "A", rec
    assert rec["defect_el_raw"] == "Cell Crack", rec
    codes = defect_codes(rec["fqc_id"])
    assert codes == ["DF-CELLCRACK"], \
        "a passed module lost its EL defect: %s" % codes


@test("a module the evidence would pass can still be rejected - a person "
      "may see what the evidence does not, no reason required")
def t_reject_against_evidence():
    c = setup()
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                                 "defect": "Cell Crack"})
    assert r.status_code == 200, r.get_json()
    assert fqc_row(FULL)["outcome"] == "reject"


@test("with no evidence, a pass is recorded provisionally and held - no "
      "reason needed, EL is not part of this either")
def t_no_evidence_pass_is_provisional():
    c = setup(ss_path=os.path.join(TMP, "gone.csv"))
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["held"] is True, r.get_json()
    assert serial_row(FULL)["state"] == "hold"


@test("but a BAD or NA reading is not passable at all, whatever else is true")
def t_bad_na_never_passable():
    c = setup()
    r = c.post("/api/fqc", json={"serial": DEAD_S, "outcome": "pass"})
    assert r.status_code == 400 and "BAD" in r.get_json()["why"], r.get_json()

    c = setup(ss_rows=[row(SHORT, "2026-09-07 10:05:00", "620.5")])  # FULL absent
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert r.status_code == 400 and "nothing for this serial" in r.get_json()["why"], \
        r.get_json()
    assert serial_row(FULL)["state"] == "planned"


# --------------------------------------------------------------------------
# a reject needs a defect; a pass's is always optional
# --------------------------------------------------------------------------

@test("a rejection with a clean EL and no named defect is refused")
def t_reject_needs_defect():
    c = setup()
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject"})
    assert r.status_code == 400, "a reject with nothing to blame it on was accepted"
    assert "defect" in (r.get_json().get("why") or "").lower(), r.get_json()
    assert fqc_row(SHORT) is None


@test("a rejected module has no grade and is not packable, once it has a defect")
def t_reject_has_no_grade():
    c = setup()
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "defect": "No Power"})
    assert r.status_code == 200, r.get_json()
    rec, s = fqc_row(SHORT), serial_row(SHORT)
    assert rec["outcome"] == "reject" and rec["grade"] is None, rec
    assert s["state"] == "rejected", s["state"]
    assert s["grade"] is None, \
        "a rejected module carries a grade before Quality has called it"


@test("the EL verdict becomes the defect when the operator names none")
def t_defect_from_el():
    c = setup()
    c.post("/api/fqc", json={"serial": CRACKED, "outcome": "reject"})
    rec = fqc_row(CRACKED)
    assert rec["defects"] == "Cell Crack", rec
    assert defect_codes(rec["fqc_id"], "el") == ["DF-CELLCRACK"]


@test("an EL folder the defect list does not know files no defect, so it cannot "
      "stand in for one: the rejection is refused until a defect is picked")
def t_el_folder_not_on_list_needs_a_defect():
    odd = "ICON625R1290220487"                    # filed under 'Corner Chip'
    c = setup(ss_rows=ROWS + [row(odd, "2026-09-07 10:15:00", "630.0")])
    folder = os.path.join(EL_ROOT, "Corner Chip")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, odd + ".jpg"), "w").close()
    try:
        with store.conn() as (cx, cur):
            store.insert(cur, "serial", {
                "serial": odd, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-07",
                "shift": 1, "sequence": 487, "state": "planned"})
        r = c.post("/api/fqc", json={"serial": odd, "outcome": "reject"})
        assert r.status_code == 400, "rejected with no defect on file: %s" % r.get_json()
        assert "Corner Chip" in r.get_json()["why"], r.get_json()
        assert fqc_row(odd) is None
        r = c.post("/api/fqc", json={"serial": odd, "outcome": "reject",
                                     "defect": "Corner Chip"})
        assert r.status_code == 200, r.get_json()
        assert defect_codes(fqc_row(odd)["fqc_id"]) == ["DF-CORNERCHIP"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@test("a named defect is recorded alongside the EL's, not instead of it")
def t_defect_named_plus_el():
    c = setup()
    c.post("/api/fqc", json={"serial": CRACKED, "outcome": "reject",
                             "defect": "Bussing Miss"})
    rec = fqc_row(CRACKED)
    assert defect_codes(rec["fqc_id"], "el") == ["DF-CELLCRACK"]
    assert defect_codes(rec["fqc_id"], "fqc") == ["DF-BUSSINGMISS"]


@test("an operator defect equal to the EL's own is not attached twice")
def t_defect_same_as_el_not_doubled():
    c = setup()
    c.post("/api/fqc", json={"serial": CRACKED, "outcome": "reject",
                             "defect": "Cell Crack"})
    rec = fqc_row(CRACKED)
    assert defect_codes(rec["fqc_id"]) == ["DF-CELLCRACK"], \
        "the same code was attached twice"


@test("operators cannot mint new defect names")
def t_defect_must_be_on_list():
    c = setup()
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "defect": "Buring"})
    assert r.status_code == 400, "free text was accepted as a defect"
    assert "not on the defect list" in (r.get_json().get("why") or ""), r.get_json()
    assert fqc_row(SHORT) is None


@test("\"Other\" is not a defect on its own - the note is compulsory")
def t_other_needs_note():
    c = setup()
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "defect": "Other"})
    assert r.status_code == 400, "Other was accepted with nothing written"
    assert "Note" in (r.get_json().get("why") or ""), r.get_json()

    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "defect": "Other", "note": "frame bent"})
    assert r.status_code == 200, r.get_json()
    assert fqc_row(SHORT)["note"] == "frame bent"


@test("a pass's defect is optional even with a clean EL")
def t_pass_defect_optional():
    c = setup()
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    rec = fqc_row(FULL)
    assert rec["defects"] is None, rec


# --------------------------------------------------------------------------
# a reject has no grade until Quality gives it one
# --------------------------------------------------------------------------

@test("Quality turns a reject into GY or BGY, and only then is it packable")
def t_quality_grades():
    c = setup()
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                             "defect": "No Power"})
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
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                             "defect": "No Power"})
    r = c.post("/api/quality", json={"serial": SHORT, "grade": "BGY"})
    assert r.status_code == 400, \
        "a grade was recorded with no reasoning behind it"
    assert "why" in (r.get_json().get("why") or "").lower(), r.get_json()
    assert serial_row(SHORT)["state"] == "rejected", "it was graded anyway"


@test("Quality can return a reject to A - grade A is legitimate off review")
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
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                             "defect": "No Power"})
    r = c.post("/api/quality", json={"serial": SHORT, "grade": "A",
                                     "note": "looks fine to me"})
    assert r.status_code == 400, "a module below its wattage was made an A by review"
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
        "evidence": {"ss_state": "OK", "pmax": 631.0}})
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
        "evidence": {"ss_state": "OK", "pmax": 999.9,
                     "el": "Cell Crack", "el_state": "OK"}})
    assert r.status_code == 200, r.get_json()
    rec = fqc_row(FULL)
    assert rec["ss_pmax"] == 628.4, \
        "the posted Pmax was stored - the record claims a reading no tester " \
        "produced (got %r)" % rec["ss_pmax"]
    assert rec["el_verdict"] == "OK", \
        "the posted EL verdict was stored (got %r)" % rec["el_verdict"]


@test("mode is a property of the evidence, not a field the client sets")
def t_mode_not_client_set():
    c = setup(ss_path=os.path.join(TMP, "gone.csv"))
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "defect": "No Power", "mode": "confirmed"})
    assert r.status_code == 200, r.get_json()
    assert fqc_row(SHORT)["mode"] == "provisional", \
        "a client claimed its decision was confirmed while the tester was " \
        "unreachable"


@test("every record is stamped with the ruleset it was judged under, and its "
      "place in the serial's own retest history")
def t_rule_version_and_test_seq():
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "defect": "Cell Crack"})
    with store.conn() as (cx, cur):
        history = [dict(r) for r in db.fqc_history(cur, FULL)]
    history.sort(key=lambda r: r["fqc_id"])
    assert [h["test_seq"] for h in history] == [1, 2], history
    assert all(h["rule_version"] for h in history), \
        "a record with no rule_version at all"


# --------------------------------------------------------------------------
# the paths that must not regress
# --------------------------------------------------------------------------

@test("a serial that is not in the master AND that neither tester has seen is "
      "refused (one the testers HAVE seen can be graded ahead of Planning - "
      "test_fqc_unplanned.py)")
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


@test("the unified defect list is served for the screen's picker")
def t_defects_endpoint():
    c = setup()
    d = c.get("/api/fqc/defects").get_json()
    codes = {x["code"] for x in d["defects"]}
    assert "DF-CELLCRACK" in codes and "DF-LOWEFF" in codes and "DF-CROSS" in codes, \
        "the EL share's own vocabulary is missing from the served list: %s" % codes
    assert all(x["label"] != "OK" for x in d["defects"]), \
        "OK is the clean verdict, not a defect"


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
                             "defect": "Cell Crack"})
    t = c.get("/api/fqc/dashboard").get_json()["totals"]
    assert t["inspected"] == 1, "counted %s inspections of one module" % t["inspected"]
    assert t["passed"] == 0 and t["rejected"] == 1, t


@test("the quality queue lists a module once, on its live decision")
def t_queue_not_doubled():
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "defect": "Cell Crack"})
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "defect": "No Power"})
    q = c.get("/api/quality/pending").get_json()
    assert len(q) == 1, "one module appeared %d times in the queue" % len(q)


@test("the module journey says what happened at FQC, not 'None'")
def t_journey_reads():
    c = setup()

    def stage(s, name):
        d = c.get("/api/trace/serial/" + s).get_json()
        hits = [j for j in d["journey"] if j["stage"] == name]
        return hits[0] if hits else None

    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    # Mukesh, 4 Oct: a confirmed pass shows its band, a reject shows none
    assert stage(FULL, "FQC")["value"] == "Pass · A", stage(FULL, "FQC")
    assert stage(FULL, "Quality Decision") is None, "a pass has no quality step"

    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                             "defect": "No Power"})
    assert stage(SHORT, "FQC")["value"] == "Reject", stage(SHORT, "FQC")
    q = stage(SHORT, "Quality Decision")
    assert q["value"] == "—" and q["done"] is False, q
    assert q["detail"] == ["awaiting a quality decision"], q
    for j in c.get("/api/trace/serial/" + SHORT).get_json()["journey"]:
        assert "None" not in str(j["value"]), j

    # Quality decides later than FQC did: the step carries QUALITY's time
    with store.conn() as (cx, cur):
        cur.execute("UPDATE fqc_record SET at='2026-09-07T10:00:00' WHERE serial=%s",
                    (SHORT,))
    c.post("/api/quality", json={"serial": SHORT, "grade": "GY",
                                 "note": "edge chip, cosmetic"})
    q = stage(SHORT, "Quality Decision")
    assert q["value"] == "GY" and q["done"] is True, q
    with store.conn() as (cx, cur):
        qa = store.one(cur, "SELECT quality_at FROM fqc_record WHERE serial=%s "
                            "AND quality_grade IS NOT NULL", (SHORT,))["quality_at"]
    assert qa and q["tag"] == qa and q["tag"] != "2026-09-07T10:00:00", \
        "the Quality Decision step shows FQC's time, not Quality's: %s" % q

    assert stage(CRACKED, "FQC")["done"] is False, "never judged, but shown as done"


@test("a packed module is never silently re-judged where it stands")
def t_packed_not_rejudged():
    # A packed module graded again is not a flat 400: it is compared against
    # the record packing already acted on, and only a DISAGREEMENT raises
    # anything - but even then the box, the state and the grade are left
    # exactly as they were until a person resolves it.
    c = setup()
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    b = c.post("/api/box/open", json={"grade": "A", "model": "ISEN625-G12R",
                                      "capacity": 36}).get_json()
    c.post("/api/box/%d/scan" % b["box_id"], json={"serial": FULL})
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                                 "defect": "Cell Crack"})
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
            # The dashboard's shift is the one FQC inspected in, read from
            # the time (A 06-14, B 14-22) - so each row is inspected inside
            # the shift it is meant to count under.
            store.insert(cur, "fqc_record", {
                "serial": s, "outcome": outcome,
                "grade": "A" if outcome == "pass" else None,
                "mode": "confirmed", "decided_by": "operator",
                "at": day + (" 10:00:00" if shift == 1 else " 15:00:00"),
                "defect": defect})
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
#   packable) in Hold & Deviation. When the reading is available: only the
#   wattage floor decides whether it agrees (EL is not part of this) -> it
#   does -> confirmed, released, packable, automatically; it does not ->
#   Needs Review for Quality. Nothing is packed on a reading nobody has seen.
# --------------------------------------------------------------------------

GONE = os.path.join(TMP, "gone.csv")


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
    r = c.post("/api/fqc", json={"serial": FULL, "outcome": "pass",
                                 "note": "Sun Simulator down; seen on the line"})
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
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    assert hold(c)["reconciled"]["waiting"] == 1
    assert serial_row(FULL)["state"] == "hold"

    tester_back()                                   # FULL reads 628.4
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


@test("a held pass is counted on the shift it was DECIDED, not the one in which "
      "the reading turned up - decided 23:40 (C shift), confirmed next morning")
def t_reconcile_keeps_decision_time():
    import datetime, icon_clock
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    day_before = (icon_clock.now() - datetime.timedelta(days=2)).date()
    decided = "%sT23:40:00" % day_before.isoformat()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE fqc_record SET at=%s WHERE serial=%s", (decided, FULL))
    tester_back()
    assert hold(c)["reconciled"]["confirmed"] == 1
    recs = live_records(FULL)
    assert recs[-1]["at"] == decided and recs[-1]["decided_by"] == "system", recs
    assert recs[0]["superseded_at"] != decided, "superseded_at must say when it was superseded"
    q = "/api/fqc/dashboard?from=%s&to=%s&shift=C" % (day_before, day_before)
    assert c.get(q).get_json()["totals"]["inspected"] == 1, c.get(q).get_json()["totals"]


@test("while the tester is still away nothing moves: the hold stays and "
      "nothing is confirmed or flagged")
def t_reconcile_waits():
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": FULL, "outcome": "pass"})
    for _ in range(3):
        assert hold(c)["reconciled"] == {"confirmed": 0, "flagged": 0, "waiting": 1}
    assert serial_row(FULL)["state"] == "hold" and len(live_records(FULL)) == 1


@test("the tester comes back and DISAGREES on the wattage: nothing picks a "
      "side - the module stays held, Needs Review gets an item for Quality, "
      "once")
def t_reconcile_disagree():
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "pass"})
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

    # while Quality decides, the decision made is the ONE live record: the
    # reading that disagreed is held beside it, not counted as a second
    # inspection on the FQC Dashboard
    assert sum(1 for x in live_records(SHORT) if x["superseded_by"] is None) == 1
    assert c.get("/api/fqc/dashboard").get_json()["totals"]["inspected"] == 1

    items = [i for i in c.get("/api/review").get_json() if i["type"] == "provisional_mismatch"]
    assert len(items) == 1 and items[0]["serial"] == SHORT, items
    assert items[0]["evidence"]["original"]["outcome"] == "pass"
    assert items[0]["evidence"]["evidence"]["outcome"] == "reject"

    # a module in Needs Review is not re-judged at the FQC desk
    r = c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                                 "defect": "No Power"})
    assert r.status_code == 400 and "Needs Review" in r.get_json()["why"], r.get_json()


@test("Quality resolves it: keeping the evidence rejects the module, keeping "
      "the decision passes it as A - each needs a reason, only Quality may, "
      "and the other record is superseded, not deleted")
def t_resolve_provisional_mismatch():
    for choice, want_state, want_grade in (("keep_evidence", "rejected", None),
                                           ("keep_decision", "graded", "A")):
        c = setup(ss_path=GONE)
        c.post("/api/fqc", json={"serial": SHORT, "outcome": "pass"})
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


@test("a reject decided WITH the Sun Simulator reading - only the EL image "
      "missing - waits for nothing: not on Hold, never flagged, it stays in "
      "Quality's queue")
def t_reject_with_reading_is_not_reconciled():
    noel = "ICON625R1290220488"                   # 630 W read, no EL image at all
    c = setup(ss_rows=ROWS + [row(noel, "2026-09-07 10:20:00", "630.0")])
    with store.conn() as (cx, cur):
        store.insert(cur, "serial", {
            "serial": noel, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
            "format_version": 2, "date_produced": "2026-09-07",
            "shift": 1, "sequence": 488, "state": "planned"})
    r = c.post("/api/fqc", json={"serial": noel, "outcome": "reject",
                                 "defect": "Frame Dent"})
    assert r.status_code == 200 and r.get_json()["mode"] == "provisional", r.get_json()
    h = hold(c)
    assert h["rows"] == [] and h["reconciled"]["flagged"] == 0, h
    assert serial_row(noel)["state"] == "rejected", serial_row(noel)
    q = [i["serial"] for i in c.get("/api/review").get_json() if i["type"] == "quality_grade"]
    assert noel in q, q


@test("a provisional REJECT is confirmed by agreeing evidence - and sent to "
      "Needs Review if the evidence would now make it a pass")
def t_provisional_reject_reconciles():
    c = setup(ss_path=GONE)
    c.post("/api/fqc", json={"serial": SHORT, "outcome": "reject",
                             "defect": "No Power"})    # will agree: still short
    c.post("/api/fqc", json={"serial": FULL, "outcome": "reject",
                             "defect": "Cell Crack"})   # will not: makes wattage
    assert sorted(x["serial"] for x in hold(c)["rows"]) == sorted([SHORT, FULL])
    assert serial_row(SHORT)["state"] == serial_row(FULL)["state"] == "rejected"

    tester_back()
    h = hold(c)
    assert h["reconciled"] == {"confirmed": 1, "flagged": 1, "waiting": 0}, h["reconciled"]
    assert (serial_row(SHORT)["state"], fqc_row(SHORT)["mode"]) == ("rejected", "confirmed")
    assert serial_row(FULL)["state"] == "hold"
    assert [(x["serial"], x["status"]) for x in h["rows"]] == [(FULL, "review")]


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
