"""
ICON TRACE - Round 24: the Users screen, in a real browser.

    python test_users_screen.py        (needs Playwright + Chromium)

What only a browser can show: that v4's fourteen fictional names are
genuinely gone from the rendered page, that the action buttons a person is
offered match what the server would actually allow, and that a refusal
arrives as the server's own sentence rather than a paraphrase.
"""

import os, sys, traceback

import ui_harness as H                                   # noqa: E402 (sets the DB path)
import store                                             # noqa: E402
import icon_auth                                         # noqa: E402
import auth_test_helper as AUTH                          # noqa: E402

APP = H.APP
icon_auth.COOLDOWN_STEPS = ()

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "round24_shots")
os.makedirs(SHOTS, exist_ok=True)


def base():
    store.wipe()
    AUTH.ensure_auth_schema()
    key = os.path.join(os.path.dirname(store.DB_PATH), ".icon_totp_key")
    if not os.path.exists(key):
        icon_auth.create_key()
    AUTH.make_user("Super Admin", login_id="sa1", name="Super One")
    AUTH.make_user("Admin", login_id="admin1", name="Admin One")
    AUTH.make_user("FQC Operator", login_id="op1", name="Amit Sharma",
                   station="FQC-01")


def users_page(b, role="Super Admin", login_id=None):
    pg = H.open_page(b, "admin", wait_ms=1200, role=role, login_id=login_id)
    pg.wait_for_selector("#userRows tr", timeout=15000)
    return pg


def create_via_form(pg, login_id, name, role, password=None, station=""):
    pg.fill("#usrNewId", login_id)
    pg.fill("#usrNewName", name)
    pg.select_option("#usrNewRole", role)
    pg.fill("#usrNewStation", station)
    if password is not None:
        pg.fill("#usrNewPw", password)
    pg.click("#usrNewBtn")


def user_row(login_id):
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT * FROM app_user WHERE login_id=%s", (login_id,))
    return dict(r) if r else None


# --------------------------------------------------------------------------

@test("v4's fourteen fictional names are gone from the rendered page, and "
     "no Super Admin row appears anywhere on screen")
def t_the_old_list_is_gone():
    base()
    with H.browser() as b:
        pg = users_page(b)
        text = pg.inner_text("#ad-users")
        for ghost in ("Rajesh Kumar", "Amit Sharma\nFQC-A1", "Dasrath Pal",
                      "Suresh Patel", "PRD-A1", "FQC-A1"):
            assert ghost not in text, "v4's sample data is still on screen: %r" % ghost
        assert "Super One" not in text and "sa1" not in text, \
            "a Super Admin is visible on the Users screen"
        # the real accounts ARE there
        assert "Admin One" in text and "admin1" in text, text[:200]
        assert "op1" in text, text[:200]
        assert pg.errors == [], pg.errors


@test("a weak temporary password is refused on screen with the policy's "
     "own sentence, and creates nobody; a strong one works and the account "
     "appears in the list")
def t_create_operator_weak_then_strong():
    base()
    with H.browser() as b:
        pg = users_page(b)
        create_via_form(pg, "newop", "New Operator", "Packing Operator",
                        password="abc", station="PACK-01")
        pg.wait_for_selector("#usrNewMsg:not(:empty)", timeout=10000)
        assert pg.inner_text("#usrNewMsg") == \
            "Password must be at least 8 characters.", pg.inner_text("#usrNewMsg")
        assert user_row("newop") is None, "a refused create still made an account"
        pg.screenshot(path=os.path.join(SHOTS, "2_weak_password_refused.png"))

        pg.fill("#usrNewPw", "CorrectHorse99")
        pg.click("#usrNewBtn")
        pg.wait_for_selector("#userRows tr:has-text('newop')", timeout=10000)
        assert user_row("newop")["role"] == "Packing Operator"
        assert "New Operator" in pg.inner_text("#userRows")


@test("creating an Admin offers no password field at all and shows a "
     "copyable enrolment link afterwards - an Admin signs in by "
     "authenticator code, so there is no password to set")
