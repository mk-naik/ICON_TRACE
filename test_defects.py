"""
ICON TRACE - tests for the unified defect vocabulary (icon_defects.py,
defect_master, defect_folder_map).

    python test_defects.py

THE RULES THIS FILE DEFENDS

  1. defect_master is seeded once, from icon_defects.py, into an empty
     database - and never re-seeded once a row exists.

  2. A folder name is matched on its DEFECT_CODE, not its raw text - "low
     eff" and " low eff" (a leading space, both filed by production) are
     the same code, and so are any other whitespace or case differences.

  3. 'OK' is the clean verdict, not a defect, and never resolves to a code.
     An unknown folder name resolves to None, not a guess.

Each test names the rule it defends, so a failure says which decision broke.
"""

import os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_defects_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_defects                                          # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


@test("defect_master is seeded from icon_defects.py, one row per code")
def _():
    with store.conn() as (cx, cur):
        rows = db.defects(cur, active_only=False)
    assert len(rows) == len(icon_defects.DEFECT_MASTER), len(rows)
    codes = {r["code"] for r in rows}
    assert len(codes) == len(rows), "a code was seeded twice"


@test("re-running the seed does not touch a table that already has rows")
def _():
    with store.conn() as (cx, cur):
        cur.execute("UPDATE defect_master SET active=0 WHERE code='DF-OTHER'")
    store._ready = False
    store.ensure()
    with store.conn() as (cx, cur):
        row = db.defects(cur, active_only=False)
    row = [r for r in row if r["code"] == "DF-OTHER"][0]
    assert row["active"] == 0, "seeding ran again and overwrote the edit"


@test("leading-space and clean spellings of the same folder are one code")
def _():
    with store.conn() as (cx, cur):
        a = db.defect_code_for_folder(cur, "low eff")
        b = db.defect_code_for_folder(cur, " low eff")
        c = db.defect_code_for_folder(cur, "LOW EFF")
    assert a == b == c == "DF-LOWEFF", (a, b, c)


@test("OK is the clean verdict, never a defect code")
def _():
    with store.conn() as (cx, cur):
        assert db.defect_code_for_folder(cur, "OK") is None
        assert db.defect_code_for_folder(cur, " OK ") is None


@test("a folder name nothing has seeded resolves to None, not a guess")
def _():
    with store.conn() as (cx, cur):
        assert db.defect_code_for_folder(cur, "Not A Real Category") is None


@test("Cell Crack, Ribbon Short and Other are 'both' - filed by EL and typed by an operator")
def _():
    with store.conn() as (cx, cur):
        rows = {r["code"]: r for r in db.defects(cur, active_only=False)}
    for code in ("DF-CELLCRACK", "DF-RIBSHORT", "DF-OTHER"):
        assert rows[code]["source_hint"] == "both", rows[code]


# The EL Defect Master (17 Oct 2026): every spelling the six EL machines on the
# LAN filed 11-17 Oct, exactly as on disk, and the reason each one means.
SURVEY = {
    "DARK BUSBAR": "DF-DARKBUSBAR", "Low efficiency": "DF-LOWEFF",
    "Low effciency": "DF-LOWEFF", "Grid burning": "DF-GRIDBURNING",
    "Grid Buring": "DF-GRIDBURNING", "Grid Burning": "DF-GRIDBURNING",
    "Patches": "DF-PATCHES", "Lead OPEN/ Cross": "DF-LEADOPENCROSS",
    "Lead OPEN/Cross": "DF-LEADOPENCROSS", "Lead Open/Cross": "DF-LEADOPENCROSS",
    "Lead open/cross": "DF-LEADOPENCROSS", "other": "DF-OTHER", "Other": "DF-OTHER",
    "SR": "DF-SR", "Edge burning": "DF-EDGEBURNING", "Edge Burning": "DF-EDGEBURNING",
    "Cell Crack": "DF-CELLCRACK", "cell crack": "DF-CELLCRACK",
    " Cell Crack": "DF-CELLCRACK",
    "Cell issue/Ribbon bold": "DF-CELLISSUERIBBONBOLD",
    "Dust partical": "DF-FOREIGNPARTICLE", "String Short": "DF-STRSHORT",
    "String short": "DF-STRSHORT", "string short": "DF-STRSHORT",
    " NO IMEAGE": "DF-NOIMAGE", "NO IMEAGE": "DF-NOIMAGE",
    "Bussing Miss": "DF-BUSSINGMISS", "Bussing miss": "DF-BUSSINGMISS",
    "bussing miss": "DF-BUSSINGMISS", "BUSSING MISS": "DF-BUSSINGMISS",
    "Cell partical": "DF-CELLPARTICLE", "Ribbon short": "DF-RIBSHORT",
    "Terminel bending": "DF-TERMINALBENDING",
    "OUTPUT TERMINAL ISSU": "DF-OUTPUTTERMINALISSUE",
    "Cell Short": "DF-CELLSHORT", "Cell short": "DF-CELLSHORT",
    "Ribbon Missing": "DF-RIBBONMISSING", "Ribbon missing": "DF-RIBBONMISSING",
}
NEW_CODES = ("DF-DARKBUSBAR", "DF-GRIDBURNING", "DF-EDGEBURNING", "DF-LEADOPENCROSS",
             "DF-SR", "DF-CELLISSUERIBBONBOLD", "DF-NOIMAGE", "DF-CELLPARTICLE",
             "DF-TERMINALBENDING", "DF-OUTPUTTERMINALISSUE", "DF-RIBBONMISSING")


