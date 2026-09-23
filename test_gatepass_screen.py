"""
ICON TRACE - tests for the Gate Pass screens in a real browser.

    python test_gatepass_screen.py     (needs Playwright + Chromium)

THE RULES THIS FILE DEFENDS

  1. THE LANDING LIST ACTUALLY RENDERS CLICKABLE ACTIONS. Every row - module-
     linked or standalone - shows a real, visible Print link. A standalone
     row additionally shows a real, visible Edit button. A module-linked
     row does not, anywhere - not hidden, not disabled, simply not there.
     Reported missing live once; proven here against the running page
     itself, not by reading gpRenderListRow()'s source.

  2. THE CREATE PAGE IS STANDALONE ONLY, IN THE ACTUAL DOM. No module
     checkbox, no reachable challan selector, no live preview panel, no
     leftover Loading verification card, and a header that describes a
     standalone gate pass rather than one issued against a challan -
     checked against the rendered page, because a function that no longer
     builds this markup is not the same claim as the markup not being
     there.

  3. THE SUMMARY TRAIL IS REAL. Adding and removing item rows, and
     toggling NRGP/RGP, updates the on-screen item count and kind
     indicator, live, in the browser - not assumed from a previous
     commit message.

These run in a real browser against a throwaway database, because what a
person actually sees - a rendered button, a hidden field, a live count -
only exists once the page is running.
"""

import datetime, sys, traceback

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


WATT = 630
MODEL = "ISEN630-G12R"


def serial(i):
    return "ICONSCR%dR129073%03d" % (WATT, i)


def packed_box(c, idx):
    with store.conn() as (cx, cur):
        for i in idx:
            store.insert(cur, "serial", {
                "serial": serial(i), "build_instance": 1, "model": MODEL,
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned", "grade": "A"})
            db.set_serial(cur, serial(i), state="graded")
    b = c.post("/api/box/open",
              json={"grade": "A", "model": MODEL, "capacity": len(idx)}).get_json()
    for i in idx:
        r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(i)})
        assert r.status_code == 200, r.get_json()
    c.post("/api/box/%d/close" % b["box_id"], json={})
    return b["box_id"]


def make_invoice(qty, invoice_no):
    data = {"buyer_name": "AGNI GREEN POWER LIMITED (MZ)",
            "buyer_gstin": "15AACCA2122Q1ZT", "declared_qty": qty,
            "declared_model": MODEL, "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                              datetime.timedelta(days=10)).isoformat(),
            "invoice_no": invoice_no, "irn": None,
            "consignee_same_as_buyer": 1}
    with store.conn() as (cx, cur):
        return db.insert_invoice(cur, data, "test.pdf", "deadbeef-" + invoice_no,
                                 {"fields": {}, "compare_only": {}, "qr": {}},
                                 False, {}, "tester")


_module_idx = [0]


def module_gatepass(c, invoice_no):
    """Pack, issue, load and submit - the auto-generated gate pass, the
    only way a module one exists at all now."""
    _module_idx[0] += 1
    b = packed_box(c, [_module_idx[0]])
    inv = make_invoice(1, invoice_no)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    chid = r.get_json()["challan_id"]
    boxes = c.get("/api/loading/%d" % chid).get_json()["boxes"]
    for bx in boxes:
        c.post("/api/loading/%d/confirm" % chid, json={"box_no": bx["box_no"]})
    r2 = c.post("/api/loading/%d/submit" % chid, json={})
    assert r2.status_code == 200, r2.get_json()
    return chid


def standalone_gatepass(c, party="Repair Vendor Pvt Ltd"):
    r = c.post("/api/gatepass", json={"kind": "NRGP", "party": party,
                                      "items": [{"description": "Laptop for repair",
                                                "unit": "Nos", "qty": 1, "remark": None}]})
    assert r.get_json()["ok"], r.get_json()
    return r.get_json()


def base():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


