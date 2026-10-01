"""
ICON TRACE - the Planning screen for custom (non-ICON) serial numbers, in a
real browser.

    python test_custom_serials_ui.py

THE RULES THIS FILE DEFENDS

  1. On an ICON item the Excel upload is NOT on the screen, and the ICON range
     fields are. On a custom-serial item it is the other way round.
  2. A good file fills the rail (count, first, last, the item's model) and the
     bill of materials, enables Load, and Load writes the allocation.
  3. A bad file loads nothing: every problem is on screen with its cell, and
     Load stays disabled.
  4. Changing to another item drops what was uploaded.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import io, os, sys, tempfile, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import test_custom_serials as T                              # noqa: E402  (its world() and sheet())

TMP = tempfile.mkdtemp(prefix="icontrace_customui_")
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def xlsx(name, data):
    p = os.path.join(TMP, name)
    open(p, "wb").write(data)
    return p


def pick(pg, indent_no):
    pg.select_option("#pIndent", indent_no)
    pg.evaluate("indentChange()")
    pg.wait_for_timeout(500)


def open_plan(b):
    pg = H.open_page(b, "plan")
    pg.click("#newPlanBtn")
    pg.wait_for_timeout(500)
    return pg


def fill_bom(pg):
    """Choose a make (and efficiency) for every material, as the planner must."""
    pg.evaluate("""() => document.querySelectorAll('#matPanel .mat-f select').forEach(sel => {
        const o = Array.from(sel.options).find(x => x.value);
        if (o) { sel.value = o.value; sel.dispatchEvent(new Event('change', {bubbles: true})); }
    })""")
    pg.wait_for_timeout(300)


def visible(pg, sel):
    return pg.evaluate("(s) => { const e = document.querySelector(s); "
                       "return !!e && !!(e.offsetWidth || e.offsetHeight) && !e.hidden; }", sel)


@test("ICON item: the range fields, no upload anywhere; custom item: the upload "
      "and no range fields - and back again")
def t_mode_switch():
    T.world()
    with H.browser() as b:
        pg = open_plan(b)
        pick(pg, "OCT-02/2026")                                  # ICON
        assert visible(pg, "#rgFrom") and visible(pg, "#rgTo")
        assert not visible(pg, "#pCustomFile"), "the upload is offered for an ICON item"
        pick(pg, "OCT-01/2026")                                  # custom
        assert visible(pg, "#pCustomFile")
        assert not visible(pg, "#rgFrom") and not visible(pg, "#rgTo"), "ICON range shown for a custom item"
        props = pg.inner_text("#pPropsNote").lower()
        assert "make to order" in props and "custom serial numbers" in props, props
        pick(pg, "OCT-02/2026")
        assert visible(pg, "#rgFrom") and not visible(pg, "#pCustomFile")
        assert "front glass" in pg.inner_text("#v-plan").lower()
        assert not pg.errors, pg.errors


@test("a good file fills the rail and the bill of materials; Load writes the "
      "allocation with the serials as uploaded")
def t_upload_and_load():
    T.world()
    path = xlsx("good.xlsx", T.sheet([["B100001", "b100002", "B100003"]]))
    with H.browser() as b:
        pg = open_plan(b)
        pick(pg, "OCT-01/2026")
        assert pg.is_disabled("#loadBtn"), "Load is enabled before anything is uploaded"
        pg.set_input_files("#pCustomFile", path)
        pg.wait_for_selector("#pCustomResult .n-ok", timeout=8000)
        assert "3" in pg.inner_text("#pCustomResult") and "B100001" in pg.inner_text("#pCustomResult")
        assert pg.inner_text("#pvQty").strip() == "3", pg.inner_text("#pvQty")
        assert pg.inner_text("#pvFirst").strip() == "B100001" and pg.inner_text("#pvLast").strip() == "B100003"
        assert pg.inner_text("#pvModel").strip() == "ISEN625-G12R", pg.inner_text("#pvModel")
        assert pg.query_selector("#matPanel .matrow"), "the bill of materials did not appear"
        fill_bom(pg)
        assert not pg.is_disabled("#loadBtn"), pg.inner_text("#railStatus")
        pg.click("#loadBtn")
        pg.wait_for_function("() => !document.getElementById('pCustomResult') || "
                             "!document.getElementById('pCustomResult').innerText", timeout=8000)
        pg.wait_for_timeout(800)
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT serial, sequence, format_version FROM serial ORDER BY sequence")
        mats = store.one(cur, "SELECT COUNT(*) AS n FROM allocation_material")["n"]
    assert [r["serial"] for r in rows] == ["B100001", "B100002", "B100003"], rows
    assert all(r["format_version"] == 0 for r in rows) and mats >= 1, (rows, mats)


@test("a bad file loads nothing: each problem on screen with its cell, Load "
      "stays disabled, and a corrected file then works")
def t_bad_file():
    T.world()
    bad = xlsx("bad.xlsx", T.sheet([["B100001", "ab 12", "ABC", "B100001"]]))
    good = xlsx("fixed.xlsx", T.sheet([["B100001", "B100002"]]))
    with H.browser() as b:
        pg = open_plan(b)
        pick(pg, "OCT-01/2026")
        pg.set_input_files("#pCustomFile", bad)
        pg.wait_for_selector("#pCustomResult .n-bad", timeout=8000)
        txt = pg.inner_text("#pCustomResult")
        assert "Nothing was loaded" in txt and "B4" in txt and "space" in txt and "twice" in txt, txt
        assert pg.is_disabled("#loadBtn")
        assert pg.inner_text("#pvQty").strip() in ("—", "")
        pg.set_input_files("#pCustomFile", good)
        pg.wait_for_selector("#pCustomResult .n-ok", timeout=8000)
        fill_bom(pg)
        assert not pg.is_disabled("#loadBtn")
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM serial")["n"] == 0, "a bad file wrote serials"


@test("changing the item drops the uploaded list, and an upload for another "
      "item is never loaded against this one")
def t_change_item_drops_upload():
    T.world()
    path = xlsx("good2.xlsx", T.sheet([["B100001", "B100002"]]))
    with H.browser() as b:
        pg = open_plan(b)
        pick(pg, "OCT-01/2026")
        pg.set_input_files("#pCustomFile", path)
        pg.wait_for_selector("#pCustomResult .n-ok", timeout=8000)
        pick(pg, "OCT-02/2026")
        assert pg.evaluate("() => window.__customSerials") is None
        pick(pg, "OCT-01/2026")
        assert pg.evaluate("() => window.__customSerials") is None, "the old upload came back"
        assert pg.inner_text("#pCustomResult").strip() == ""
        assert pg.is_disabled("#loadBtn")


@test("Search & Trace on screen: typing a custom serial (Detect automatically) "
      "shows its journey, not 'nothing recorded'")
def t_search_screen():
    c, custom_line, _ = T.world()
    T.allocate(c, custom_line, ["B100001"])
    with H.browser() as b:
        pg = H.open_page(b, "search")
        pg.fill("#qBox", "b100001")
        pg.evaluate("doSearch()")
        pg.wait_for_function("() => { const o = document.getElementById('searchOut');"
                             " return o && /MODULE JOURNEY/i.test(o.innerText); }", timeout=8000)
        txt = pg.inner_text("#searchOut")
        assert "B100001" in txt and "Nothing recorded" not in txt, txt[:300]
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
                print("  FAIL  %-*s  %s" % (width, name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
