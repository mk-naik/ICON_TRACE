"""
ICON TRACE - the defect an FQC decision carries must be visible everywhere a
decision is shown.

    python test_defect_readers.py

Stage 3 moved a decision's defects into fqc_defect (the EL's, and the
operator's beside it) and stopped writing fqc_record.defect. Five screens went
on reading only that column:

    the dashboard's rejection reasons and its drill-down,
    Quality's row and popup on Needs Review,
    Hold & Deviation,
    the module journey on Search & Trace.

Every rejection since then read "no defect recorded" on the dashboard, and
Quality decided GY or BGY without being shown what FQC had found. The tests
that were meant to catch it seeded the dead column by hand, so they passed.

These go through the REAL write path - POST /api/fqc, db.record_fqc - and read
the answers back from the endpoints a person's screen reads.
"""

import csv, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_defread_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


REJ_EL = "ICON625R1290220501"      # rejected; the EL says Cell Crack
REJ_OP = "ICON625R1290220502"      # rejected; EL clean, the OPERATOR names Cell Crack
PASS_BOTH = "ICON625R1290220503"   # passed despite a Burning EL, plus an operator defect
REJ_TWO = "ICON625R1290220504"     # EL says Burning AND the operator adds Frame Dent
REJ_NC = "ICON625R1290220505"      # rejected with the tester unreachable (provisional)
SERIALS = (REJ_EL, REJ_OP, PASS_BOTH, REJ_TWO, REJ_NC)

SS = os.path.join(TMP, "ss.csv")
EL = os.path.join(TMP, "el")


def row(sid, pmax):
    return ["2026-09-07 10:00:00", sid, pmax, "12.1", "48.9", "11.8", "52.5",
            "96.1", "0.41", "0.4", "210.0", "23.1", "25.0", "25.0", "1000.0"]


def setup(ss_reachable=True):
    store.wipe()
    shutil.rmtree(EL, ignore_errors=True)
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([row(s, "630.0") for s in SERIALS])
    for verdict, ss in (("Cell Crack", [REJ_EL]), ("OK", [REJ_OP]),
                        ("Burning", [PASS_BOTH, REJ_TWO]),
                        ("Cell Crack", [REJ_NC])):
        os.makedirs(os.path.join(EL, verdict), exist_ok=True)
        for s in ss:
            open(os.path.join(EL, verdict, s + ".jpg"), "w").close()
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS if ss_reachable else os.path.join(TMP, "gone.csv"),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_root": EL, "el_a_root": "", "el_b_root": ""})
        for i, s in enumerate(SERIALS):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": 625, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-07",
                "shift": 1, "sequence": 501 + i, "state": "planned"})
    c = APP.app.test_client()
    AUTH.test_login(c)                      # Super Admin
    return c


