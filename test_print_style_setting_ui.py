"""
ICON TRACE - the "Printed documents format" setting, on the running page.

    python test_print_style_setting_ui.py        (needs Playwright + Chromium)

Management may prefer the plant's original layout to the redesign, so which
format the Dispatch Challan cum Gate Pass and the Gate Pass print in is a
setting (Admin > Stations & sources > Plant). Seen here the way a person sees it:
it shows what is set, a Super Admin's Save stores it, and an Admin - who can
read but not write settings - is told so instead of being told "saved".
"""

import os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_printstyle_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import db                                                    # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def world():
    store.wipe()
    AUTH.ensure_auth_schema()


def stored():
    with store.conn() as (cx, cur):
        return db.get_config(cur)["print_style"]


def settings_tab(b, role):
    pg = H.open_page(b, "admin", wait_ms=1500, role=role)
    pg.toasts = []
    pg.expose_function("__toastSeen", lambda t: pg.toasts.append(t))
    pg.evaluate("""() => { var t = window.toast; window.toast = function (m) {
        window.__toastSeen(String(m)); return t.apply(this, arguments); }; }""")
    pg.click('#adTabs button[onclick*="\'stations\'"]')
    pg.wait_for_selector("#s_print_style", timeout=8000)
    return pg


@test("the setting shows the redesign by default, a Super Admin can switch to the original, "
      "and the page then shows what is stored")
def t_super_admin_switches():
    world()
    assert stored() == "premium"
    with H.browser() as b:
        pg = settings_tab(b, "Super Admin")
        opts = pg.eval_on_selector_all("#s_print_style option", "els => els.map(e => e.value)")
        assert opts == ["premium", "classic"], opts
        assert pg.input_value("#s_print_style") == "premium"
        pg.select_option("#s_print_style", "classic")
        pg.click('#v-settings button[onclick="setSave()"]')
        pg.wait_for_timeout(1200)
        assert stored() == "classic", "Save did not store the format"
        assert not pg.errors, pg.errors
        # the page, redrawn from the server, shows it
        pg.reload()
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.evaluate("go('admin')")
        pg.wait_for_timeout(800)
        pg.click('#adTabs button[onclick*="\'stations\'"]')
        pg.wait_for_selector("#s_print_style", timeout=8000)
        assert pg.input_value("#s_print_style") == "classic"
        pg.close()


@test("an Admin can see the setting but cannot change it: the control is locked, with the reason")
def t_admin_sees_it_locked():
    world()
    with H.browser() as b:
        pg = settings_tab(b, "Admin")
        assert pg.input_value("#s_print_style") == "premium", "an Admin cannot even see what is set"
        assert pg.is_disabled("#s_print_style"),             "the format is editable by an Admin, whose Save the server refuses"
        assert "Super Admin" in (pg.get_attribute("#s_print_style", "title") or ""),             "the locked control does not say who may change it"
        assert stored() == "premium"
        pg.close()
    # and the server holds the same line when asked directly
    c = H.APP.app.test_client()
    AUTH.test_login(c, role="Admin", login_id="admin1")
    r = c.post("/api/settings", json={"print_style": "classic"})
    assert r.status_code == 403 and stored() == "premium", (r.status_code, stored())


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
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
