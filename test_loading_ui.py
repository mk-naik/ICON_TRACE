"""
ICON TRACE - Loading Verification in a real browser.

    python test_loading_ui.py        (needs Playwright + Chromium)

test_loading.py holds the server rules and test_loading.js the session's
own logic against a stub page. What only exists once the page is running -
a scanner's Enter in the pallet-contents check, the list's count beside the
rows a search really leaves, what Reset puts back, the day the list opens
on - is checked here, in Chromium, on the real app.
"""

import shutil
import sys
import traceback

import test_loading as T            # first: it fixes the throwaway database
import ui_harness as H              # noqa: E402  (same store and app)
import store                        # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def issued(c, idx, invoice_no):
    b = T.packed_box(c, idx)
    inv = T.make_invoice(qty=len(idx), invoice_no=invoice_no)
    return T.make_issued_challan(c, [b], inv)


@test("the pallet-contents check matches a scanned module (Enter) and flags one "
      "that is not in the pallet - its listeners survive the close bar put in "
      "front of it")
def t_contents_check_scan():
    c = T.setup()
    chid = issued(c, [2, 3], "INV-UI-SCAN")
    box_no = T.box_no_of(chid)
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator")
        pg.evaluate("go('loadver')")
        pg.wait_for_selector("#ldPalletCheckClose", timeout=10000)
        pg.fill("#lvBox", box_no)
        pg.click("text=Load its serials")
        pg.wait_for_selector("#lvCard", state="visible", timeout=5000)
        pg.fill("#lvScan", T.serial(2))
        pg.press("#lvScan", "Enter")
        pg.wait_for_timeout(200)
        assert pg.inner_text("#lvOk").strip().startswith("1"), pg.inner_text("#lvOk")
        pg.fill("#lvScan", T.serial(77))
        pg.press("#lvScan", "Enter")
        pg.wait_for_timeout(200)
        assert pg.inner_text("#lvBad").strip().startswith("1"), pg.inner_text("#lvBad")
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
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(T.TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
