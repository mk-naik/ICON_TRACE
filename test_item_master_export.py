"""
ICON TRACE - Item Master's Export table exports, and is recorded.

    python test_item_master_export.py      (needs Playwright + Chromium)

The button sat in the page header, outside the table's own wiring
(icon_table.js answers data-role="export" only inside its card), so it did
nothing at all - found by the overnight audit, 24 Oct 2026. The indent list
had the same fault once (test_indent_export.py). It now goes through the
same Export every other screen uses: the rows on screen, sent to
/api/export/xlsx, recorded in the Document & print log.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_models as models                                 # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


@test("in the browser: Item Master's Export table sends the items on screen to "
      "/api/export/xlsx, and the export is in the Document & print log")
def t_items_export():
    store.wipe()
    AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = H.open_page(b, "items", wait_ms=1200)
        pg.wait_for_selector("#v-items tbody tr")
        shown = pg.eval_on_selector_all("#v-items tbody tr", "rs => rs.length")
        with pg.expect_request("**/api/export/xlsx", timeout=8000) as info:
            with pg.expect_download(timeout=8000):
                pg.click("#v-items .pg-act >> text=Export table")
        body = info.value.post_data_json
        assert body["name"] == "items", body["name"]
        rows = sum(len(s["rows"]) for s in body["sheets"])
        assert rows == shown == len(models.all_items()), (rows, shown)
        cols = body["sheets"][0]["columns"]
        assert cols[:4] == ["Item", "Cell type", "Item code", "Model"], cols
        pg.wait_for_timeout(300)
        with store.conn() as (cx, cur):
            logged = store.rows(cur, "SELECT action, entity_id FROM dispatch_audit "
                                     "WHERE action='export.xlsx'", ())
        got = [(r["action"], r["entity_id"]) for r in logged]
        assert got == [("export.xlsx", "items")], got
        assert not pg.errors, pg.errors


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
                print("  FAIL  %-*s  %s" % (width, name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
