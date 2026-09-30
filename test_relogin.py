"""
ICON TRACE - signing in AGAIN on a page that has already been in the app.

    python test_relogin.py        (needs Playwright + Chromium)

Reported by Mukesh: the session times out, the page says "sign in again", he
signs in, and gets "Signed in, but the app's data could not be loaded" - and a
plain refresh then loads it properly. Only Admin and Super Admin.

What it was: v4's initAll() runs on every sign-in and reaches cancelCheck(),
which reads v4's own Cancel-document inputs. The live layer replaces that pane
(Round 34), so on a SECOND run in the same page those inputs were gone, the
call threw, and enterApp()'s one catch-all reported every exception as a data
problem. A refresh starts from v4's own markup, which is why it "fixed" it.

What this defends, in a real browser:

  1. A real idle timeout, then signing in again on the same page, opens the
     app - as Super Admin (authenticator code), the account it was reported on.
  2. The same after an explicit sign-out, for Admin as well.
  3. If some OTHER re-entry problem ever appears, the page reloads once by
     itself (the path that always worked) instead of stranding the person.
  4. A permanent failure to build the screens says so - it does not claim the
     data could not be loaded - and does not reload in a loop.
  5. A genuine failure to fetch /api/boot still says the data could not be
     loaded (that message is true there).
"""

import os, re, sys, tempfile, time, traceback

# A 25-second window, so a REAL idle expiry is testable without waiting.
os.environ["ICON_SESSION_SECONDS"] = "25"
os.environ["ICON_SESSION_SECONDS_ADMIN"] = "25"

import ui_harness as H                                     # noqa: E402 (sets the DB path)
import store                                               # noqa: E402
import icon_auth                                           # noqa: E402
import auth_test_helper as AUTH                            # noqa: E402

icon_auth.SESSION_WINDOW_SHORT = 25
icon_auth.SESSION_WINDOW_LONG = 25

REPO = os.path.dirname(os.path.abspath(__file__))
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


PASSWORD = "CorrectHorse99"
ACCOUNTS = {}          # role -> (login_id, totp secret or None)
ALL_ROLES = ("Super Admin", "Admin", "Production Incharge", "FQC Operator")


def seed(*roles):
    """One real account per role, made once - wiping the file between roles
    fails on Windows while the server still has it open. Admin and Super
    Admin sign in with an authenticator code, everyone else with a password:
    the credential is chosen by role, as in production."""
    for _ in range(30):                       # a request may still be finishing
        try:
            store.wipe()
            break
        except PermissionError:
            time.sleep(0.5)
    AUTH.ensure_auth_schema()
    key = os.path.join(os.path.dirname(store.DB_PATH), ".icon_totp_key")
    if not os.path.exists(key):
        icon_auth.create_key()
    icon_auth.COOLDOWN_STEPS = ()
    ACCOUNTS.clear()
    for role in (roles or ALL_ROLES):
        login_id = "relogin." + role.lower().replace(" ", "")
        if role in ("Admin", "Super Admin"):
            AUTH.make_user(role, login_id=login_id, name="Relogin " + role,
                           station="FQC-01")
            ACCOUNTS[role] = (login_id, AUTH.provision_totp(login_id))
        else:
            with store.conn() as (cx, cur):
                cur.execute(
                    "INSERT INTO app_user (login_id, display_name, role, station, "
                    "pw_hash, created_at, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (login_id, "Relogin " + role, role, "FQC-01",
                     icon_auth.hash_pw(PASSWORD), 1000000, "test"))
                icon_auth.set_screen_perms(cur, "cli", login_id,
                                           icon_auth.default_perms_for_role(role))
            ACCOUNTS[role] = (login_id, None)


def credential(role):
    """What the person types. A code is good once per 30 s step (the replay
    guard), so every sign-in is given one that has never been used - exactly
    what a fresh code from the app is."""
    login_id, secret = ACCOUNTS[role]
    if secret is None:
        return PASSWORD
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET totp_last_step=0 WHERE login_id=%s",
                    (login_id,))
    return AUTH.totp_code(secret)


def js_source():
    with open(os.path.join(REPO, "static", "icon_live.js"), encoding="utf-8") as fh:
        return fh.read()