# --------------------------------------------------------------------------
# 1 - the landing list actually renders clickable actions
# --------------------------------------------------------------------------

@test("every row on the landing list shows a real, visible, clickable "
     "Print link - module-linked and standalone alike")
def t_print_visible_every_row():
    c = base()
    module_gatepass(c, "INV-SCR-1")
    standalone_gatepass(c)
    with H.browser() as b:
        pg = H.open_page(b, "gp-list", wait_ms=1200)
        assert pg.errors == [], pg.errors
        rows = pg.eval_on_selector_all("#gpLTableBody tr", "els => els.length")
        assert rows == 2, "expected 2 rows, found %d" % rows
        prints = pg.eval_on_selector_all(
            "#gpLTableBody a",
            "els => els.filter(a => a.offsetParent !== null && "
            "a.textContent.trim() === 'Print').length")
        assert prints == 2, \
            "expected 2 visible Print links, found %d - this is the exact " \
            "thing reported missing live" % prints
        # and it is a real, followable link, not a dead decoration
        href = pg.eval_on_selector("#gpLTableBody a", "a => a.getAttribute('href')")
        assert href and href.startswith("/gatepass/") and href.endswith("/print"), href


@test("a standalone row shows a real, visible, clickable Edit button; a "
     "module-linked row shows no Edit anywhere - not hidden, not "
     "disabled, absent")
def t_edit_only_on_standalone_row():
    c = base()
    module_gatepass(c, "INV-SCR-2")
    standalone_gatepass(c, party="Edit Target Vendor")
    with H.browser() as b:
        pg = H.open_page(b, "gp-list", wait_ms=1200)
        edit_count = pg.eval_on_selector_all(
            "#gpLTableBody button",
            "els => els.filter(b => b.offsetParent !== null && "
            "b.textContent.trim() === 'Edit').length")
        assert edit_count == 1, "expected exactly 1 visible Edit button, found %d" % edit_count
        # it belongs to the standalone row, not the module row
        row_text = pg.eval_on_selector_all(
            "#gpLTableBody tr",
            "trs => trs.map(tr => ({text: tr.textContent, "
            "hasEdit: !!tr.querySelector('button')}))")
        standalone_row = [r for r in row_text if "Edit Target Vendor" in r["text"]][0]
        module_row = [r for r in row_text if "AGNI" in r["text"]][0]
        assert standalone_row["hasEdit"], standalone_row
        assert not module_row["hasEdit"], \
            "the module-linked row has an Edit action: %s" % module_row

        # clickable: it actually opens the create form pre-filled
        pg.click("#gpLTableBody button:has-text('Edit')")
        pg.wait_for_timeout(600)
        on_form = pg.evaluate(
            "document.getElementById('v-gp-new') && "
            "document.getElementById('v-gp-new').classList.contains('on')")
        assert on_form, "clicking Edit did not open the create form"
        party_val = pg.eval_on_selector("#gpParty", "e => e.value")
        assert party_val == "Edit Target Vendor", party_val


# --------------------------------------------------------------------------
# 2 - the create page's DOM, not its source code
# --------------------------------------------------------------------------

@test("the New Gate Pass page has no module checkbox, no reachable "
     "challan selector, no preview panel, and no leftover Loading "
     "verification card anywhere in its DOM - and its header describes "
     "a standalone gate pass, not a challan-linked one")
