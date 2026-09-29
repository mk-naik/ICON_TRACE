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