def grade(c, serial, outcome, **kw):
    d = c.get("/api/fqc/lookup?serial=" + serial).get_json()
    body = {"serial": serial, "outcome": outcome, "evidence_token": d["evidence_token"]}
    body.update(kw)
    r = c.post("/api/fqc", json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def make_decisions(c):
    grade(c, REJ_EL, "reject")                                    # defect comes from the EL
    grade(c, REJ_OP, "reject", defect="Cell Crack")               # EL clean: the operator's
    grade(c, PASS_BOTH, "pass", defect="Backsheet Scratch")       # passed despite Burning
    grade(c, REJ_TWO, "reject", defect="Frame Dent")              # EL Burning + operator's


def reasons(c, q=""):
    d = c.get("/api/fqc/dashboard" + q).get_json()
    return {r["defect"]: r["qty"] for r in d["by_defect"]}


@test("the dashboard's rejection reasons count what the decisions really carry "
      "- the EL's defect and the operator's, each once per rejection - not "
      "'no defect recorded'")
def t_dashboard_reasons():
    c = setup()
    make_decisions(c)
    got = reasons(c)
    assert got.get("Cell Crack") == 2, got           # REJ_EL (EL) + REJ_OP (operator)
    assert got.get("Burning") == 1 and got.get("Frame Dent") == 1, got   # REJ_TWO under both
    assert "(no defect recorded)" not in got, "every rejection here has a defect: %s" % got
    assert sum(got.values()) == 4, "the pass is not a rejection: %s" % got


@test("a rejection that really has no defect is still counted as such - and a "
      "decision from BEFORE Stage 3 (its old column) still reads as it did, "
      "with 'low eff' and 'Low Eff' one defect")
def t_legacy_and_none():
    c = setup()
    make_decisions(c)
    with store.conn() as (cx, cur):
        for i, d in enumerate(("low eff", "Low Eff", None)):
            s = "ICON625R12902209%02d" % i
            store.insert(cur, "serial", {"serial": s, "build_instance": 1,
                "model": "ISEN625-G12R", "wattage": 625, "customer": "STOCK",
                "dcr": "DCR", "format_version": 2, "date_produced": "2026-09-07",
                "shift": 1, "sequence": 900 + i, "state": "rejected"})
            store.insert(cur, "fqc_record", {"serial": s, "outcome": "reject",
                "mode": "confirmed", "decided_by": "old", "at": db.clock.now().isoformat(timespec="seconds"),
                "defect": d})
    got = reasons(c)
    assert got.get("Low Eff") == 2 or got.get("low eff") == 2, got
    assert len([k for k in got if k.lower() == "low eff"]) == 1, "one defect, two spellings: %s" % got
    assert got.get("(no defect recorded)") == 1, got


@test("the drill-down lists exactly the modules the reasons table counted, "
      "each carrying the defect that was asked for - and '(no defect "
      "recorded)' finds only those with none")
def t_drilldown():
    c = setup()
    make_decisions(c)
    rows = c.get("/api/fqc/dashboard/modules?remark=Cell%20Crack&result=reject").get_json()
    assert sorted(r["serial"] for r in rows) == sorted([REJ_EL, REJ_OP]), rows
    assert all(r["defect"] == "Cell Crack" for r in rows), rows
    rows = c.get("/api/fqc/dashboard/modules?remark=Frame%20Dent").get_json()
    assert [r["serial"] for r in rows] == [REJ_TWO] and rows[0]["defect"] == "Frame Dent", rows
    rows = c.get("/api/fqc/dashboard/modules?remark=Burning&result=reject").get_json()
    assert [r["serial"] for r in rows] == [REJ_TWO], rows
    rows = c.get("/api/fqc/dashboard/modules?remark=" + "%28no%20defect%20recorded%29").get_json()
    assert rows == [], "every decision here has a defect: %s" % rows
    # with no remark asked for, each module carries its FIRST defect (the EL's)
    every = {r["serial"]: r["defect"] for r in c.get("/api/fqc/dashboard/modules").get_json()}
    assert every[REJ_TWO] == "Burning" and every[REJ_OP] == "Cell Crack", every


@test("Quality is shown what FQC found: its row on Needs Review names the "
      "defect(s), and the popup's evidence carries them")
def t_quality_sees_defect():
    c = setup()
    make_decisions(c)
    q = APP.app.test_client()
    AUTH.test_login(q, role="Quality", login_id="test.quality", name="Quality")
    items = {i["serial"]: i for i in q.get("/api/review").get_json()
             if i["type"] == "quality_grade"}
    assert items[REJ_EL]["detail"] == "Rejected — Cell Crack", items[REJ_EL]["detail"]
    assert items[REJ_TWO]["detail"] == "Rejected — Burning, Frame Dent", items[REJ_TWO]["detail"]
    assert items[REJ_OP]["evidence"]["original"]["defect"] == "Cell Crack", items[REJ_OP]
    assert items[REJ_TWO]["evidence"]["original"]["defect"] == "Burning, Frame Dent"


@test("Hold & Deviation names the defect of a provisional decision")
def t_hold_shows_defect():
    c = setup(ss_reachable=False)                # the tester is unreachable: provisional
    grade(c, REJ_NC, "reject")                   # the EL alone says Cell Crack
    rows = c.get("/api/hold").get_json()["rows"]
    mine = [r for r in rows if r["serial"] == REJ_NC]
    assert mine and mine[0]["defect"] == "Cell Crack", rows


@test("the module journey on Search & Trace shows the defect of a rejection - "
      "and of a PASS, so 'passed despite Burning' can be seen on the module")
def t_journey_shows_defect():
    c = setup()
    make_decisions(c)
    j = c.get("/api/trace/serial/" + REJ_TWO).get_json()
    fqc = [s for s in j["journey"] if s["stage"] == "FQC"][0]
    assert fqc["value"] == "Reject" and "Burning, Frame Dent" in fqc["detail"], fqc
    j = c.get("/api/trace/serial/" + PASS_BOTH).get_json()
    fqc = [s for s in j["journey"] if s["stage"] == "FQC"][0]
    assert fqc["value"] == "Pass" and "Burning, Backsheet Scratch" in fqc["detail"], fqc


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
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
