"""
ICON TRACE - Round 23: the real login screen, in a real browser.

    python test_login_screen.py        (needs Playwright + Chromium)

What this defends, which no server-side test can:

  1. THE FAKE LOGIN IS GONE FROM THE ACTUAL DOM. No #who dropdown of
     fourteen names, no password box with dots painted into its value, and
     no "Authentication is designed, not yet built" note - checked against
     the rendered page, because a function that no longer builds that
     markup is not the same claim as the markup not being there.

  2. SIGNING IN IS A REAL LOGIN. Typing a real ID and password reaches
     POST /login, and what comes back - name, role, station - is what USER
     ends up holding. A wrong password gets the same uninformative sentence
     the server chose on purpose.

  3. SIGNING OUT ACTUALLY ENDS THE SESSION. Not just hiding #app: the same
     cookie afterwards cannot perform a write.

  4. THE IDLE WARNING APPEARS AND CAN BE ACTED ON, near a real expiry -
     with the window shortened by an env override rather than by waiting
     an hour.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_login_")
# A 40-second window, so the 2-minute warning band is already open the
# moment a session exists and the popup is testable in seconds.
os.environ["ICON_SESSION_SECONDS"] = "40"
os.environ["ICON_SESSION_SECONDS_ADMIN"] = "40"

import ui_harness as H                                     # noqa: E402 (sets the DB path)
import store                                               # noqa: E402
import icon_auth                                           # noqa: E402
import auth_test_helper as AUTH                            # noqa: E402

APP = H.APP
icon_auth.SESSION_WINDOW_SHORT = 40
icon_auth.SESSION_WINDOW_LONG = 40

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


LOGIN_ID = "dasrath.p"
PASSWORD = "CorrectHorse99"
NAME = "Dasrath Pal"


def seed_account(role="Dispatch Operator"):
    """A real account with a real password - this is the one test that
    goes through icon_auth.login() itself rather than around it."""
    store.wipe()
    AUTH.ensure_auth_schema()
    key = os.path.join(os.path.dirname(store.DB_PATH), ".icon_totp_key")
    if not os.path.exists(key):
        icon_auth.create_key()
    icon_auth.COOLDOWN_STEPS = ()
    with store.conn() as (cx, cur):
        cur.execute(
            "INSERT INTO app_user (login_id, display_name, role, station, "
            "pw_hash, created_at, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (LOGIN_ID, NAME, role, "DISPATCH-01",
             icon_auth.hash_pw(PASSWORD), 1000000, "test"))


def blank_page(b):
    """The login screen as a person actually meets it - no cookie."""
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(H.base_url() + "/")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_selector("#liLoginId", timeout=15000)
    return pg


def sign_in(pg, login_id=LOGIN_ID, credential=PASSWORD):
    pg.fill("#liLoginId", login_id)
    pg.fill("#liCredential", credential)
    pg.click("#liSubmit")


# --------------------------------------------------------------------------

@test("the fake login is gone from the real DOM: no #who dropdown of "
     "names, no painted-dots password, no 'not yet built' note - and two "
     "real inputs in their place")
def t_fake_login_is_gone():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        assert pg.evaluate("!document.getElementById('who')"), \
            "the #who dropdown of names is still in the page"
        dots = pg.eval_on_selector_all(
            "#login input[type=password]",
            "els => els.filter(e => (e.value || '').indexOf('\\u2022') >= 0).length")
        assert dots == 0, "a password box still has dots painted into its value"
        note = pg.inner_text("#login").lower()
        assert "not yet built" not in note, \
            "the login screen still says authentication is not built"
        assert pg.eval_on_selector("#liLoginId", "e => e.offsetParent !== null")
        assert pg.eval_on_selector("#liCredential", "e => e.offsetParent !== null")
        assert pg.errors == [], pg.errors


@test("a real ID and password sign in through POST /login, and USER holds "
     "what the SERVER said - name, role and station - not anything chosen "
     "on the page")
def t_real_sign_in_sets_user_from_server():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        sign_in(pg)
        pg.wait_for_selector("#app.on", timeout=15000)
        user = pg.evaluate("({name: USER.name, role: USER.role, "
                          "station: USER.station})")
        assert user == {"name": NAME, "role": "Dispatch Operator",
                        "station": "DISPATCH-01"}, user
        assert pg.inner_text("#uname").strip() == NAME
        # and the cookie really is a server-issued session
        s = pg.evaluate("fetch('/api/session').then(r => r.json())")
        assert s["signed_in"] is True and s["name"] == NAME, s


@test("a wrong password is refused on the screen with the server's own "
     "deliberately uninformative sentence, and does not sign anyone in")
def t_wrong_password_refused():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        sign_in(pg, credential="not-the-password")
        pg.wait_for_selector("#liMsg:not(:empty)", timeout=15000)
        msg = pg.inner_text("#liMsg")
        assert msg == icon_auth.GENERIC_FAIL, msg
        assert pg.evaluate(
            "!document.getElementById('app').classList.contains('on')"), \
            "a wrong password still got into the app"
        s = pg.evaluate("fetch('/api/session').then(r => r.json())")
        assert s["signed_in"] is False, s


@test("a role-restricted action is allowed for the role that owns it and "
     "refused for one that does not - proved through the running page, "
     "against the real endpoint")
def t_role_restriction_in_the_browser():
    seed_account(role="Dispatch Operator")
    with H.browser() as b:
        pg = blank_page(b)
        sign_in(pg)
        pg.wait_for_selector("#app.on", timeout=15000)

        # Dispatch Operator owns the gate pass: allowed (400 here is the
        # endpoint disliking an empty body, which means the gate passed).
        gp = pg.evaluate(
            "fetch('/api/gatepass', {method:'POST',"
            "headers:{'Content-Type':'application/json'},body:'{}'})"
            ".then(r => r.status)")
        assert gp != 403, "Dispatch Operator was refused the gate pass (403)"

        # Packing is not theirs, and saying otherwise in a header changes
        # nothing now - there is no header left that the server reads.
        pack = pg.evaluate(
            "fetch('/api/box/open', {method:'POST',"
            "headers:{'Content-Type':'application/json',"
            "'X-User-Role':'Super Admin'},body:'{}'})"
            ".then(r => r.status)")
        assert pack == 403, \
            "Dispatch Operator opened a pallet (%s) - the gate did not hold" % pack


@test("signing out ends the session for real: the same cookie afterwards "
     "cannot perform a write, and the login screen is back")
def t_sign_out_ends_the_session():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        sign_in(pg)
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.evaluate("signOut()")
        pg.wait_for_timeout(700)

        assert pg.evaluate(
            "!document.getElementById('app').classList.contains('on')")
        assert pg.evaluate("!USER.name"), "USER.name survived sign-out"
        after = pg.evaluate(
            "fetch('/api/gatepass', {method:'POST',"
            "headers:{'Content-Type':'application/json'},body:'{}'})"
            ".then(r => r.status)")
        assert after == 401, \
            "the same cookie still authenticated a write after sign-out (%s)" % after


@test("the idle warning appears near expiry and one click on it extends "
     "the session - with the window shortened by an env override rather "
     "than an hour of waiting")
def t_idle_warning_appears_and_extends():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        sign_in(pg)
        pg.wait_for_selector("#app.on", timeout=15000)

        # 40-second window, 120-second warning band: the popup is due on
        # the first poll.
        pg.wait_for_selector("#idleWarn", timeout=20000)
        txt = pg.inner_text("#idleWarn").lower()
        assert "still there" in txt, txt
        assert "signed out" in txt, txt

        before = pg.evaluate(
            "fetch('/api/session').then(r => r.json()).then(s => s.expires_at)")
        pg.wait_for_timeout(1200)
        pg.click("#idleStay")
        pg.wait_for_timeout(900)
        after = pg.evaluate(
            "fetch('/api/session').then(r => r.json()).then(s => s.expires_at)")
        assert after > before, \
            "the popup's button did not extend the session (%s -> %s)" % (before, after)


@test("v4's old login is never painted, even while icon_live.js is still "
     "being fetched - the markup is in the DOM but #login stays hidden "
     "until the real fields replace it")
def t_no_flash_of_the_old_login():
    seed_account()
    with H.browser() as b:
        ctx = b.new_context(viewport={"width": 1400, "height": 900})

        def slow(route):
            import time as _t
            _t.sleep(1.5)          # hold the live layer back on purpose
            route.continue_()

        ctx.route("**/icon_live.js*", slow)
        pg = ctx.new_page()
        pg.goto(H.base_url() + "/", wait_until="commit")
        pg.wait_for_timeout(700)   # mid-fetch: the old form's best chance

        assert pg.evaluate("!!document.getElementById('who')"), \
            "test is not proving anything - v4's markup is not in the DOM here"
        vis = pg.evaluate(
            "getComputedStyle(document.getElementById('login')).visibility")
        assert vis == "hidden", \
            "the old login was painted while the live layer loaded (%s)" % vis

        pg.wait_for_selector("#liLoginId", timeout=20000)
        assert pg.evaluate(
            "getComputedStyle(document.getElementById('login')).visibility") == "visible"
        assert pg.evaluate(
            "document.getElementById('login').classList.contains('icon-ready')")
        ctx.close()


@test("the splash covers the sign-in and the bootstrap behind it, then "
     "clears itself and leaves the app on screen")
def t_splash_covers_sign_in():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        assert pg.evaluate(
            "getComputedStyle(document.getElementById('enIconSplash')).display") == "none", \
            "the splash is up before anyone has signed in"

        sign_in(pg)
        pg.wait_for_selector("#enIconSplash.is-showing", timeout=8000)
        pg.wait_for_selector("#enIconSplash", state="hidden", timeout=15000)

        assert pg.evaluate("document.getElementById('app').classList.contains('on')")
        assert pg.evaluate("USER.name") == NAME
        assert pg.errors == [], pg.errors


def watch_splash(pg):
    """Record whether the splash is EVER shown from here on.

    Checking after the fact is not enough and was the hole in the first
    version of this test: the splash used to go up on the click and come
    down when the refusal arrived, so a test that only looked at the end
    state saw it hidden and passed, while a person saw the whole brand
    animation flash and then drop back to the login screen."""
    pg.evaluate("""() => {
      window.__splashEverShown = false;
      const el = document.getElementById('enIconSplash');
      if (el.classList.contains('is-showing')) window.__splashEverShown = true;
      new MutationObserver(() => {
        if (el.classList.contains('is-showing')) window.__splashEverShown = true;
      }).observe(el, {attributes: true, attributeFilter: ['class']});
    }""")


@test("a refused sign-in never shows the splash at all - not for a "
     "moment. The animation says 'you are in'; until the server has said "
     "so, showing it is a claim we cannot make")
def t_splash_never_shown_on_refusal():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        watch_splash(pg)
        sign_in(pg, credential="not-the-password")
        pg.wait_for_selector("#liMsg:not(:empty)", timeout=10000)
        pg.wait_for_timeout(400)
        assert pg.evaluate("window.__splashEverShown") is False, \
            "the splash flashed during a failed sign-in"
        assert pg.inner_text("#liMsg") == icon_auth.GENERIC_FAIL
        assert pg.evaluate(
            "!document.getElementById('app').classList.contains('on')")


@test("clicking Sign in with nothing typed is answered on the spot - no "
     "splash, and no request, so an empty form cannot spend one of the "
     "attempts that lead to a lockout")
def t_empty_form_never_reaches_the_server():
    seed_account()
    with H.browser() as b:
        pg = blank_page(b)
        watch_splash(pg)
        posts = []
        pg.on("request", lambda r: posts.append(r.url)
              if r.method == "POST" and "/login" in r.url else None)

        pg.click("#liSubmit")                      # both fields empty
        pg.wait_for_selector("#liMsg:not(:empty)", timeout=5000)
        assert pg.evaluate("window.__splashEverShown") is False, \
            "the splash showed for an empty form"
        assert posts == [], "an empty form was still POSTed to /login: %s" % posts

        pg.fill("#liLoginId", LOGIN_ID)            # ID only, still no credential
        pg.click("#liSubmit")
        pg.wait_for_timeout(400)
        assert posts == [], "an empty credential was still POSTed: %s" % posts
        assert pg.evaluate("window.__splashEverShown") is False

        # and a complete form does reach it
        pg.fill("#liCredential", PASSWORD)
        pg.click("#liSubmit")
        pg.wait_for_selector("#app.on", timeout=15000)
        assert len(posts) == 1, posts


@test("with the OS asking for reduced motion the splash holds the finished "
     "mark still, for long enough to read as deliberate - not the 166ms "
     "flicker that setting used to produce")
def t_splash_holds_under_reduced_motion():
    seed_account()
    with H.browser() as b:
        # What Windows' Accessibility -> Visual effects -> Animation effects
        # OFF does to a browser. Reported as "just showing logo for a
        # fraction of a second and load screens".
        ctx = b.new_context(viewport={"width": 1400, "height": 900},
                            reduced_motion="reduce")
        pg = ctx.new_page()
        pg.goto(H.base_url() + "/")
        pg.wait_for_selector("#liLoginId", timeout=15000)
        assert pg.evaluate(
            "matchMedia('(prefers-reduced-motion:reduce)').matches") is True

        pg.evaluate("""() => {
          window.__t = {};
          const el = document.getElementById('enIconSplash');
          const t0 = performance.now();
          new MutationObserver(() => {
            if (el.classList.contains('is-leaving')) {
              if (!window.__t.left) window.__t.left = performance.now() - t0;
            } else if (el.classList.contains('is-showing')) {
              if (!window.__t.shown) window.__t.shown = performance.now() - t0;
            }
          }).observe(el, {attributes: true, attributeFilter: ['class']});
        }""")
        pg.fill("#liLoginId", LOGIN_ID)
        pg.fill("#liCredential", PASSWORD)
        pg.click("#liSubmit")
        # Wait for it to COME UP first: the splash sits at display:none at
        # rest, so asking for state="hidden" straight after the click is
        # satisfied instantly, before it has shown at all.
        pg.wait_for_selector("#enIconSplash.is-showing", timeout=10000)
        pg.wait_for_selector("#enIconSplash", state="hidden", timeout=15000)

        t = pg.evaluate("window.__t")
        visible = t["left"] - t["shown"]
        assert visible > 700, \
            "the splash only held for %dms under reduced motion - that is " \
            "the flicker, not a hold" % visible

        # ...and it is still genuinely motionless: no animation on the mark,
        # and no scale on the way out.
        anim = pg.evaluate(
            "getComputedStyle(document.querySelector('#enIconSplash .breathe'))"
            ".animationName")
        assert anim in ("none", ""), "the mark is still animating: %r" % anim
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
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
