"""
ICON TRACE - the Challan list, in a real browser.

    python test_challan_list_ui.py

The list reloads from the server on every keystroke in its search box, on
every change of its Status filter and on Refresh. Those inline handlers call
clLoad() on window - where it was not (every one threw "clLoad is not
defined" and the list never moved). And a reload asked for while one is
still on its way must not be dropped: the rows shown have to be the rows for
what the search box and the filter say once the typing stops - not the
first keystroke's rows under the whole word.

Realistic data: two challans for two buyers, made from real pallets and
invoices (test_challan.py's helpers). ui_harness is imported FIRST: it fixes
the throwaway database path.
"""

import sys, time, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import test_challan as T                                     # noqa: E402  (seeding: real pallets, invoices)

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def seed():
    c = T.setup()
    for k, (name, gstin) in enumerate(((T.AGNI_NAME, T.AGNI_GSTIN),
                                       ("RAVITYA SOLAR ENERGY LLP - (MH)",
                                        "27ABNFR6585K1Z9"))):
        b = T.packed_box(c, [300 + 2 * k, 301 + 2 * k])
        inv = T.make_invoice(qty=2, buyer_name=name, buyer_gstin=gstin,
                             invoice_no="INV-LIST-%d" % k)
        r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                         "invoice_id": inv, "buyer_name": name})
        assert r.status_code == 200, r.get_json()


@test("typing into the search while a reload is on its way: the rows end up "
      "the ones for the whole word, not the first keystroke's (audit 9 Oct)")
def t_search_while_loading():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, view="challan-list", role="Dispatch Operator",
                         login_id="disp.list", wait_ms=1200)

        def slow(route):
            time.sleep(0.4)
            route.continue_()
        pg.route("**/api/challans?*", slow)
        pg.type("#clSearch", "RAVITYA", delay=50)
        pg.wait_for_timeout(3000)
        rows = pg.locator("#clTableBody tr").all_inner_texts()
        assert len(rows) == 1 and "RAVITYA" in rows[0].upper(), rows
        pg.fill("#clSearch", "")
        pg.select_option("#clStatusFilter", "issued")
        pg.wait_for_timeout(2500)
        rows = pg.locator("#clTableBody tr").all_inner_texts()
        assert len(rows) == 2, rows
        assert not pg.errors, pg.errors


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
        H.cleanup()
    sys.exit(1 if failed else 0)
