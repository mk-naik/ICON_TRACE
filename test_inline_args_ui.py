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
