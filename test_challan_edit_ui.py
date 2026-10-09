"""
ICON TRACE - editing an issued challan, and printing the result, in a real browser.

    python test_challan_edit_ui.py        (needs Playwright + Chromium)

An edit never rewrites a challan: it makes a new version at the same number
with a suffix (MA, MB...) and marks the original superseded. So a challan is
named by its number AND its suffix, and what a person clicks has to say which
one it means:

  1. After an edit and that version's own Loading Verification, the challan's
     Print link opens the printed challan - it names the suffix. It used to
     name only /challan/<fy>/<seq>/print, which is the superseded original, and
     the server answered "superseded by an edit - print ... (MA) instead".
  2. The superseded original is not offered a Print or Excel link at all (they
     could only ever open that refusal); it offers "View the replacement".

Realistic data, not an empty database: three real pallets of FQC-passed modules,
a real invoice, and a challan created with its transport details the way the
Create screen posts them. test_challan.py seeds it (its helpers are reused);
ui_harness is imported FIRST because it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import test_challan as T                                     # noqa: E402  (seeding: real pallets, invoice)
import store                                                 # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def seed(**over):
    """(client, challan_id, box_ids): three pallets of two modules on an issued
    challan, created with the fields the Create screen posts for an invoice.
    `over` replaces any of those fields (a date, a buyer typed differently...)."""
    c = T.setup()
    boxes = [T.packed_box(c, [10, 11]), T.packed_box(c, [12, 13]),
             T.packed_box(c, [14, 15])]
    inv = T.make_invoice(qty=6, invoice_no="INV-EDIT-UI")
    body = {
        "action": "create", "boxes": boxes, "invoice_id": inv,
        "buyer_name": T.AGNI_NAME, "buyer_gstin": T.AGNI_GSTIN,
        "consignee_same_as_buyer": True, "consignee_name": "",
        "consignee_address": "", "vehicle_no": "CG04AB1234",
        "transporter": "Sharma Transport", "lr_no": "LR-778",
        "driver_name": "Ramesh", "driver_mobile": "9876543210"}
    body.update(over)
    r = c.post("/api/challan", json=body)
    assert r.status_code == 200, r.get_json()
    return c, r.get_json()["challan_id"], boxes


def challans():
    """Every challan row, as the list screen sees the lineage."""
    with store.conn() as (cx, cur):
        return [dict(r) for r in store.rows(
            cur, "SELECT challan_id, suffix, status, challan_date, buyer_name, "
                 "consignee_name, consignee_address FROM challan "
                 "ORDER BY challan_id")]


def toast_text(pg):
    return pg.evaluate("(document.getElementById('toast') || {}).textContent || ''")


def open_detail(pg, cid):
    pg.evaluate("go('challan-list')")
    pg.wait_for_timeout(800)
    pg.evaluate("clOpenDetail(%d)" % cid)
    pg.wait_for_selector("#clDetailCard button", timeout=8000)
    pg.wait_for_timeout(300)


def doc_links(pg):
    return pg.eval_on_selector_all("#clDetailCard a",
                                   "els => els.map(a => a.getAttribute('href'))")


def field(pg, label):
    """The input of a labelled field on the Create / Edit screen (v4 gives most
    of them no id; the live layer finds them the same way). Vehicle, transporter,
    LR and the buyer are the invoice's own and are hidden there - what a person
    can change in an edit is the pallets, the date and the driver."""
    return pg.locator("#v-challan .bomgrid .fld",
                      has=pg.locator("label", has_text=label)).locator(
                          "input,select,textarea").first


def begin_edit(pg, cid, mobile="9876543210"):
    """Detail panel -> Edit, and wait until the form holds the challan's own
    driver mobile (filled after the invoice and the pallets have loaded)."""
    open_detail(pg, cid)
    pg.click("#clDetailCard button:has-text('Edit')")
    pg.wait_for_function(
        "document.getElementById('chCreate') && "
        "document.getElementById('chCreate').textContent.indexOf('Save changes') >= 0",
        timeout=10000)
    pg.wait_for_function(
        "(v) => { const f = [...document.querySelectorAll('#v-challan .bomgrid .fld')]"
        ".find(x => x.textContent.trim().indexOf('Driver mobile') === 0);"
        " return f && f.querySelector('input').value === v; }", arg=mobile, timeout=10000)
    pg.wait_for_timeout(800)


def save_edit(pg):
    """Press 'Save changes' and return what the server answered."""
    with pg.expect_response(lambda r: "/edit-save" in r.url, timeout=15000) as ri:
        pg.click("#chCreate")
    return ri.value.json()


def load_and_submit(c, challan_id):
    """Team 3: confirm every pallet on that version, then submit."""
    with store.conn() as (cx, cur):
        nos = [r["box_no"] for r in store.rows(
            cur, "SELECT box_no FROM challan_box WHERE challan_id=%s "
                 "ORDER BY load_order", (challan_id,))]
    for no in nos:
        r = c.post("/api/loading/%d/confirm" % challan_id, json={"box_no": no})
        assert r.status_code == 200, r.get_json()
    r = c.post("/api/loading/%d/submit" % challan_id, json={})
    assert r.status_code == 200, r.get_json()


@test("after an edit and ITS Loading Verification, the challan's Print link names its "
      "suffix and opens the printed challan; the superseded original offers no Print")
def t_edit_then_print():
    c, chid, boxes = seed()
    with H.browser() as b:
        pg = H.open_page(b, role="Super Admin", login_id="edit.ui", wait_ms=1200)
        begin_edit(pg, chid)
        field(pg, "Driver mobile").fill("9111222333")           # a real change
        saved = save_edit(pg)
        assert saved["ok"] and saved["suffix"] == "MA", saved
        fy, seq, new_id = saved["fy"], saved["seq"], saved["challan_id"]
        load_and_submit(c, new_id)

        # the original: no link to an error page, but a way to the replacement
        open_detail(pg, chid)
        assert doc_links(pg) == [], doc_links(pg)
        assert "View the replacement" in pg.inner_text("#clDetailCard")

        # the replacement: every link names its version, and Print really prints
        open_detail(pg, new_id)
        assert doc_links(pg) == ["/challan/%d/%d/print?suffix=MA" % (fy, seq),
                                 "/challan/%d/%d/excel?suffix=MA" % (fy, seq)], doc_links(pg)
        with pg.context.expect_page() as pi:
            pg.click("#clDetailCard a:has-text('Print')")
        pop = pi.value
        pop.wait_for_load_state()
        text = pop.inner_text("body")
        assert saved["no"] in text, text[:300]
        low = text.lower()
        assert "superseded" not in low and "not complete" not in low, text[:300]
        flat = text.replace(" ", "")          # the print groups a mobile: 91112 22333
        assert "9111222333" in flat and "9876543210" not in flat, \
            "the printed challan is not the edited version"
        assert not pg.errors, pg.errors


def said_nothing_changed(pg):
    pg.wait_for_function(
        "((document.getElementById('toast') || {}).textContent || '')"
        ".indexOf('Nothing was changed') >= 0", timeout=8000)
    t = toast_text(pg)
    assert "stays as it is" in t and "no new version" in t, t
    assert "saved" not in t and "superseded" not in t and "dispatched" not in t, \
        "a save that changed nothing was announced as a save: " + t


@test("Edit, change nothing, Save: the answer says nothing was changed, and no new "
      "version is made - the original stays the one issued challan")
def t_untouched_edit_is_nothing():
    c, chid, boxes = seed()
    before = challans()
    with H.browser() as b:
        pg = H.open_page(b, role="Super Admin", login_id="edit.ui", wait_ms=1200)
        begin_edit(pg, chid)
        saved = save_edit(pg)
        assert saved["ok"] and saved["changed"] is False and \
            saved["challan_id"] == chid, saved
        said_nothing_changed(pg)
        assert not pg.errors, pg.errors
    assert challans() == before, "a save with nothing changed wrote to the challans"
    assert [r["status"] for r in challans()] == ["issued"]


@test("a challan dated a day earlier: Edit opens on ITS date, an untouched Save is "
      "still nothing, and a real change keeps that date")
def t_untouched_edit_a_day_later():
    import datetime
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    c, chid, boxes = seed(challan_date=yesterday)
    with H.browser() as b:
        pg = H.open_page(b, role="Super Admin", login_id="edit.ui", wait_ms=1200)
        begin_edit(pg, chid)
        assert field(pg, "Challan date").input_value() == yesterday, \
            "the Edit form opened on today's date, not the challan's own"
        saved = save_edit(pg)
        assert saved["changed"] is False, saved
        said_nothing_changed(pg)
        assert len(challans()) == 1, challans()

        # now a real change: the corrected challan keeps the date it had
        begin_edit(pg, chid)
        field(pg, "Driver mobile").fill("9111222333")
        saved = save_edit(pg)
        assert saved["changed"] is True and saved["suffix"] == "MA", saved
    rows = challans()
    assert [r["status"] for r in rows] == ["superseded", "issued"], rows
    assert rows[1]["challan_date"] == yesterday, rows


@test("a buyer and consignee typed differently from the invoice's survive Edit - "
      "an untouched Save is nothing, and a real change does not re-read them "
      "from the invoice")
def t_edit_keeps_own_buyer_and_consignee():
    c, chid, boxes = seed(
        buyer_name="Typed Buyer Pvt Ltd", buyer_gstin="22AAAAA0000A1Z5",
        consignee_same_as_buyer=False, consignee_name="Site Store",
        consignee_address="Plot 4\nRaipur")
    with H.browser() as b:
        pg = H.open_page(b, role="Super Admin", login_id="edit.ui", wait_ms=1200)
        begin_edit(pg, chid)
        saved = save_edit(pg)
        assert saved["changed"] is False, \
            "an untouched Edit re-read the buyer / consignee from the invoice: %s" % saved
        said_nothing_changed(pg)
        assert len(challans()) == 1, challans()

        begin_edit(pg, chid)
        field(pg, "Driver mobile").fill("9111222333")
        saved = save_edit(pg)
        assert saved["changed"] is True, saved
    new = challans()[-1]
    assert (new["buyer_name"], new["consignee_name"], new["consignee_address"]) == \
        ("Typed Buyer Pvt Ltd", "Site Store", "Plot 4\nRaipur"), new


@test("the selection line ('N boxes - N modules - N KW') describes the pallets "
      "actually ticked: 0 on a fresh screen, the challan's own when an edit opens, "
      "0 again after Cancel edit - never v4's demo '9 boxes - 290 modules' (audit 9 Oct)")
def t_selection_line_is_real():
    c, chid, boxes = seed()
    with H.browser() as b:
        pg = H.open_page(b, role="Super Admin", login_id="edit.sel", wait_ms=1200)
        pg.evaluate("go('challan')")
        pg.wait_for_timeout(1000)
        assert pg.inner_text("#chSel").lower().startswith("0 boxes"), pg.inner_text("#chSel")
        begin_edit(pg, chid)
        line = pg.inner_text("#chSel").lower()
        assert line == "3 boxes · 6 modules · 3.78 kw", line
        pg.evaluate("chAbandonEdit()")
        pg.wait_for_timeout(800)
        assert pg.inner_text("#chSel").lower().startswith("0 boxes"), pg.inner_text("#chSel")
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
