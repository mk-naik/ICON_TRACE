"""
ICON TRACE - Round 33: a refresh returns you to the screen you were on.

    python test_hash_route.py

Every screen lives at one URL (/), so before this round a refresh reloaded /,
which always booted to the dashboard - the person lost their place AND paid for
the dashboard's full query load every time, even landing somewhere else. This
round records the screen in the URL hash (#challan-list, #indent) and reads it
back on load.

Decided and pinned here:
  * REFRESH-RETURN only. The hash never leaves the browser; it carries only a
    screen id; it is validated through the SAME can() gate the nav uses, so an
    unknown or unviewable hash falls back to home (the open-redirect defence in
    miniature).
  * SCREEN only, not record, and NOT in-progress form state - a half-typed form
    is gone after a refresh, and that is accepted.
  * The efficiency win: a refresh onto a non-dashboard runs only that screen's
    load, NOT the dashboard's query load (prod/dashboard, fqc/dashboard,
    stock_dispatch). Pinned as a test below.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_hash_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


DASH_ENDPOINTS = ["/api/prod/dashboard", "/api/fqc/dashboard", "/api/stock_dispatch"]


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


def signed_in_page(b, role="Super Admin", login_id="sa.hash", hashfrag=""):
    """A page in its own context. `hashfrag` (e.g. '#search') is appended to the
    URL, so the page loads exactly as a refresh onto that screen would."""
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.errors = []
    pg.reqs = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("request", lambda r: pg.reqs.append(r.url))
    sid = AUTH.make_session_id(role=role, login_id=login_id)
    ctx.add_cookies([{"name": "icon_sid", "value": sid,
                      "domain": "127.0.0.1", "path": "/"}])
    pg.goto(H.base_url() + "/" + hashfrag)
    pg.wait_for_selector("#app.on", timeout=20000)
    pg.wait_for_timeout(1500)
    return ctx, pg


def shown(pg):
    return (pg.evaluate("(document.querySelector('.view.on')||{}).id") or "").replace("v-", "")


def api_paths(pg):
    return sorted({"/api/" + u.split("/api/", 1)[1].split("?")[0]
                   for u in pg.reqs if "/api/" in u})


# --------------------------------------------------------------------------
# 1. a refresh comes back to the same screen - list, dashboard, form-bearing
# --------------------------------------------------------------------------

@test("navigate to a screen, refresh, and the SAME screen is shown - proved on "
     "a list (challan-list), a dashboard (mgmt) and a form-bearing screen "
     "(prodentry); the form's half-entered state is gone, which is expected")
def t_refresh_returns_to_screen():
    fresh()
    with H.browser() as b:
        ctx, pg = signed_in_page(b)
        try:
            # a list screen
            pg.evaluate("go('challan-list')")
            pg.wait_for_timeout(500)
            assert pg.evaluate("location.hash") == "#challan-list", \
                pg.evaluate("location.hash")
            pg.reload()
            pg.wait_for_selector("#app.on", timeout=20000)
            pg.wait_for_timeout(1200)
            assert shown(pg) == "challan-list", \
                "a list did not survive a refresh: %r" % shown(pg)

            # a dashboard
            pg.evaluate("go('mgmt')")
            pg.wait_for_timeout(500)
            pg.reload()
            pg.wait_for_selector("#app.on", timeout=20000)
            pg.wait_for_timeout(1200)
            assert shown(pg) == "mgmt", \
                "a dashboard did not survive a refresh: %r" % shown(pg)

            # a form-bearing screen: put a value in the form, refresh - the
            # SCREEN comes back; the value does not (form recovery is out of
            # scope, deliberately). .value is set directly rather than through
            # fill(), which needs the field on screen; either way it proves the
            # reload is a fresh screen, not a restored one.
            pg.evaluate("go('prodentry')")
            pg.wait_for_timeout(500)
            pg.evaluate("var e = document.getElementById('peFrom'); "
                        "if (e) e.value = 'ICON590G1202129999';")
            pg.reload()
            pg.wait_for_selector("#app.on", timeout=20000)
            pg.wait_for_timeout(1200)
            assert shown(pg) == "prodentry", \
                "a form screen did not survive a refresh: %r" % shown(pg)
            assert pg.evaluate("(document.getElementById('peFrom')||{}).value") \
                != "ICON590G1202129999", \
                "the half-entered form value came back - not what this feature does"
            assert pg.errors == [], pg.errors
            print("      refresh returned to challan-list, mgmt and prodentry; "
                  "form state gone as expected")
        finally:
            ctx.close()


# --------------------------------------------------------------------------
# 2. the efficiency claim - a hash refresh skips the dashboard's query load
# --------------------------------------------------------------------------

@test("a refresh onto a non-dashboard (#search) does NOT call the dashboard's "
     "own data endpoints; a refresh onto #mgmt does - the efficiency claim")
def t_hash_refresh_skips_dashboard_load():
    fresh()
    with H.browser() as b:
        ctxS, pgS = signed_in_page(b, login_id="sa.search", hashfrag="#search")
        try:
            assert shown(pgS) == "search", shown(pgS)
            fired = [d for d in DASH_ENDPOINTS if d in api_paths(pgS)]
            assert fired == [], \
                "a refresh onto #search ran the dashboard's query load: %s" % fired
            assert pgS.errors == [], pgS.errors
            print("      #search refresh: dashboard endpoints NOT called -> %s"
                  % ([d for d in DASH_ENDPOINTS if d in api_paths(pgS)]))
        finally:
            ctxS.close()

        ctxM, pgM = signed_in_page(b, login_id="sa.mgmt", hashfrag="#mgmt")
        try:
            assert shown(pgM) == "mgmt", shown(pgM)
            fired = sorted(d for d in DASH_ENDPOINTS if d in api_paths(pgM))
            assert fired == sorted(DASH_ENDPOINTS), \
                "a refresh onto #mgmt did not run the dashboard load: %s" % fired
            print("      #mgmt refresh: dashboard endpoints called -> %s" % fired)
        finally:
            ctxM.close()


# --------------------------------------------------------------------------
# 3. an unknown hash lands on home, not an error
# --------------------------------------------------------------------------

@test("an unknown hash (#nonsense) on load falls back to the home screen, no "
     "error, no blank screen")
def t_unknown_hash_goes_home():
    fresh()
    with H.browser() as b:
        ctx, pg = signed_in_page(b, login_id="sa.bad", hashfrag="#nonsense")
        try:
            s = shown(pg)
            assert s and s != "nonsense", "an unknown hash was acted on: %r" % s
            # Super Admin's home is a real screen (mgmt); the hash was rewritten
            # to it, so a further refresh is stable.
            assert pg.evaluate("location.hash") in ("#mgmt", ""), \
                pg.evaluate("location.hash")
            assert pg.errors == [], pg.errors
            print("      #nonsense -> home (%s), no error" % s)
        finally:
            ctx.close()


# --------------------------------------------------------------------------
# 4. a hash for a screen the account cannot view lands on home, not a 403
# --------------------------------------------------------------------------

@test("a hash for a screen this account cannot view (a restricted, "
     "Dashrath-shaped account, hash to #mgmt) lands on its home - not a 403, "
     "not a blank screen - through the SAME can() gate the nav uses")
def t_unviewable_hash_goes_home():
    fresh()
    # a restricted account: it may view only Search and FQC Entry, nothing else
    AUTH.make_user(role="FQC Operator", login_id="restricted")
    with store.conn() as (cx, cur):
        perms = {sid: {"view": False, "write": False} for sid in icon_auth.SCREEN_IDS}
        perms["search"] = {"view": True, "write": False}
        perms["fqc"] = {"view": True, "write": True}
        icon_auth.set_screen_perms(cur, "cli", "restricted", perms)
    with H.browser() as b:
        ctx, pg = signed_in_page(b, role="FQC Operator", login_id="restricted",
                                 hashfrag="#mgmt")
        try:
            s = shown(pg)
            assert s != "mgmt", "a hash forced an account onto a screen it cannot view"
            assert s in ("search", "fqc"), \
                "did not land on a viewable home: %r" % s
            # it never even asked the server for the dashboard it cannot see
            assert not any(d in api_paths(pg) for d in DASH_ENDPOINTS), \
                "the unviewable hash still fetched the dashboard: %s" % api_paths(pg)
            assert pg.errors == [], pg.errors
            print("      restricted account + #mgmt -> %s (its home), no 403" % s)
        finally:
            ctx.close()


# --------------------------------------------------------------------------
# 5. the Back button does not walk backwards through visited screens
# --------------------------------------------------------------------------

@test("navigating between screens uses replaceState, so the history does not "
     "grow per screen and the Back button does not walk backwards through them")
def t_back_does_not_walk_screens():
    fresh()
    with H.browser() as b:
        ctx, pg = signed_in_page(b)
        try:
            start_len = pg.evaluate("history.length")
            for screen in ["challan-list", "gp-list", "prodentry", "mgmt", "search"]:
                pg.evaluate("go('%s')" % screen)
                pg.wait_for_timeout(250)
            end_len = pg.evaluate("history.length")
            assert end_len == start_len, \
                "history grew from %d to %d - navigation is stacking Back entries" \
                % (start_len, end_len)
            # and the hash tracked the last screen
            assert pg.evaluate("location.hash") == "#search", pg.evaluate("location.hash")
            assert pg.errors == [], pg.errors
            print("      5 in-app navigations, history.length stayed %d" % end_len)
        finally:
            ctx.close()


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