def open_signed_in(b, role="Super Admin", extra_js=None):
    """A page that has signed in through the real form and is on #fqc."""
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.errors, pg.navs = [], []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("framenavigated",
          lambda f: pg.navs.append(f.url) if f == pg.main_frame else None)
    if extra_js:
        body = js_source() + "\n" + extra_js
        pg.route(re.compile(r".*/static/icon_live\.js.*"),
                 lambda r: r.fulfill(status=200, body=body,
                                     content_type="application/javascript"))
    pg.goto(H.base_url() + "/")
    pg.wait_for_selector("#liLoginId", timeout=20000)
    sign_in(pg, role)
    pg.wait_for_selector("#app.on", timeout=20000)
    pg.wait_for_timeout(1200)
    pg.evaluate("go('fqc')")
    pg.wait_for_timeout(1200)
    return ctx, pg


def sign_in(pg, role="Super Admin"):
    pg.fill("#liLoginId", ACCOUNTS[role][0])
    pg.fill("#liCredential", credential(role))
    pg.click("#liSubmit")


def app_on(pg):
    return pg.evaluate("document.getElementById('app').classList.contains('on')")


def login_msg(pg):
    return pg.evaluate("(document.getElementById('liMsg') || {}).textContent || ''")


def wait_app_on(pg, ms=15000):
    """Poll for the app to be open. Tolerates the page navigating underneath
    (an automatic reload is one of the things under test)."""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            if app_on(pg):
                return True
        except Exception:
            pass                       # mid-navigation: try again
        time.sleep(0.3)
    try:
        return app_on(pg)
    except Exception:
        return False


# --------------------------------------------------------------------------

@test("Super Admin: the session really times out (no saves), 'sign in again' "
      "is shown, and signing in on the SAME page opens the app - not 'the "
      "app's data could not be loaded'")
def t_timeout_then_relogin_super_admin():
    seed("Super Admin")
    with H.browser() as b:
        ctx, pg = open_signed_in(b, "Super Admin")
        try:
            pg.wait_for_function(
                "!document.getElementById('app').classList.contains('on')",
                timeout=90000)
            assert "timed out" in login_msg(pg), login_msg(pg)
            assert pg.evaluate("location.hash") == "#fqc"
            pg.evaluate("window.__sentinel = 'same page'")
            sign_in(pg)
            assert wait_app_on(pg), \
                "signing in again did not open the app: %r" % login_msg(pg)
            assert "could not be loaded" not in login_msg(pg), login_msg(pg)
            assert pg.evaluate("window.__sentinel") == "same page", \
                "it needed a reload - the fix is meant to make the same page work"
            assert pg.evaluate("location.hash") == "#fqc", "did not return to FQC"
            assert pg.errors == [], pg.errors
        finally:
            ctx.close()


@test("Admin and Super Admin: sign out, sign in again on the same page - the "
      "app opens; the other roles still do too")
def t_signout_then_relogin_every_role():
    seed()
    with H.browser() as b:
        for role in ALL_ROLES:
            ctx, pg = open_signed_in(b, role)
            try:
                pg.evaluate("window.signOut()")
                pg.wait_for_timeout(700)
                assert not app_on(pg)
                pg.evaluate("window.__sentinel = 'same page'")
                sign_in(pg)
                assert wait_app_on(pg), \
                    "%s: signing in again did not open the app: %r" % (role, login_msg(pg))
                assert pg.evaluate("window.__sentinel") == "same page", \
                    "%s needed a reload" % role
                assert login_msg(pg) == "", (role, login_msg(pg))
                assert pg.errors == [], (role, pg.errors)
            finally:
                ctx.close()


@test("nothing piles up across sign-ins on one page: the top bar keeps ONE "
      "database badge (it gained another on every sign-in), and the nav, views "
      "and element ids do not grow")
