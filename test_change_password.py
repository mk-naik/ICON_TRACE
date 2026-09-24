"""
ICON TRACE - Round 25: a temporary password has to be replaced.

    python test_change_password.py        (needs Playwright + Chromium)

icon_auth.login() has always returned must_change_pw and nothing in app.py
or icon_live.js read it, so an operator handed a temporary password signed
in on it and stayed on it indefinitely - confirmed live before this round,
not inferred from the code.
"""

import os, sys, traceback

import ui_harness as H                                   # noqa: E402 (sets the DB path)
import store                                             # noqa: E402
import icon_auth                                         # noqa: E402
import auth_test_helper as AUTH                          # noqa: E402

APP = H.APP
icon_auth.COOLDOWN_STEPS = ()

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "round25_shots")
os.makedirs(SHOTS, exist_ok=True)

TEMP = "TempPass123!"
NEW = "CorrectHorse99"

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def base(role="Packing Operator", login_id="pk1"):
    """A brand-new account holding nothing but a temporary password."""
    store.wipe()
    AUTH.ensure_auth_schema()
    key = os.path.join(os.path.dirname(store.DB_PATH), ".icon_totp_key")
    if not os.path.exists(key):
        icon_auth.create_key()
    AUTH.make_user("Super Admin", login_id="sa1", name="Super One")
    c = APP.app.test_client()
    AUTH.test_login(c, role="Super Admin", login_id="sa1")
    r = c.post("/api/users", json={"login_id": login_id, "display_name": "Pack One",
                                   "role": role, "temp_password": TEMP})
    assert r.status_code == 200, r.get_json()
    return login_id


def sign_in(pg, login_id, credential):
    pg.fill("#liLoginId", login_id)
    pg.fill("#liCredential", credential)
    pg.click("#liSubmit")


def fresh_page(b):
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(H.base_url() + "/")
    pg.wait_for_selector("#liLoginId", timeout=15000)
    return pg


# --------------------------------------------------------------------------

@test("signing in on a temporary password lands on the change-password "
     "step, not in the app - and a reload does not slip past it")
def t_forced_to_change_on_first_sign_in():
    base()
    with H.browser() as b:
        pg = fresh_page(b)
        sign_in(pg, "pk1", TEMP)
        pg.wait_for_selector("#cpSubmit", timeout=15000)

        assert pg.evaluate(
            "!document.getElementById('app').classList.contains('on')"), \
            "the app opened while a temporary password was still in force"
        assert "temporary password" in pg.inner_text("#login").lower()
        pg.screenshot(path=os.path.join(SHOTS, "3_change_password.png"))

        # a reload comes back to the same step, from /api/session
        pg.reload()
        pg.wait_for_selector("#cpSubmit", timeout=15000)
        assert pg.evaluate(
            "!document.getElementById('app').classList.contains('on')"), \
            "reloading escaped the change-password step"
        assert pg.errors == [], pg.errors


@test("nothing can be saved while the temporary password stands - the "
     "server refuses the write regardless of what the screen allows")
def t_writes_refused_until_changed():
    base()
    with H.browser() as b:
        pg = fresh_page(b)
        sign_in(pg, "pk1", TEMP)
        pg.wait_for_selector("#cpSubmit", timeout=15000)

        out = pg.evaluate("""() => fetch('/api/box/open', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({grade:'A', model:'ISEN630-G12R', capacity:2})
        }).then(r => r.json().then(j => ({status: r.status, why: j.why})))""")
        assert out["status"] == 403, out
        assert out["why"] == "Set your own password before saving anything.", out


@test("the policy's own sentence is shown for a weak new password, and a "
     "mismatch is caught before the server is asked")
def t_refusals_on_the_screen():
    base()
    with H.browser() as b:
        pg = fresh_page(b)
        sign_in(pg, "pk1", TEMP)
        pg.wait_for_selector("#cpSubmit", timeout=15000)

        pg.fill("#cpCurrent", TEMP)
        pg.fill("#cpNew", "CorrectHorse99")
        pg.fill("#cpAgain", "CorrectHorse98")
        pg.click("#cpSubmit")
        pg.wait_for_selector("#cpMsg:not(:empty)", timeout=10000)
        assert pg.inner_text("#cpMsg") == "Those two do not match.", \
            pg.inner_text("#cpMsg")

        pg.fill("#cpNew", "abc")
        pg.fill("#cpAgain", "abc")
        pg.click("#cpSubmit")
        pg.wait_for_function(
            "document.getElementById('cpMsg').textContent.indexOf('8 characters') >= 0",
            timeout=10000)
        assert pg.inner_text("#cpMsg") == "Password must be at least 8 characters."

        pg.fill("#cpCurrent", "not-the-temp-one")
        pg.fill("#cpNew", NEW)
        pg.fill("#cpAgain", NEW)
        pg.click("#cpSubmit")
        pg.wait_for_function(
            "document.getElementById('cpMsg').textContent.indexOf('not accepted') >= 0",
            timeout=10000)


@test("setting a real password lets them straight into the app, and the "
     "temporary one stops working from then on")
def t_change_then_in_and_temp_is_dead():
    base()
    with H.browser() as b:
        pg = fresh_page(b)
        sign_in(pg, "pk1", TEMP)
        pg.wait_for_selector("#cpSubmit", timeout=15000)

        pg.fill("#cpCurrent", TEMP)
        pg.fill("#cpNew", NEW)
        pg.fill("#cpAgain", NEW)
        pg.click("#cpSubmit")
        pg.wait_for_selector("#app.on", timeout=20000)
        assert pg.evaluate("USER.name") == "Pack One", pg.evaluate("USER.name")

        # a write the role is allowed now goes through
        out = pg.evaluate("""() => fetch('/api/box/open', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({grade:'A', model:'ISEN630-G12R', capacity:2})
        }).then(r => r.status)""")
        assert out == 200, out
        assert pg.errors == [], pg.errors

    old = APP.app.test_client().post(
        "/login", json={"login_id": "pk1", "credential": TEMP})
    assert old.status_code == 401, "the temporary password still works"
    new = APP.app.test_client().post(
        "/login", json={"login_id": "pk1", "credential": NEW})
    assert new.status_code == 200 and new.get_json()["must_change_pw"] is False


@test("an account whose password is reset WHILE it is signed in is stopped "
     "on its next action - the flag is read per request, not captured at "
     "login")
def t_reset_while_signed_in():
    base()
    c = APP.app.test_client()
    assert c.post("/login", json={"login_id": "pk1", "credential": TEMP}).status_code == 200
    c.post("/api/session/change-password",
           json={"current_password": TEMP, "new_password": NEW})
    assert c.post("/api/box/open",
                  json={"grade": "A", "model": "ISEN630-G12R",
                        "capacity": 2}).status_code == 200

    # an Admin resets it under them, mid-session
    sa = APP.app.test_client()
    AUTH.test_login(sa, role="Super Admin", login_id="sa1")
    assert sa.post("/api/users/pk1/reset-password",
                   json={"temp_password": "AnotherTemp1!"}).status_code == 200

    blocked = c.post("/api/box/open", json={"grade": "A", "model": "ISEN630-G12R",
                                            "capacity": 2})
    assert blocked.status_code == 403, blocked.status_code
    assert blocked.get_json()["why"] == \
        "Set your own password before saving anything.", blocked.get_json()


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
