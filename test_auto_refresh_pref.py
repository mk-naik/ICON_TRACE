"""
ICON TRACE - Round 31: live updates on or off, per ACCOUNT.

    python test_auto_refresh_pref.py

Mukesh asked for a switch, and for it to live on the account rather than in
the browser, so it follows the person to any machine they sign in on - the
same way their permissions already do. Default on: nobody who has not asked
for a change gets one.

Round 32 fixes what OFF means. The toggle governs the CHIP: box ON refreshes
the list silently and never chips (a chip is what you show INSTEAD of
refreshing); box OFF does the opposite - it never refreshes the list under the
person, it shows the chip and lets them reload when they choose. So OFF is not
"nothing at all" (Round 31 read it that way): OFF suppresses the SILENT
refresh, and the chip is precisely the OFF affordance. The one thing OFF and
ON share: an open form or popup stands the screen down either way - OFF shows
no chip over a form, ON refreshes only once the form closes.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_autoref_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


WAIT_MS = 14000


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


def signed_in_page(b, login_id, role="Super Admin"):
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    sid = AUTH.make_session_id(role=role, login_id=login_id)
    ctx.add_cookies([{"name": "icon_sid", "value": sid,
                      "domain": "127.0.0.1", "path": "/"}])
    pg.goto(H.base_url() + "/")
    pg.wait_for_selector("#app.on", timeout=20000)
    pg.wait_for_timeout(1500)
    return ctx, pg


def issue_gatepass(pg, party):
    ok = pg.evaluate("""(party) => fetch('/api/gatepass', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({kind: 'RGP', party: party,
                                  description: 'pref test', qty: 1})
          }).then(function (r) { return r.json(); })
            .then(function (d) { return d.ok === true || !!d.gp_no; })""", party)
    assert ok, "the save did not go through"


def open_pallet(pg):
    ok = pg.evaluate("""() => fetch('/api/box/open', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({grade: 'A', model: 'ISEN625-G12R', capacity: 4})
          }).then(function (r) { return r.json(); })
            .then(function (d) { return !!d.box_id; })""")
    assert ok, "the pallet did not open"


# --------------------------------------------------------------------------
# the setting itself
# --------------------------------------------------------------------------

@test("a fresh account is on, without anybody setting it - and the value "
     "comes back in the session payload the page already reads")
def t_default_on():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c, role="FQC Operator", login_id="brand.new")
    assert c.get("/api/session").get_json()["auto_refresh"] is True
    with store.conn() as (cx, cur):
        assert icon_auth.get_auto_refresh(cur, "brand.new") is True


@test("it is stored on the ACCOUNT, so it follows the person to another "
     "machine and survives signing out and back in")
def t_follows_the_account():
    fresh()
    first = APP.app.test_client()
    AUTH.test_login(first, role="Super Admin", login_id="travels")
    assert first.post("/api/session/auto-refresh",
                      json={"on": False}).get_json()["auto_refresh"] is False
    first.post("/logout")

    # a different session for the same person - a second machine, or after
    # signing back in
    second = APP.app.test_client()
    AUTH.test_login(second, role="Super Admin", login_id="travels")
    assert second.get("/api/session").get_json()["auto_refresh"] is False

    # and nobody else's account moved with it
    other = APP.app.test_client()
    AUTH.test_login(other, role="Super Admin", login_id="someone.else")
    assert other.get("/api/session").get_json()["auto_refresh"] is True
    print("      off survived a sign-out; another account unaffected")


@test("the switch is self only - it reads the login from the session, so "
     "there is no way to set it for anybody else - and needs a session")
def t_self_only():
    fresh()
    anon = APP.app.test_client()
    assert anon.post("/api/session/auto-refresh", json={"on": False}).status_code == 401

    me = APP.app.test_client()
    AUTH.test_login(me, role="Super Admin", login_id="me.only")
    victim = APP.app.test_client()
    AUTH.test_login(victim, role="FQC Operator", login_id="victim")
    # a login_id in the body is simply not read
    r = me.post("/api/session/auto-refresh",
                json={"on": False, "login_id": "victim", "user": "victim"})
    assert r.status_code == 200, r.get_json()
    assert victim.get("/api/session").get_json()["auto_refresh"] is True, \
        "one account changed another's setting"
    assert me.get("/api/session").get_json()["auto_refresh"] is False
    assert me.post("/api/session/auto-refresh", json={}).status_code == 400


# --------------------------------------------------------------------------
# what it does on screen
# --------------------------------------------------------------------------

@test("OFF suppresses the SILENT refresh of a list and shows the chip instead "
     "- box off is the chip, not 'nothing at all' (Round 32 reverses Round 31)")
def t_off_is_chip_not_silent():
    fresh()
    with H.browser() as b:
        ctxA, pgA = signed_in_page(b, "sa.saver")
        ctxB, pgB = signed_in_page(b, "sa.off")
        try:
            assert pgB.evaluate("USER.auto_refresh") is True
            pgB.evaluate("""() => fetch('/api/session/auto-refresh', {
                  method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({on: false})
                }).then(function (r) { return r.json(); })
                  .then(function (d) { USER.auto_refresh = d.auto_refresh; })""")
            pgB.wait_for_timeout(600)
            assert pgB.evaluate("USER.auto_refresh") is False

            # a dashboard that WOULD refresh itself silently with the box on:
            # off, it must NOT refetch, and must show the chip instead.
            pgB.evaluate("go('packdash')")
            pgB.wait_for_timeout(900)
            pgB.evaluate("""() => { window.__loads = 0;
                var real = window.fetch;
                window.fetch = function (u) {
                  if (String(u).indexOf('/api/boxes') >= 0) window.__loads++;
                  return real.apply(this, arguments); }; }""")
            open_pallet(pgA)
            pgB.wait_for_selector("#chgChip.on", timeout=WAIT_MS)
            assert pgB.evaluate("window.__loads") == 0, \
                "off: the list refreshed silently instead of chipping"

            # a working list too: off, gp-list shows the chip, never refetches
            pgB.evaluate("if (window.hideChangeChip) hideChangeChip()")
            pgB.evaluate("go('gp-list')")
            pgB.wait_for_timeout(900)
            before = pgB.inner_text("#gpLTableBody")
            issue_gatepass(pgA, "CHIP WHEN OFF")
            pgB.wait_for_selector("#chgChip.on", timeout=WAIT_MS)
            assert "CHIP WHEN OFF" not in pgB.inner_text("#gpLTableBody"), \
                "off: the list refreshed silently instead of chipping"
            assert pgB.errors == [], pgB.errors
            print("      off: chip shown on both a dashboard and a list, 0 silent refreshes")
        finally:
            ctxA.close(); ctxB.close()


@test("the checkbox is on the profile card, ticked by default, and saves "
     "the moment it is ticked - no separate Save step")
def t_checkbox_on_profile_card():
    fresh()
    with H.browser() as b:
        ctx, pg = signed_in_page(b, "sa.card")
        try:
            pg.click("#av")                       # open the profile menu
            pg.wait_for_timeout(400)
            box = pg.locator("#umAutoRefresh")
            assert box.count() == 1, "no switch on the profile card"
            assert box.is_checked(), "it did not open ticked"
            assert "Update screens when others save" in pg.inner_text(".um-pref")

            box.uncheck()
            pg.wait_for_timeout(1500)
            # persisted, with no other action taken
            with store.conn() as (cx, cur):
                assert icon_auth.get_auto_refresh(cur, "sa.card") is False
            assert pg.evaluate("USER.auto_refresh") is False
            # and back on again
            box.check()
            pg.wait_for_timeout(1500)
            with store.conn() as (cx, cur):
                assert icon_auth.get_auto_refresh(cur, "sa.card") is True
            assert pg.errors == [], pg.errors
            print("      ticked by default; unticking persisted immediately")
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
