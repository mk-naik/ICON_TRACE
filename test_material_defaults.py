"""
ICON TRACE - a material's default make, and the two packing materials.

    python test_material_defaults.py

Mukesh, on ICON625R1293022642's BOM, which showed Barcode Label and Pallet
Packing as "not recorded": "for Barcode Label use Kvell, for pallet remove
current make, use Manmohan and Balaji, and set default Manmohan."

THE RULES THIS FILE DEFENDS

  1. A material may name a DEFAULT MAKE, one of its makes. Barcode Label's is
     Kvell; Pallet Packing's makes are Manmohan and Balaji, default Manmohan.
  2. A database that already holds the old seeded rows is brought to that once,
     only while the row is still the seeded one - a person's edit is never put
     back - and a boot read that has nothing to change writes nothing.
  3. The master refuses a default that is not one of the makes.
  4. Planning pre-selects the default and the import records it where the file
     is silent (test_bom_match / test_bom_match_ui cover those two).

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def mat(n):
    with store.conn() as (cx, cur):
        return [m for m in db.materials(cur) if m["n"] == n][0]


def old_database():
    """A database seeded before this change: the two rows as they were."""
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        cur.execute("UPDATE material SET makes=%s, default_make=NULL, updated_by=NULL WHERE n=30",
                    ('["Kvell", "Sunsol"]',))
        cur.execute("UPDATE material SET default_make=NULL, updated_by=NULL WHERE n=29")


def changes():
    with store.conn() as (cx, cur):
        return cur.execute("SELECT COUNT(*) AS n FROM change_log").fetchone()["n"]


@test("a fresh master has them: Barcode Label defaults to Kvell, Pallet Packing is "
      "Manmohan or Balaji, Manmohan by default")
def t_fresh():
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
    assert mat(29)["default_make"] == "Kvell" and "Kvell" in mat(29)["makes"], mat(29)
    assert mat(30)["makes"] == ["Manmohan", "Balaji"] and mat(30)["default_make"] == "Manmohan", mat(30)


@test("an existing database is brought to it once - and a boot read with nothing "
      "to change writes nothing")
def t_migrates():
    old_database()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)                 # what every boot read does
    assert mat(29)["default_make"] == "Kvell", mat(29)
    assert mat(30)["makes"] == ["Manmohan", "Balaji"] and mat(30)["default_make"] == "Manmohan", mat(30)
    before = changes()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        db.seed_materials(cur)
    assert changes() == before, "a boot read wrote although there was nothing to change"


@test("a person's edit is never put back: a row somebody saved, or whose makes are "
      "no longer the seeded ones, is left alone")
def t_edit_survives():
    old_database()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE material SET updated_by='Mukesh Naik' WHERE n=29")
        cur.execute("UPDATE material SET makes=%s WHERE n=30", ('["Sunsol"]',))
        db.seed_materials(cur)
    assert mat(29).get("default_make") is None, mat(29)
    assert mat(30)["makes"] == ["Sunsol"] and mat(30).get("default_make") is None, mat(30)


@test("the G12R frame's mounting holes are variants of ONE material: the 1000 frame the master "
      "already had, and the 790 one, in one group - an existing database gets it once, "
      "and a frame somebody edited is left alone")
def t_frame_variants():
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
    assert mat(8)["group"] == "FRM" and mat(34)["group"] == "FRM"
    assert "holes 1000, 1400, 1094" in mat(8)["size"] and "holes 790, 1400, 1094" in mat(34)["size"]
    # a database seeded before: the frame as it was, no 790 variant
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        cur.execute("DELETE FROM material WHERE n=34")
        cur.execute("UPDATE material SET size='2382 x 1134 x 30 mm', grp=NULL, note=NULL, updated_by=NULL WHERE n=8")
        db.seed_materials(cur)
    assert mat(34)["size"].endswith("holes 790, 1400, 1094 mm") and mat(8)["group"] == "FRM", (mat(8), mat(34))
    assert mat(8)["size"] == "2382 x 1134 x 30 mm · holes 1000, 1400, 1094 mm", mat(8)["size"]
    before = changes()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        db.seed_materials(cur)
    assert changes() == before, "a boot read wrote although there was nothing to change"
    # a frame somebody edited keeps its size
    store.wipe()
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
        cur.execute("UPDATE material SET size='2382 x 1134 x 32 mm', grp=NULL, updated_by='Mukesh Naik' WHERE n=8")
        db.seed_materials(cur)
    assert mat(8)["size"] == "2382 x 1134 x 32 mm", mat(8)["size"]


@test("the master refuses a default that is not one of the makes, and accepts one that is")
def t_validation():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)
    with store.conn() as (cx, cur):
        db.seed_materials(cur)
    m = dict(mat(30))
    m["default_make"] = "Nobody"
    r = c.put("/api/material/30", json=m)
    assert r.status_code == 400 and "one of the material's makes" in r.get_json()["why"], r.get_json()
    assert mat(30)["default_make"] == "Manmohan", "a refused save changed the row"
    m["default_make"] = "Balaji"
    r = c.put("/api/material/30", json=m)
    assert r.status_code == 200 and mat(30)["default_make"] == "Balaji", (r.status_code, r.get_json())
    m["default_make"] = ""
    assert c.put("/api/material/30", json=m).status_code == 200 and "default_make" not in mat(30)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %-*s" % (width, name))
                passed += 1
            except Exception as e:
                print("  FAIL  %-*s  %s" % (width, name, str(e)[:500]))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