def t_create_page_has_no_module_ui():
    c = base()
    with H.browser() as b:
        pg = H.open_page(b, "gp-list", wait_ms=800)
        pg.click("#gpNewBtn")
        pg.wait_for_timeout(600)
        assert pg.errors == [], pg.errors

        # no module checkbox exists at all
        has_checkbox = pg.evaluate("!!document.getElementById('gpIsSolar')")
        assert not has_checkbox, "#gpIsSolar still exists in the DOM"

        # the native "Against challan" select does not exist on this view at
        # all - v-gp-new is a purpose-built view, not v4's native v-gp, so
        # there is nothing here to hide in the first place
        visible_selects = pg.eval_on_selector_all(
            "#v-gp-new select",
            "els => els.filter(e => e.offsetParent !== null).map(e => e.id || e.className)")
        assert "gpChallanSelV4" not in visible_selects, \
            "a challan selector is visible on the create page: %s" % visible_selects
        # every visible <select> left is the item grid's own Nos/Kg/Set -
        # confirming the challan selector's ABSENCE is not just an empty page
        assert all(sel == "gpi_unit" for sel in visible_selects), visible_selects

        # no live document preview, and no leftover "Loading verification"
        # card either - v-gp-new has no heading matching either one
        stray_headings = pg.eval_on_selector_all(
            "#v-gp-new h3", "els => els.map(e => e.textContent.trim())")
        assert "Gate pass preview" not in stray_headings, stray_headings
        assert "Loading verification" not in stray_headings, stray_headings

        # and the real, standalone-only UI is what's actually there
        assert pg.eval_on_selector("#gpItemsBody", "e => e.offsetParent !== null")
        assert pg.eval_on_selector("#gpParty", "e => e.offsetParent !== null")

        # the header describes a standalone gate pass, not the old
        # module-linked flow
        header_text = pg.eval_on_selector("#gpNewTitle", "e => e.textContent")
        sub_text = pg.eval_on_selector("#gpNewSubtitle", "e => e.textContent")
        combined = (header_text + " " + sub_text).lower()
        assert "issued against a challan" not in combined, \
            "the create page still describes itself as issued against a " \
            "challan: %r / %r" % (header_text, sub_text)


# --------------------------------------------------------------------------
# 3 - the summary trail is real, live
# --------------------------------------------------------------------------

@test("the summary trail's item count and RGP/NRGP indicator update live "
     "as rows are added, removed and the Type is toggled, in the actual "
     "browser")
def t_summary_trail_updates_live():
    c = base()
    with H.browser() as b:
        pg = H.open_page(b, "gp-list", wait_ms=800)
        pg.click("#gpNewBtn")
        pg.wait_for_timeout(500)

        summary = lambda: pg.eval_on_selector("#gpItemsSummary", "e => e.textContent")
        assert summary().startswith("1 item"), summary()

        pg.click("#v-gp-new >> text=+ Add item")
        pg.click("#v-gp-new >> text=+ Add item")
        pg.wait_for_timeout(200)
        assert summary().startswith("3 items"), summary()
        rows = pg.eval_on_selector_all(".gp_item_row", "els => els.length")
        assert rows == 3, rows

        pg.click(".gp_item_row:last-child >> text=Remove this item")
        pg.wait_for_timeout(200)
        assert summary().startswith("2 items"), summary()

        # the RGP/NRGP indicator in the summary is live too, not just the
        # count - caught failing once (toggling Type left the summary
        # showing the old kind until the next item edit)
        assert summary().endswith("NRGP"), summary()
        pg.click("#gpRGP")
        pg.wait_for_timeout(200)
        assert not summary().endswith("NRGP"), \
            "toggling Type did not update the summary's kind indicator: %r" % summary()

        # Clear form takes it back to exactly one, blank. #gpClearBtn is a
        # real id (not a text locator) precisely because "Clear form" is
        # not unique across the whole page - v4 keeps every view in the
        # DOM at once, and another screen has a button with this same text.
        pg.click("#gpClearBtn")
        pg.wait_for_timeout(200)
        rows_after_clear = pg.eval_on_selector_all(".gp_item_row", "els => els.length")
        assert rows_after_clear == 1, rows_after_clear
        assert summary().startswith("1 item"), summary()
        party_val = pg.eval_on_selector("#gpParty", "e => e.value")
        assert party_val == "", "Clear form left the party field filled: %r" % party_val


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