def t_reentry_does_not_grow_the_page():
    seed("Super Admin")
    snap = """() => {
      const ids = {}; document.querySelectorAll('[id]').forEach(e => ids[e.id] = (ids[e.id] || 0) + 1);
      return {badge: document.querySelectorAll('#dbBadge').length,
              tb_units: document.querySelectorAll('.tb-unit').length,
              nav: document.querySelectorAll('#sidenav .nav-i').length,
              views: document.querySelectorAll('section.view').length,
              dup_ids: Object.keys(ids).filter(k => ids[k] > 1).length}; }"""
    with H.browser() as b:
        ctx, pg = open_signed_in(b, "Super Admin")
        try:
            first = pg.evaluate(snap)
            assert first["badge"] == 1, first
            for _ in range(3):
                pg.evaluate("window.signOut()")
                pg.wait_for_timeout(600)
                sign_in(pg, "Super Admin")
                assert wait_app_on(pg)
                pg.wait_for_timeout(1500)
            last = pg.evaluate(snap)
            assert last == first, "the page grew across re-entries: %s -> %s" % (first, last)
        finally:
            ctx.close()


@test("if some OTHER re-entry problem ever appears the page reloads once by "
      "itself and opens the app, and the real error is logged for whoever "
      "looks - the person is not stranded on a wrong message")
def t_unknown_reentry_failure_reloads_once():
    seed("Super Admin")
    once = ("(function(){var n=0,o=window.initAll;window.initAll=function(){"
            "n++;if(n>1)throw new Error('boom on re-entry');"
            "return o.apply(this,arguments);};})();")
    with H.browser() as b:
        ctx, pg = open_signed_in(b, "Super Admin", once)
        console = []
        pg.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        try:
            pg.evaluate("window.signOut()")
            pg.wait_for_timeout(700)
            pg.evaluate("window.__sentinel = 'same page'")
            loads_before = len(pg.navs)
            sign_in(pg, "Super Admin")
            assert wait_app_on(pg, 20000), \
                "the page did not recover: %r" % login_msg(pg)
            assert pg.evaluate("window.__sentinel || 'reloaded'") == "reloaded", \
                "it should have reloaded"
            assert len(pg.navs) - loads_before == 1, \
                "expected exactly one reload, saw %d" % (len(pg.navs) - loads_before)
            assert any("boom on re-entry" in c for c in console), \
                "the real error was not logged: %s" % console
        finally:
            ctx.close()


@test("a PERMANENT failure to build the screens says so, does not blame the "
      "data, and does not reload in a loop")
def t_permanent_build_failure_is_honest():
    seed("FQC Operator")
    with H.browser() as b:
        ctx = b.new_context()
        pg = ctx.new_page()
        navs = []
        pg.on("framenavigated",
              lambda f: navs.append(f.url) if f == pg.main_frame else None)
        body = js_source() + "\n;window.initAll=function(){throw new Error('permanent fault');};\n"
        pg.route(re.compile(r".*/static/icon_live\.js.*"),
                 lambda r: r.fulfill(status=200, body=body,
                                     content_type="application/javascript"))
        try:
            pg.goto(H.base_url() + "/")
            pg.wait_for_selector("#liLoginId", timeout=20000)
            sign_in(pg, "FQC Operator")
            pg.wait_for_timeout(5000)
            msg = login_msg(pg)
            assert not app_on(pg)
            assert "could not be built" in msg and "permanent fault" in msg, msg
            assert "could not be loaded" not in msg, msg
            assert len(navs) == 1, "it reloaded %d time(s)" % (len(navs) - 1)
        finally:
            ctx.close()


@test("a genuine failure to fetch /api/boot still says the data could not be "
      "loaded - that message is true there - and nothing of the app opens")
def t_boot_fetch_failure_message_kept():
    seed("FQC Operator")
    with H.browser() as b:
        ctx = b.new_context()
        pg = ctx.new_page()
        pg.route(re.compile(r".*/api/boot.*"),
                 lambda r: r.fulfill(status=500, body="{}", content_type="application/json"))
        try:
            pg.goto(H.base_url() + "/")
            pg.wait_for_selector("#liLoginId", timeout=20000)
            sign_in(pg, "FQC Operator")
            pg.wait_for_timeout(3000)
            assert not app_on(pg)
            assert "data could not be loaded" in login_msg(pg), login_msg(pg)
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
                print("  PASS  %s" % name)
                passed += 1
            except Exception as e:
                print("  FAIL  %s\n        %s" % (name, e))
                traceback.print_exc()
                failed += 1
    finally:
        H.cleanup()
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
