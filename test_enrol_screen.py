"""
ICON TRACE - Round 25: enrolment, served by the real app.

    python test_enrol_screen.py        (needs Playwright + Chromium)

Until this round the link handed out after creating an Admin pointed at
http://127.0.0.1:8091 - auth_lab/lab_app.py's port. Nothing runs there on a
real deployment, so the link simply did not resolve. The flow itself was
never the problem; it just lived in the wrong process.
"""

import os, re, sys, traceback

import ui_harness as H                                   # noqa: E402 (sets the DB path)
import store                                             # noqa: E402
import icon_auth                                         # noqa: E402
import auth_test_helper as AUTH                          # noqa: E402
import pyotp                                             # noqa: E402

APP = H.APP
icon_auth.COOLDOWN_STEPS = ()

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "round25_shots")
os.makedirs(SHOTS, exist_ok=True)

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def base():
    store.wipe()
    AUTH.ensure_auth_schema()
    key = os.path.join(os.path.dirname(store.DB_PATH), ".icon_totp_key")
    if not os.path.exists(key):
        icon_auth.create_key()
    AUTH.make_user("Super Admin", login_id="sa1", name="Super One")


def make_admin(login_id="admin2", name="Admin Two"):
    """Create an Admin through the real endpoint and return its enrol URL."""
    c = APP.app.test_client()
    AUTH.test_login(c, role="Super Admin", login_id="sa1")
    r = c.post("/api/users", json={"login_id": login_id, "display_name": name,
                                   "role": "Admin"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def user_row(login_id):
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT * FROM app_user WHERE login_id=%s", (login_id,))
    return dict(r) if r else None


# --------------------------------------------------------------------------

@test("the enrolment link points at THIS app, not the standalone lab's "
     "8091 - the link an Admin is handed now resolves where they are")
def t_enrol_url_is_this_app():
    base()
    d = make_admin()
    assert ":8091" not in d["enrol_url"], d["enrol_url"]
    assert "/enrol?login_id=admin2" in d["enrol_url"], d["enrol_url"]
    # and it really is served here
    r = APP.app.test_client().get("/enrol?login_id=admin2&token=" + d["token"])
    assert r.status_code == 200, r.status_code


@test("the whole flow through the app's own routes, in a real browser: "
     "open the link, enter the code the secret generates, and the account "
     "is enrolled")
def t_full_enrol_flow_in_browser():
    base()
    d = make_admin()
    with H.browser() as b:
        pg = b.new_page(viewport={"width": 1100, "height": 900})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.goto(H.base_url() + "/enrol?login_id=admin2&token=" + d["token"])
        pg.wait_for_selector("input[name=code]", timeout=15000)

        assert pg.eval_on_selector_all("svg", "e => e.length") >= 1, \
            "no QR code rendered"
        secret = pg.inner_text(".secret").strip()
        assert len(secret) == 32, secret
        pg.screenshot(path=os.path.join(SHOTS, "1_enrol_page.png"))

        # a wrong code is refused and can simply be retyped - the pending
        # secret must NOT be regenerated, or the QR already scanned dies
        pg.fill("input[name=code]", "000000")
        pg.click("button[type=submit]")
        pg.wait_for_selector(".note.n-bad", timeout=10000)
        assert "not accepted" in pg.inner_text(".note.n-bad")
        assert not user_row("admin2")["totp_secret_enc"]

        pg.fill("input[name=code]", pyotp.TOTP(secret).now())
        pg.click("button[type=submit]")
        pg.wait_for_selector("text=Your authenticator", timeout=10000)
        assert user_row("admin2")["totp_secret_enc"], "not enrolled"
        assert user_row("admin2")["must_reenrol"] == 0
        assert pg.errors == [], pg.errors
        pg.screenshot(path=os.path.join(SHOTS, "2_enrol_done.png"))


@test("a used token is dead: reopening the same link afterwards refuses, "
     "with the same sentence a bad or expired one gets")
def t_token_is_single_use():
    base()
    d = make_admin()
    c = APP.app.test_client()
    r = c.get("/enrol?login_id=admin2&token=" + d["token"])
    secret = re.search(rb'<div class="secret">([A-Z2-7]+)</div>', r.data).group(1).decode()
    ok = c.post("/enrol", data={"login_id": "admin2", "token": d["token"],
                                "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200

    again = c.get("/enrol?login_id=admin2&token=" + d["token"])
    assert again.status_code == 400
    assert b"not valid, or it has expired" in again.data

    # a nonsense token, and an unknown account, answer identically
    for url in ("/enrol?login_id=admin2&token=deadbeef",
                "/enrol?login_id=ghost&token=" + d["token"]):
        bad = c.get(url)
        assert bad.status_code == 400 and b"not valid, or it has expired" in bad.data


@test("recovery codes are shown once and never again - a Super Admin "
     "enrolling sees ten, and reopening shows none")
def t_recovery_codes_shown_once():
    base()
    # a Super Admin's own re-enrolment is the path that mints recovery codes
    with store.conn() as (cx, cur):
        token = icon_auth.reset_totp(cur, "cli", "sa1")
    c = APP.app.test_client()
    r = c.get("/enrol?login_id=sa1&token=" + token)
    secret = re.search(rb'<div class="secret">([A-Z2-7]+)</div>', r.data).group(1).decode()
    done = c.post("/enrol", data={"login_id": "sa1", "token": token,
                                  "code": pyotp.TOTP(secret).now()})
    assert done.status_code == 200, done.status_code
    body = done.data.decode()
    assert "Save these recovery codes" in body, "no recovery codes shown"
    codes = re.findall(r'<span>([A-Z2-9]{4}-[A-Z2-9]{4})</span>', body)
    assert len(codes) == 10, codes

    # and they are not obtainable again
    again = c.get("/enrol?login_id=sa1&token=" + token)
    assert b"Save these recovery codes" not in again.data


@test("enrolment always requires a token here, even for an account "
     "flagged must_reenrol - the lab's tokenless path would let anyone who "
     "knows a login_id enrol an account whose TOTP was just reset")
def t_token_always_required():
    base()
    with store.conn() as (cx, cur):
        icon_auth.reset_totp(cur, "cli", "sa1")          # sets must_reenrol=1
    assert user_row("sa1")["must_reenrol"] == 1

    r = APP.app.test_client().get("/enrol?login_id=sa1")
    assert r.status_code == 400, r.status_code
    assert b"not valid, or it has expired" in r.data
    assert not user_row("sa1")["totp_secret_enc"], \
        "a tokenless request started an enrolment"


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
