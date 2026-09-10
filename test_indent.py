"""
ICON TRACE - tests for the indent list and what an edit may do to it.

    python test_indent.py

THE RULES THIS FILE DEFENDS

  * An indent number is used once. The database enforces it, so two quick
    presses of Save cannot make two.

  * An edit never empties an indent. It used to: a PUT carrying no items
    deleted every line, and because the progress view joined to those lines
    the indent then vanished from every screen while its number went on
    refusing to be used again - invisible and un-recreatable. The usual
    cause was a form that had not finished loading.

  * The list is one row per ITEM. Two rows under one indent number are its
    two items, not a duplicate.

Each test names the rule it defends, so a failure says which decision broke.
"""

import os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_ind_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_models as models                                 # noqa: E402
import app as APP                                            # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


ITEMS = [i["item_code"] for i in models.all_items()][:2]


def setup():
    store.wipe()
    return APP.app.test_client()


def make(c, no="SEP-09/2026", items=None):
    return c.post("/api/indent", json={
        "indent_no": no, "indent_date": "2026-09-09", "customer": "ICON STOCK",
        "items": items if items is not None
                 else [{"item_code": ITEMS[0], "qty": 120}]})


def rows(c):
    return c.get("/api/indents").get_json()


# --------------------------------------------------------------------------
# one number, one indent
# --------------------------------------------------------------------------

@test("an indent number cannot be used twice")
def t_unique_number():
    c = setup()
    assert make(c).get_json().get("ok"), "the first save should succeed"
    again = make(c).get_json()
    assert again.get("errors"), "the same number was accepted twice"
    assert "already exists" in " ".join(again["errors"]), again


@test("the database refuses a duplicate even if the check is bypassed")
def t_unique_enforced_in_db():
    c = setup()
    make(c)
    import sqlite3
    with store.conn() as (cx, cur):
        try:
            store.insert(cur, "indent", {
                "indent_no": "SEP-09/2026", "indent_date": "2026-09-09",
                "customer": "STOCK", "build_type": "make_to_stock",
                "status": "open", "created_by": "t"})
            raise AssertionError("a second row with the same number was "
                                 "written - the constraint is missing")
        except sqlite3.IntegrityError:
            pass


# --------------------------------------------------------------------------
# an edit never empties an indent
# --------------------------------------------------------------------------

@test("an edit carrying no items is refused, not applied")
def t_empty_edit_refused():
    c = setup()
    make(c)
    r = c.put("/api/indent/SEP-09%2F2026", json={"items": []})
    d = r.get_json()
    assert d.get("errors"), "an edit with no items was accepted"
    assert "empty the indent" in " ".join(d["errors"]), d
    assert len([x for x in rows(c) if x["indent_no"] == "SEP-09/2026"]) == 1, \
        "the items were deleted anyway"


@test("the items survive a refused edit")
def t_items_survive():
    c = setup()
    make(c)
    c.put("/api/indent/SEP-09%2F2026", json={"items": []})
    row = [x for x in rows(c) if x["indent_no"] == "SEP-09/2026"][0]
    assert row["ordered_qty"] == 120, row


@test("a real edit still replaces the items")
def t_real_edit_works():
    c = setup()
    make(c)
    r = c.put("/api/indent/SEP-09%2F2026",
              json={"items": [{"item_code": ITEMS[0], "qty": 240}]})
    assert r.get_json().get("ok"), r.get_json()
    row = [x for x in rows(c) if x["indent_no"] == "SEP-09/2026"][0]
    assert row["ordered_qty"] == 240, row


@test("an indent that already has no items is still visible, and fixable")
def t_orphan_visible():
    c = setup()
    with store.conn() as (cx, cur):
        store.insert(cur, "indent", {
            "indent_no": "AUG-01/2026", "indent_date": "2026-08-01",
            "customer": "STOCK", "build_type": "make_to_stock",
            "status": "open", "created_by": "t"})
    listed = [x for x in rows(c) if x["indent_no"] == "AUG-01/2026"]
    assert listed, \
        "an indent with no items vanished from the list while its number " \
        "still refused to be reused"
    assert listed[0]["indent_line_id"] is None, listed[0]
    # and it can be given items back
    r = c.put("/api/indent/AUG-01%2F2026",
              json={"items": [{"item_code": ITEMS[0], "qty": 36}]})
    assert r.get_json().get("ok"), r.get_json()
    assert [x for x in rows(c)
            if x["indent_no"] == "AUG-01/2026"][0]["ordered_qty"] == 36


# --------------------------------------------------------------------------
# what looks like a duplicate
# --------------------------------------------------------------------------

@test("an indent with two items is two rows under one number, not two indents")
def t_two_items_two_rows():
    c = setup()
    if len(ITEMS) < 2:
        return
    make(c, items=[{"item_code": ITEMS[0], "qty": 100},
                   {"item_code": ITEMS[1], "qty": 200}])
    mine = [x for x in rows(c) if x["indent_no"] == "SEP-09/2026"]
    assert len(mine) == 2, mine
    assert sorted(x["line_no"] for x in mine) == [1, 2], \
        "the rows should be numbered items of one indent"
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM indent "
                           "WHERE indent_no='SEP-09/2026'")["n"]
    assert n == 1, "there should be one indent behind those two rows, not %d" % n


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
