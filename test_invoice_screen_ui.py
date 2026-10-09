"""
ICON TRACE - the Tax Invoice screen (v4's parser view plus the live layer), in
a real browser.

    python test_invoice_screen_ui.py

What the operator sees has to agree with what the server enforces:

  1. when the parser finds no quantity, the operator types it (v4: "The
     parser did not find this. Type it rather than trust a guess.") - no page
     error, Attach enables, and the typed figure is stored, marked edited.

The invoices are synthetic PDFs (invoice_pdf_fixture.py). ui_harness is
imported FIRST: it fixes the throwaway database path.
"""

import datetime, json, os, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
from invoice_pdf_fixture import irn_of, make_pdf             # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def load(pg, path):
    """Pick the PDF in the screen's own file input, as Read Invoice does."""
    pg.evaluate("go('invoice-parser')")
    pg.wait_for_timeout(300)
    pg.set_input_files("#invFile", path)
    pg.wait_for_function("document.getElementById('invFields').querySelector('#f_invoice_no')",
                         timeout=10000)
    pg.wait_for_timeout(300)


def stored(invoice_no):
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT * FROM invoice WHERE irn=%s",
                         (irn_of(invoice_no),))


@test("no quantity on the invoice: no page error, the typed quantity enables "
      "Attach and is stored, marked edited")
def t_quantity_typed_when_missing():
    store.wipe()
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator", login_id="disp.ui2")
        load(pg, make_pdf(H.TMP, "UINV/26-27/003", 36, qty_text=""))
        assert not pg.is_enabled("#invSubmit")
        pg.fill("#f_quantity", "36")
        pg.wait_for_timeout(300)
        assert not pg.errors, pg.errors
        assert pg.is_enabled("#invSubmit"), pg.inner_text("#invStatus")
        pg.click("#invSubmit")
        pg.wait_for_timeout(1200)
        row = stored("UINV/26-27/003")
        assert row and row["declared_qty"] == 36, dict(row or {})
        assert "quantity" in json.loads(row["edited_fields"] or "{}")


def _filed():
    return set(os.listdir(H.APP.STORE)) if os.path.isdir(H.APP.STORE) else set()


if __name__ == "__main__":
    _filed_before = _filed()           # the PDFs these tests file are removed after
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
        for f in _filed() - _filed_before:
            try:
                os.remove(os.path.join(H.APP.STORE, f))
            except OSError:
                pass
        H.cleanup()
    sys.exit(1 if failed else 0)