def t_create_admin_shows_enrol_link():
    base()
    with H.browser() as b:
        pg = users_page(b)
        pg.select_option("#usrNewRole", "Admin")
        pg.wait_for_timeout(200)
        assert pg.eval_on_selector("#usrNewPwWrap", "e => e.offsetParent === null"), \
            "a password field is offered for an Admin account"

        create_via_form(pg, "admin2", "Admin Two", "Admin")
        pg.wait_for_selector("#usrEnrolUrl", timeout=10000)
        url = pg.input_value("#usrEnrolUrl")
        assert "admin2" in url and "token=" in url, url
        assert user_row("admin2")["role"] == "Admin"
        assert not user_row("admin2")["pw_hash"], "an Admin got a password"
        pg.screenshot(path=os.path.join(SHOTS, "3_admin_enrol_link.png"))


@test("an Admin is never offered an action the server would refuse: "
     "another Admin's row reads 'View only', and the create form does not "
     "offer the Admin role at all")
def t_admin_sees_only_what_it_may_do():
    base()
    AUTH.make_user("Admin", login_id="admin2", name="Admin Two")
    with H.browser() as b:
        pg = users_page(b, role="Admin", login_id="admin1")
        text = pg.inner_text("#userRows")
        assert "Super One" not in text, "an Admin saw a Super Admin"
        assert "Admin Two" not in text, \
            "an Admin saw another Admin's row: %s" % text

        roles = pg.eval_on_selector_all("#usrNewRole option", "e => e.map(o => o.value)")
        assert "Admin" not in roles, \
            "an Admin is offered a role the server will refuse: %s" % roles
        assert "Super Admin" not in roles, roles

        # their OWN row is view-only rather than showing a button that lies
        own = pg.eval_on_selector_all(
            "#userRows tr", "trs => trs.map(t => t.textContent)")
        mine = [t for t in own if "admin1" in t][0]
        assert "View only" in mine, mine
        pg.screenshot(path=os.path.join(SHOTS, "4_admin_view_only.png"))


@test("an Admin calling the API directly - not through a button - still "
     "cannot reset another Admin's password, and learns nothing about "
     "them from the refusal")
def t_admin_direct_api_is_still_refused():
    base()
    AUTH.make_user("Admin", login_id="admin2", name="Admin Two")
    with H.browser() as b:
        pg = users_page(b, role="Admin", login_id="admin1")
        out = pg.evaluate("""() => fetch('/api/users/admin2/reset-password', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({temp_password:'CorrectHorse99'})
        }).then(r => r.json().then(j => ({status: r.status, why: j.why})))""")
        assert out["status"] == 403, out
        assert out["why"] == "Not found.", out

        ghost = pg.evaluate("""() => fetch('/api/users/nobody-at-all/reset-password', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({temp_password:'CorrectHorse99'})
        }).then(r => r.json().then(j => ({status: r.status, why: j.why})))""")
        assert ghost == out, \
            "a real Admin and a nonexistent id answer differently: %s vs %s" % (out, ghost)


@test("deactivating an operator stops them signing in; reactivating lets "
     "them back - both driven from the screen, both confirmed at /login")
def t_deactivate_then_reactivate_from_the_screen():
    base()
    with store.conn() as (cx, cur):
        icon_auth.set_temp_password(cur, "sa1", "op1", "CorrectHorse99")

    def can_sign_in():
        r = APP.app.test_client().post(
            "/login", json={"login_id": "op1", "credential": "CorrectHorse99"})
        return r.status_code == 200

    assert can_sign_in(), "the operator could not sign in to begin with"

    with H.browser() as b:
        pg = users_page(b)
        pg.on("dialog", lambda d: d.accept())      # the Deactivate confirm
        pg.click("#userRows tr:has-text('op1') >> text=Deactivate")
        pg.wait_for_selector("#userRows tr:has-text('op1') >> text=Reactivate",
                             timeout=10000)
        assert user_row("op1")["active"] == 0
        assert not can_sign_in(), "a deactivated operator still signed in"
        pg.screenshot(path=os.path.join(SHOTS, "5_deactivated.png"))

        pg.click("#userRows tr:has-text('op1') >> text=Reactivate")
        pg.wait_for_selector("#userRows tr:has-text('op1') >> text=Deactivate",
                             timeout=10000)
        assert user_row("op1")["active"] == 1
        assert can_sign_in(), "a reactivated operator still could not sign in"


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