@test("every spelling the EL machines file - typos, leading spaces, a folder "
      "inside a folder - resolves to its reason")
def _():
    with store.conn() as (cx, cur):
        got = {raw: db.defect_code_for_folder(cur, raw) for raw in SURVEY}
    wrong = {raw: (got[raw], want) for raw, want in SURVEY.items() if got[raw] != want}
    assert not wrong, wrong
    # the Python map FQC and the poller read agrees with the table
    for raw, want in SURVEY.items():
        assert icon_defects.FOLDER_MAP.get(icon_defects.normalize(raw)) == want, raw


@test("the eleven new reasons are on the list; every code that was there still is")
def _():
    with store.conn() as (cx, cur):
        rows = {r["code"]: r for r in db.defects(cur, active_only=False)}
    for code in NEW_CODES:
        assert code in rows, code
    for code in ("DF-RIBSHORT", "DF-STRSHORT", "DF-BURNING", "DF-NOPOWER",
                 "DF-CROSS", "DF-LEADOPEN", "DF-LOWEFF", "DF-PATCHES"):
        assert code in rows, "an existing code was dropped: %s" % code
    assert "jig/probe" in rows["DF-NOIMAGE"]["label"].lower() and \
        "jb" in rows["DF-NOIMAGE"]["label"].lower(), \
        "NO IMEAGE's label must name both causes: %s" % rows["DF-NOIMAGE"]["label"]


@test("each reason names the stations it is filed at; Dust partical is Foreign "
      "Particle, on Pre-EL as well as FQC's own list")
def _():
    with store.conn() as (cx, cur):
        rows = {r["code"]: r for r in db.defects(cur, active_only=False)}
    assert rows["DF-TERMINALBENDING"]["stations"] == "pre_el"
    assert rows["DF-DARKBUSBAR"]["stations"] == "final_el"
    assert rows["DF-FOREIGNPARTICLE"]["stations"] == "pre_el,final_el,visual"
    assert rows["DF-CORNERCHIP"]["stations"] == "visual"
    assert rows["DF-FOREIGNPARTICLE"]["source_hint"] == "both"
    assert all(r["stations"] for r in rows.values()), \
        [c for c, r in rows.items() if not r["stations"]]


@test("a folder no machine's list has - and 'ell issue', left out of the scope - "
      "resolves to nothing: recorded under its own name, never guessed")
def _():
    with store.conn() as (cx, cur):
        assert db.defect_code_for_folder(cur, "Corner Chip ") is None
        assert db.defect_code_for_folder(cur, "ell issue/Ribbon bold") is None


@test("an existing database GAINS the new reasons and spellings at start-up, and "
      "nothing it already had is changed")
def _():
    # a database from before 17 Oct: none of the new rows, no stations, and an
    # Admin's own correction (DF-OTHER retired) that must survive
    with store.conn() as (cx, cur):
        cur.execute("DELETE FROM defect_folder_map WHERE defect_code IN (%s)"
                    % ",".join("'%s'" % c for c in NEW_CODES))
        cur.execute("DELETE FROM defect_master WHERE code IN (%s)"
                    % ",".join("'%s'" % c for c in NEW_CODES))
        cur.execute("DELETE FROM defect_folder_map WHERE folder_key='low effciency'")
        cur.execute("UPDATE defect_master SET stations=NULL")
        cur.execute("UPDATE defect_master SET source_hint='visual' "
                    "WHERE code='DF-FOREIGNPARTICLE'")
        cur.execute("UPDATE defect_master SET active=0 WHERE code='DF-OTHER'")
        cur.execute("UPDATE defect_folder_map SET sample_raw='by hand' "
                    "WHERE folder_key='low eff'")
    store._ready = False
    store.ensure()
    with store.conn() as (cx, cur):
        rows = {r["code"]: r for r in db.defects(cur, active_only=False)}
        assert db.defect_code_for_folder(cur, "Low effciency") == "DF-LOWEFF"
        assert db.defect_code_for_folder(cur, " NO IMEAGE") == "DF-NOIMAGE"
        raw = cur.execute("SELECT sample_raw FROM defect_folder_map "
                          "WHERE folder_key='low eff'").fetchone()["sample_raw"]
    assert len(rows) == len(icon_defects.DEFECT_MASTER), len(rows)
    assert rows["DF-OTHER"]["active"] == 0, "the Admin's retirement was undone"
    assert raw == "by hand", "an existing folder row was rewritten"
    assert rows["DF-FOREIGNPARTICLE"]["stations"] == "pre_el,final_el,visual"
    assert rows["DF-FOREIGNPARTICLE"]["source_hint"] == "both"


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
