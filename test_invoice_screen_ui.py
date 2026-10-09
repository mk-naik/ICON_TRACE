"""
ICON TRACE - the Tax Invoice screen (v4's parser view plus the live layer), in
a real browser.

    python test_invoice_screen_ui.py

What the operator sees has to agree with what the server enforces:

  1. an e-Way Bill valid until TODAY can be attached (the server's rule:
     expired = valid-until < today); one that ended yesterday cannot;
  2. when the parser finds no quantity, the operator types it (v4: "The
     parser did not find this. Type it rather than trust a guess.") - no page
     error, Attach enables, and the typed figure is stored, marked edited;
  3. a stored invoice opens to be read (View), with Attach off - nothing on
     the server edits one.

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


@test("an e-Way Bill valid until today can be attached; one that ended "
      "yesterday cannot (the server's rule, on the screen too)")
def t_ewb_valid_today():
    store.wipe()
    today = clock.today()
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator", login_id="disp.ui1")
        load(pg, make_pdf(H.TMP, "UINV/26-27/001", 36,
                          ewb_upto=today.strftime("%d-%b-%Y")))
        assert pg.is_enabled("#invSubmit"), pg.inner_text("#invStatus")
        assert "expired" not in pg.inner_text("#invStatus").lower()
        pg.click("#invSubmit")
        pg.wait_for_timeout(1200)
        assert stored("UINV/26-27/001"), "valid-today invoice was not stored"
        yday = today - datetime.timedelta(days=1)
        load(pg, make_pdf(H.TMP, "UINV/26-27/002", 36,
                          ewb_upto=yday.strftime("%d-%b-%Y")))
        assert not pg.is_enabled("#invSubmit")
        assert "expired" in pg.inner_text("#invStatus").lower()
        # typed by hand as DD/MM/YYYY - v4 alone never saw this as a date
        pg.fill("#f_ewb_valid_upto", yday.strftime("%d/%m/%Y"))
        pg.wait_for_timeout(200)
        assert not pg.is_enabled("#invSubmit"), "a typed expired date was let through"
        assert not pg.errors, pg.errors


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


@test("the invoice list's View opens a stored invoice with Attach off and "
      "says why - there is no edit of a stored invoice to save (audit 9 Oct)")
def t_view_stored_invoice():
    store.wipe()
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator", login_id="disp.ui3")
        load(pg, make_pdf(H.TMP, "UINV/26-27/004", 36))
        pg.click("#invSubmit")
        pg.wait_for_timeout(1200)
        assert stored("UINV/26-27/004")
        pg.click("#sidenav [data-v='invoice']")
        pg.wait_for_timeout(1200)
        row = pg.locator("#invoiceListBody tr", has_text="UINV/26-27/004")
        assert row.locator("button", has_text="Edit").count() == 0
        row.locator("button", has_text="View").click()
        pg.wait_for_timeout(1200)
        assert pg.input_value("#f_invoice_no") == "UINV/26-27/004"
        assert not pg.is_enabled("#invSubmit"), "Attach offered on a stored invoice"
        assert "already on file" in pg.inner_text("#invStatus")
        pg.fill("#f_buyer_name", "SOMEONE ELSE")
        pg.wait_for_timeout(200)
        assert not pg.is_enabled("#invSubmit"), "typing re-enabled Attach"
        assert not pg.errors, pg.errors


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
