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


@test("the pallet-contents check loads a pallet on Enter - what a scanner sends "
      "after the pallet's QR - not only on the button")
def t_contents_check_enter():
    c = T.setup()
    chid = issued(c, [0, 1], "INV-UI-ENTER")
    box_no = T.box_no_of(chid)
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator")
        pg.evaluate("go('loadver')")
        pg.wait_for_selector("#lvBox", timeout=10000)
        pg.fill("#lvBox", "ICONTRACE|BOX|%s|%s|A|2|2026-10-09" % (box_no, T.MODEL))
        pg.press("#lvBox", "Enter")
        pg.wait_for_selector("#lvCard", state="visible", timeout=5000)
        assert "2 modules" in pg.inner_text("#lvInfo"), pg.inner_text("#lvInfo")
        assert not pg.errors, pg.errors


@test("the challan detail's Verify loading opens THAT challan's loading session "
      "(it called go('loading'), a screen that does not exist, and stayed put)")
def t_challan_detail_verify_loading():
    c = T.setup()
    chid = issued(c, [4, 5], "INV-UI-VERIFY")
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator")
        pg.evaluate("go('challan', document.querySelector('.nav-i[data-v=challan]'))")
        pg.wait_for_timeout(800)
        pg.evaluate("clOpenDetail(%d)" % chid)
        pg.click("#clDetailCard >> text=Verify loading")
        pg.wait_for_selector("#v-loadsession.on", timeout=5000)
        pg.wait_for_function("document.querySelectorAll('#lsRows tr').length === 1", timeout=5000)
        no = c.get("/api/loading/%d" % chid).get_json()["no"]
        assert no in pg.inner_text("#lsSubtitle"), pg.inner_text("#lsSubtitle")
        assert not pg.errors, pg.errors


def listed(pg):
    return pg.evaluate("Array.from(document.querySelectorAll('#ldTableBody tr'))"
                       ".filter(function (r) { return r.style.display !== 'none'; })"
                       ".map(function (r) { return r.cells[0].innerText; })")


def open_list(pg, frm):
    pg.evaluate("go('loadver', document.querySelector('.nav-i[data-v=loadver]'))")
    pg.wait_for_selector("#ldFrom", timeout=8000)
    pg.fill("#ldFrom", frm)
    pg.dispatch_event("#ldFrom", "change")
    pg.wait_for_timeout(900)


@test("the list's count agrees with the rows a search leaves - a search for "
      "a value only the Date column holds hid the other rows while the badge "
      "read '0 of N'")
def t_list_count_badge():
    c = T.setup()
    a = issued(c, [10, 11], "INV-UI-BADGE1")
    issued(c, [12, 13], "INV-UI-BADGE2")
    with store.conn() as (cx, cur):
        cur.execute("UPDATE challan SET challan_date='2026-09-30' WHERE challan_id=%s", (a,))
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator")
        open_list(pg, "2026-09-01")
        assert len(listed(pg)) == 2, listed(pg)
        pg.fill("#v-loading-list [data-role=search]", "2026-09-30")
        pg.wait_for_timeout(300)
        badge = pg.inner_text("#ldCount").lower()
        assert len(listed(pg)) == 1 and badge.startswith("1 of 2"), (listed(pg), badge)
        assert not pg.errors, pg.errors


@test("Reset clears every field: the dates go back to the day the list opened on, "
      "the status to All and the search empty - it reset only the search box")
def t_list_reset():
    c = T.setup()
    issued(c, [14, 15], "INV-UI-RESET")
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator")
        pg.evaluate("go('loadver', document.querySelector('.nav-i[data-v=loadver]'))")
        pg.wait_for_selector("#ldFrom", timeout=8000)
        pg.wait_for_timeout(800)
        opened = (pg.input_value("#ldFrom"), pg.input_value("#ldTo"))
        pg.fill("#ldFrom", "2026-09-01")
        pg.dispatch_event("#ldFrom", "change")
        pg.wait_for_timeout(800)
        pg.select_option("#ldStatusFilter", "pending")
        pg.wait_for_timeout(800)
        pg.fill("#v-loading-list [data-role=search]", "zzz-nothing")
        pg.click("#v-loading-list [data-role=reset]")
        pg.wait_for_timeout(900)
        assert (pg.input_value("#ldFrom"), pg.input_value("#ldTo")) == opened,             ((pg.input_value("#ldFrom"), pg.input_value("#ldTo")), opened)
        assert pg.input_value("#ldStatusFilter") == "", pg.input_value("#ldStatusFilter")
        assert pg.input_value("#v-loading-list [data-role=search]") == ""
        assert not pg.errors, pg.errors


def open_at(b, when, role="Dispatch Operator"):
    """A signed-in page whose clock reads `when` (IST) from its first script."""
    import auth_test_helper as AUTH
    ctx = b.new_context(viewport={"width": 1500, "height": 950})
    ctx.clock.set_fixed_time(when)
    ctx.add_cookies([{"name": "icon_sid", "value": AUTH.make_session_id(role=role),
                      "domain": "127.0.0.1", "path": "/"}])
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(H.base_url() + "/")
    pg.wait_for_selector("#app.on", timeout=15000)
    pg.wait_for_timeout(800)
    return pg


