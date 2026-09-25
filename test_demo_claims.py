"""
ICON TRACE - no button claims to have saved what it did not.

    python test_demo_claims.py

v4 shipped placeholder buttons whose whole action is a toast announcing
success - "Draft saved.", "Document cancelled.", "Shift events submitted."
- with nothing sent anywhere. Found live on 25 Sep, in operator workflows:
Planning's and Production Entry's "Save as draft", Planning's "Copy from
last batch", Loss's "Submit shift", and on the Admin screen "Cancel
document", "Sign off review" and "+ Add type". They are disabled now, with
the truth on hover. The toasts that only explain something (Grade rules'
"+ New version", Defect codes' "+ Add code") are honest and stay live.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_demo_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


NOT_BUILT = "Not built yet — this does not save anything."
# (screen, button that opens its form or None, label of the claiming button)
LIVE_CLAIMS = [("plan", "New plan", "Save as draft"),
               ("plan", "New plan", "Copy from last batch"),
               ("prodentry", "New production entry", "Save as draft"),
               ("loss", "Record downtime event", "Submit shift")]
ADMIN_CLAIMS = [("cancel", "Cancel document"), ("access", "Sign off review"),
                ("mach", "+ Add type")]
ADMIN_HONEST = [("grade", "+ New version"), ("defects", "+ Add code")]
CLAIM_WORDS = ["Draft saved.", "Materials copied from", "Shift events submitted",
               "Access review recorded", "Document cancelled.", "Add-machine form opens here."]


def page(b):
    pg = H.open_page(b, wait_ms=1500, role="Super Admin", login_id="sa1")
    pg.toasts = []
    pg.expose_function("__toastSeen", lambda t: pg.toasts.append(t))
    pg.evaluate("""() => { var t = window.toast; window.toast = function (m) {
        window.__toastSeen(String(m)); return t.apply(this, arguments); }; }""")
    return pg


def admin_tab(pg, pane):
    pg.click('#adTabs button[onclick*="\'%s\'"]' % pane)
    pg.wait_for_timeout(300)


@test("nothing on the page can still raise a toast claiming a save that did "
     "not happen - no element carries one of those handlers any more")
def t_no_claim_handlers_left():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = page(b)
        left = pg.evaluate("""(words) => Array.prototype.filter.call(
            document.querySelectorAll('[onclick^="toast("]'), function (e) {
              var oc = e.getAttribute('onclick');
              return words.some(function (w) { return oc.indexOf("toast('" + w) === 0; });
            }).map(function (e) { return e.getAttribute('onclick').slice(0, 60); })""", CLAIM_WORDS)
        assert left == [], left
        got = pg.evaluate("""() => Array.prototype.map.call(
            document.querySelectorAll('[data-demo-claim]'), function (e) {
              var s = e.closest('section.view');
              return (s ? s.id : '?') + ' / ' + e.textContent.trim(); }).sort()""")
        want = sorted(["v-plan / Save as draft", "v-plan / Copy from last batch",
                       "v-prodentry / Save as draft", "v-loss / Submit shift",
                       # the invoice parser's "PDF stored against this
                       # challan" - nothing takes it over; it stored nothing
                       "v-invoice-parser / Store PDF only",
                       "v-admin / Sign off review", "v-admin / + Add type",
                       "v-admin / Cancel document"])
        assert got == want, "disabled placeholders changed:\n  got  %s\n  want %s" % (got, want)
        n = len(got)
        # ...and a button the live layer took over at sign-in is NOT one of
        # them: Challan's "Save as draft" was v4's "Saved as draft." toast,
        # and is now the real draft save. The first version of this fix ran
        # at page load, before that takeover, and disabled it.
        pg.evaluate("go('challan')"); pg.wait_for_timeout(800)
        # (it may be disabled by the Challan screen itself on an empty form -
        # what matters is that it is not marked as a placeholder)
        real = pg.locator("#chDraftBtn")
        assert real.get_attribute("data-demo-claim") is None, "the real draft save was neutralised"
        assert real.get_attribute("title") != NOT_BUILT
        assert real.get_attribute("onclick") is None
        assert pg.errors == [], pg.errors
        print("      %d placeholder buttons disabled, 0 claim handlers left" % n)


@test("in the operator forms - Planning, Production Entry, Loss - each claiming "
     "button is visible, disabled, says why, and pressing it claims nothing")
def t_operator_forms():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = page(b)
        for screen, opener, label in LIVE_CLAIMS:
            pg.evaluate("go(%r)" % screen); pg.wait_for_timeout(600)
            btn = pg.locator("#v-%s [data-demo-claim]" % screen, has_text=label).first
            if not btn.is_visible():         # the form it lives in is still closed
                pg.locator("#v-%s button" % screen, has_text=opener).first.click()
                pg.wait_for_timeout(500)
            assert btn.is_visible(), (screen, label)
            assert btn.is_disabled(), (screen, label)
            assert btn.get_attribute("title") == NOT_BUILT, (screen, label)
            btn.click(force=True); pg.wait_for_timeout(200)
        assert not [t for t in pg.toasts if any(w in t for w in CLAIM_WORDS)], pg.toasts
        assert pg.errors == [], pg.errors


@test("on the Admin screen, Cancel document, Sign off review and + Add type "
     "are disabled with the reason; the two explanatory buttons still explain")
def t_admin_buttons():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = page(b)
        pg.evaluate("go('admin')"); pg.wait_for_timeout(800)
        for pane, label in ADMIN_CLAIMS:
            admin_tab(pg, pane)
            btn = pg.locator("#ad-%s button" % pane, has_text=label).first
            assert btn.is_disabled() and btn.get_attribute("title") == NOT_BUILT, (pane, label)
        for pane, label in ADMIN_HONEST:
            admin_tab(pg, pane)
            btn = pg.locator("#ad-%s button" % pane, has_text=label).first
            assert btn.is_enabled(), (pane, label)
            btn.click(); pg.wait_for_timeout(200)
        assert len(pg.toasts) == 2, pg.toasts
        assert not [t for t in pg.toasts if any(w in t for w in CLAIM_WORDS)], pg.toasts
        print("      explanatory toasts still shown: %s" % [t[:40] for t in pg.toasts])


# --------------------------------------------------------------------------

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
                traceback.print_exc()
                failed += 1
    finally:
        H.cleanup()
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
