"""
ICON TRACE - a name with an apostrophe still works the buttons it is on.

    python test_inline_args_ui.py      (needs Playwright + Chromium)

THE RULE THIS FILE DEFENDS

    A value put inside an inline handler (onclick="openModules({...})",
    onclick="usrEditPerms('...')") reaches the function whole. The browser
    decodes the attribute's entities BEFORE it parses the script, so fqcEsc()
    inside '...' gave the apostrophe back: "Shree Sai's Solar" - an indent for
    a customer not in the master keeps the text as typed - ended the string,
    Management Overview's View N threw "Unexpected identifier 's'" and opened
    nothing; a login ID with an apostrophe did the same to every button on its
    Users row. A name built for it would have run as script (audit A6, 10 Oct).
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

APP = H.APP
_results = []
CUST = "Shree Sai's Solar"
LOGIN = "o'neil.fqc"


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def seed():
    store.wipe()
    AUTH.ensure_auth_schema()
    today = clock.today().isoformat()
    with store.conn() as (cx, cur):
        for i in range(4):
            s = "ICON625R12A10%05d" % (i + 1)
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": 625, "customer": CUST, "dcr": "DCR",
                "format_version": 2, "date_produced": today, "shift": 1,
                "sequence": i + 1, "state": "planned"})
            db.record_fqc(cur, s, "pass", evidence={"pmax": 630, "ss_state": "OK",
                          "el": "OK", "proposed": "pass"}, decided_by="t", mode="live")
    AUTH.make_user("FQC Operator", login_id=LOGIN, name="Neil O'Brien")


@test("Management Overview: View N for a customer whose name has an apostrophe "
      "opens its module list, with no page error")
def t_mgmt_view_n():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, "mgmt", wait_ms=1500)
        pg.select_option("#mgCust", label=CUST)
        pg.wait_for_timeout(1500)
        btn = pg.locator("#mgShiftRows button").first
        assert btn.count(), "no View button for the customer"
        btn.click()
        pg.wait_for_timeout(1500)
        assert not pg.errors, pg.errors
        assert pg.evaluate("!!document.querySelector('#mdl.on')"), "the module list did not open"
        rows = pg.evaluate("document.querySelectorAll('#mdl.on tbody tr').length")
        assert rows == 4, rows


@test("Users: the row of a login ID with an apostrophe opens its permission "
      "editor from its own menu, with no page error")
def t_users_row():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, wait_ms=1200)
        pg.evaluate("go('admin')")
        pg.wait_for_timeout(1200)
        pg.locator("#adTabs button", has_text="Users").first.click()
        pg.wait_for_timeout(800)
        kebab = pg.locator('.usr-kebab[aria-label="Actions for %s"]' % LOGIN)
        assert kebab.count(), "no row for %s" % LOGIN
        kebab.first.click()
        pg.wait_for_timeout(300)
        pg.locator(".usr-menu.on button", has_text="Edit permissions").first.click()
        pg.wait_for_timeout(1200)
        assert not pg.errors, pg.errors
        title = pg.evaluate("(document.querySelector('#permEd h3')||{}).textContent || ''")
        assert LOGIN in title, title


@test("Needs Review: Quality grades a custom serial with an apostrophe - GY opens "
      "its prompt and Record GY records it, with no page error")
def t_review_grade_apostrophe():
    serial = "AB'CD7001"           # a custom serial: any printable token, not ICON-shaped
    seed()
    with store.conn() as (cx, cur):
        store.insert(cur, "serial", {
            "serial": serial, "build_instance": 1, "model": "ISEN625-G12R",
            "wattage": 625, "customer": CUST, "dcr": "DCR", "format_version": 0,
            "date_produced": clock.today().isoformat(), "shift": 1,
            "sequence": 1, "state": "planned"})
        db.record_fqc(cur, serial, "reject", evidence={"pmax": 630, "ss_state": "OK",
                      "el": "OK", "proposed": "reject"}, decided_by="t", mode="live",
                      defect="DF-CELLCRACK")
    with H.browser() as b:
        pg = H.open_page(b, view="review", wait_ms=1500, role="Quality")
        row = pg.locator("tr", has_text=serial)
        assert row.count(), "the reject is not listed on Needs Review"
        row.first.locator("button", has_text="GY").first.click()
        pg.wait_for_timeout(600)
        assert not pg.errors, pg.errors
        pg.fill("#revWhy", "edge chip, cosmetic")
        pg.locator("button", has_text="Record GY").first.click()
        pg.wait_for_timeout(1200)
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        s = store.one(cur, "SELECT state, grade FROM serial WHERE serial=%s", (serial,))
    assert (s["state"], s["grade"]) == ("graded", "GY"), s


@test("Stock & Dispatch: a recent challan's link hands qTry its number whole, even "
      "one with an apostrophe (the number is server-built; the answer is doctored "
      "here to prove the button is safe)")
def t_disp_challan_link():
    odd = "IS-X'1"
    seed()

    def doctor(route):
        resp = route.fetch()
        data = resp.json()
        data["recent"] = [{"challan_no": odd, "status": "issued", "gp_no": None,
                           "challan_date": "2026-10-13", "customer_name": "X",
                           "vehicle_no": "CG04", "qty": 1, "kw": 0.6}]
        route.fulfill(response=resp, json=data)

    with H.browser() as b:
        pg = H.open_page(b, wait_ms=1200)
        pg.route("**/api/stock_dispatch*", doctor)
        pg.evaluate("go('disp')")
        pg.wait_for_timeout(1500)
        btn = pg.locator("#v-disp button.lnk", has_text=odd)
        assert btn.count(), "the doctored row is not on Stock & Dispatch"
        pg.evaluate("window.__asked = []; window.qTry = function (v) { window.__asked.push(v); };")
        btn.first.click()
        pg.wait_for_timeout(300)
        assert not pg.errors, pg.errors
        # (the page's own click delegation also calls qTry once, with nothing)
        asked = [v for v in pg.evaluate("window.__asked") if v]
        assert asked == [odd], asked


def main():
    width = max(len(n) for n, _ in _results)
    failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %-*s" % (width, name))
            except Exception:
                failed += 1
                print("  FAIL  %-*s" % (width, name))
                traceback.print_exc()
    finally:
        H.cleanup()
    print("\n%d passed, %d failed" % (len(_results) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