def stamp(chid, issued_at, challan_date):
    with store.conn() as (cx, cur):
        cur.execute("UPDATE challan SET issued_at=%s, challan_date=%s WHERE challan_id=%s",
                    (issued_at, challan_date, chid))


@test("at 01:00 the list opens on the FACTORY day and shows a challan issued at "
      "23:00 (same C shift) and one issued at 00:30 - counted by when they were "
      "issued (DECISIONS 8); at 11:00 it opens on the new day, and Reset goes back "
      "to it from any filter")
def t_list_factory_day_and_reset():
    import datetime
    c = T.setup()
    late = issued(c, [6, 7], "INV-UI-NIGHT1")
    after_midnight = issued(c, [8, 9], "INV-UI-NIGHT2")
    stamp(late, "2026-10-08T23:00:00", "2026-10-08")
    stamp(after_midnight, "2026-10-09T00:30:00", "2026-10-09")
    nos = {cid: c.get("/api/loading/%d" % cid).get_json()["no"] for cid in (late, after_midnight)}
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    with H.browser() as b:
        pg = open_at(b, datetime.datetime(2026, 10, 9, 1, 0, tzinfo=ist))
        pg.evaluate("go('loadver', document.querySelector('.nav-i[data-v=loadver]'))")
        pg.wait_for_function("document.querySelectorAll('#ldTableBody tr td.mono').length >= 2",
                             timeout=8000)
        assert pg.input_value("#ldFrom") == "2026-10-08" == pg.input_value("#ldTo"),             (pg.input_value("#ldFrom"), pg.input_value("#ldTo"))
        rows = listed(pg)
        assert all(any(n in r for r in rows) for n in nos.values()), (rows, nos)
        # every filter moved, then Reset
        pg.fill("#ldFrom", "2026-09-01")
        pg.select_option("#ldStatusFilter", "pending")
        pg.fill("#v-loading-list [data-role=search]", "zzz-nothing")
        pg.click("#v-loading-list [data-role=reset]")
        pg.wait_for_timeout(900)
        assert pg.input_value("#ldFrom") == "2026-10-08", pg.input_value("#ldFrom")
        assert pg.input_value("#ldStatusFilter") == "", pg.input_value("#ldStatusFilter")
        assert pg.input_value("#v-loading-list [data-role=search]") == ""
        assert len(listed(pg)) == 2, listed(pg)
        # a search on a value only the Date column holds: the badge agrees with the rows
        pg.fill("#v-loading-list [data-role=search]", "2026-10-08")
        pg.wait_for_timeout(300)
        badge = pg.inner_text("#ldCount").lower()
        assert len(listed(pg)) == 1 and badge.startswith("1 of 2"), (listed(pg), badge)
        assert not pg.errors, pg.errors
        pg.context.close()

        pg = open_at(b, datetime.datetime(2026, 10, 9, 11, 0, tzinfo=ist))
        pg.evaluate("go('loadver', document.querySelector('.nav-i[data-v=loadver]'))")
        pg.wait_for_timeout(1200)
        assert pg.input_value("#ldFrom") == "2026-10-09", pg.input_value("#ldFrom")
        assert not [r for r in listed(pg) if r.startswith("IS-")], listed(pg)
        pg.context.close()


@test("the Gate Pass list opens on the factory day too: at 01:00 a gate pass made "
      "at 00:40 (dated the 9th) is on the 8th's list, with that night's dispatch")
def t_gatepass_list_factory_day():
    import datetime
    c = T.setup()
    r = c.post("/api/gatepass", json={"kind": "NRGP", "party": "Unit-1 Stores",
                                      "items": [{"description": "Cell stock", "unit": "Kg", "qty": 4}]})
    assert r.status_code == 200, r.get_json()
    gp_no = r.get_json()["gp_no"]
    with store.conn() as (cx, cur):
        cur.execute("UPDATE gatepass SET created_at='2026-10-09T00:40:00', gp_date='2026-10-09' "
                    "WHERE gp_no=%s", (gp_no,))
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    with H.browser() as b:
        pg = open_at(b, datetime.datetime(2026, 10, 9, 1, 0, tzinfo=ist))
        pg.evaluate("go('gp', document.querySelector('.nav-i[data-v=gp]'))")
        pg.wait_for_timeout(1200)
        assert pg.input_value("#gpLFrom") == "2026-10-08" == pg.input_value("#gpLTo")
        assert gp_no in pg.inner_text("#gpLTableBody"), pg.inner_text("#gpLTableBody")
        pg.fill("#gpLFrom", "2026-09-01")
        pg.evaluate("gpListReset()")
        pg.wait_for_timeout(800)
        assert pg.input_value("#gpLFrom") == "2026-10-08", pg.input_value("#gpLFrom")
        assert not pg.errors, pg.errors
        pg.context.close()


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
