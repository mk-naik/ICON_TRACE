"""
ICON TRACE - Round 24: the real user management screen.

    python test_users_admin.py

Before this round the Users screen inside Admin rendered v4's fourteen
fictional names from a static array - all shown "Active", with a
working-looking Edit button, none of them able to sign in - while the
accounts that COULD sign in were invisible there. These cover the API that
replaced it.

The rule this file guards hardest: Super Admin never appears in
GET /api/users, for any viewer, including a Super Admin looking at the
screen themselves. Those accounts are created and managed only through
icon_auth_cli.py. That is Mukesh's instruction, not an oversight - if this
test starts failing because somebody "fixed" the omission, the omission was
the point.
"""

import os, sys, tempfile, time, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_users_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store
import icon_auth
import app as APP
import auth_test_helper as AUTH

icon_auth.COOLDOWN_STEPS = ()
icon_auth.create_key()

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


SA, ADMIN, OP = "sa1", "admin1", "op1"


def base():
    """A fresh database with a Super Admin, an Admin and an operator."""
    store.wipe()
    AUTH.ensure_auth_schema()
    AUTH.make_user("Super Admin", login_id=SA, name="Super One")
    AUTH.make_user("Admin", login_id=ADMIN, name="Admin One")
    AUTH.make_user("FQC Operator", login_id=OP, name="Op One")


def client_as(login_id, role):
    c = APP.app.test_client()
    AUTH.test_login(c, role=role, login_id=login_id)
    return c


def as_super():
    return client_as(SA, "Super Admin")


def as_admin():
    return client_as(ADMIN, "Admin")


def user_row(login_id):
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT * FROM app_user WHERE login_id=%s", (login_id,))
    return dict(r) if r else None


# --------------------------------------------------------------------------
# 1 - the list
# --------------------------------------------------------------------------

@test("a Super Admin never appears in the list - not for an Admin, and not "
     "for a Super Admin looking at their own screen. Deliberate: those "
     "accounts are CLI-only, so listing them here would be misleading")
def t_super_admin_never_listed():
    base()
    for login_id, role in ((ADMIN, "Admin"), (SA, "Super Admin")):
        d = client_as(login_id, role).get("/api/users").get_json()
        roles = [u["role"] for u in d["users"]]
        ids = [u["login_id"] for u in d["users"]]
        assert "Super Admin" not in roles, \
            "%s saw a Super Admin row: %s" % (role, d["users"])
        assert SA not in ids, "%s saw %s in the list" % (role, SA)
    # and it is genuinely in the database - the test is not passing by
    # there being nothing to leak
    assert user_row(SA)["role"] == "Super Admin"


@test("an Admin sees rank-1 accounts and themselves; a Super Admin sees "
     "every non-Super-Admin account - the rank filtering list_users() "
     "already does, left where it is because the CLI shares it")
def t_rank_filtering_is_list_users_own():
    base()
    AUTH.make_user("Admin", login_id="admin2", name="Admin Two")

    seen_admin = {u["login_id"] for u in as_admin().get("/api/users").get_json()["users"]}
    assert OP in seen_admin, seen_admin
    assert ADMIN in seen_admin, "an Admin cannot see their own row"
    assert "admin2" not in seen_admin, \
        "an Admin saw another Admin's row: %s" % seen_admin

    seen_super = {u["login_id"] for u in as_super().get("/api/users").get_json()["users"]}
    assert {OP, ADMIN, "admin2"} <= seen_super, seen_super


@test("the list carries no hashes and no secrets - only what the screen "
     "renders")
def t_list_leaks_nothing():
    base()
    users = as_super().get("/api/users").get_json()["users"]
    allowed = {"login_id", "display_name", "role", "active", "station",
               "locked_minutes"}
    for u in users:
        extra = set(u) - allowed
        assert not extra, "unexpected fields in the response: %s" % extra
    blob = repr(users).lower()
    for bad in ("hash", "pw_", "secret", "totp", "token"):
        assert bad not in blob, "%r appears in the users response" % bad


@test("a locked account reports minutes left, rounded up - never the raw "
     "epoch, which means nothing on screen and invites a client clock "
     "being trusted to decide whether the lock is over")
def t_lock_reported_as_minutes():
    base()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET locked_until=%s WHERE login_id=%s",
                    (int(time.time()) + 400, OP))
    users = {u["login_id"]: u for u in as_super().get("/api/users").get_json()["users"]}
    assert users[OP]["locked_minutes"] == 7, users[OP]      # 400s rounds up to 7
    assert users[ADMIN]["locked_minutes"] == 0, users[ADMIN]
    assert "locked_until" not in users[OP], "the raw epoch reached the client"


@test("the list is gated like every other admin surface: an operator is "
     "refused, and a caller with no session at all gets 401")
def t_list_is_gated():
    base()
    r = client_as(OP, "FQC Operator").get("/api/users")
    assert r.status_code == 403, r.status_code
    anon = APP.app.test_client().get("/api/users")
    assert anon.status_code == 401, anon.status_code


# --------------------------------------------------------------------------
# 2 - the four account actions
# --------------------------------------------------------------------------

# The one refusal every hierarchy violation must produce. Sharing the
# constant is the point: if any endpoint ever answers something more
# specific, the tests below stop matching and the leak is caught.
HIERARCHY_REFUSAL = "Not found."


@test("reset-password works on an operator, and surfaces icon_auth's own "
     "policy message for a weak one rather than a paraphrase of it")
def t_reset_password_operator():
    base()
    c = as_super()
    before = user_row(OP)["pw_hash"]
    r = c.post("/api/users/%s/reset-password" % OP,
              json={"temp_password": "CorrectHorse99"})
    assert r.status_code == 200, r.get_json()
    assert user_row(OP)["pw_hash"] != before, "the password was not changed"
    assert user_row(OP)["must_change_pw"] == 1, "operator not forced to change it"

    weak = c.post("/api/users/%s/reset-password" % OP, json={"temp_password": "abc"})
    assert weak.status_code == 403, weak.status_code
    assert weak.get_json()["why"] == "Password must be at least 8 characters.", \
        weak.get_json()


@test("reset-password on an Admin target says to use Reset TOTP instead - "
     "but only for someone allowed to act on them; an Admin asking about "
     "another Admin still just gets 'Not found.'")
def t_reset_password_refuses_totp_roles():
    base()
    AUTH.make_user("Admin", login_id="admin2", name="Admin Two")

    r = as_super().post("/api/users/admin2/reset-password",
                        json={"temp_password": "CorrectHorse99"})
    assert r.status_code == 400, r.status_code
    assert "use Reset TOTP instead" in r.get_json()["why"], r.get_json()

    # the same request from an Admin must NOT reveal that admin2 exists or
    # what role it holds
    r2 = as_admin().post("/api/users/admin2/reset-password",
                         json={"temp_password": "CorrectHorse99"})
    assert r2.get_json()["why"] == HIERARCHY_REFUSAL, r2.get_json()


@test("every hierarchy violation is indistinguishable from a login_id that "
     "does not exist - another Admin, a Super Admin and a ghost all give "
     "the byte-identical refusal, on every action")
def t_hierarchy_refusals_are_identical():
    base()
    AUTH.make_user("Admin", login_id="admin2", name="Admin Two")
    c = as_admin()
    for action in ("reset-password", "reset-totp", "unlock",
                   "deactivate", "reactivate"):
        seen = []
        for target in ("admin2", SA, "no-such-person"):
            r = c.post("/api/users/%s/%s" % (target, action),
                      json={"temp_password": "CorrectHorse99"})
            seen.append((r.status_code, r.get_json()["why"]))
        assert len(set(seen)) == 1, \
            "%s leaks which target is which: %s" % (action, seen)
        assert seen[0] == (403, HIERARCHY_REFUSAL), (action, seen[0])


@test("reset-totp issues a real enrolment token for an Admin target, and "
     "refuses an operator, who has no authenticator to reset")
def t_reset_totp():
    base()
    AUTH.make_user("Admin", login_id="admin2", name="Admin Two")
    r = as_super().post("/api/users/admin2/reset-totp")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert len(d["token"]) == 32, d
    assert "admin2" in d["enrol_url"] and d["token"] in d["enrol_url"], d
    assert user_row("admin2")["must_reenrol"] in (0, 1)

    op = as_super().post("/api/users/%s/reset-totp" % OP)
    assert op.get_json()["why"] == "Operators do not use TOTP.", op.get_json()


@test("unlock clears a real lock, and the account stops reporting minutes "
     "left on the list afterwards")
def t_unlock():
    base()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET locked_until=%s, failed_count=9 "
                    "WHERE login_id=%s", (int(time.time()) + 600, OP))
    c = as_admin()
    assert {u["login_id"]: u for u in c.get("/api/users").get_json()["users"]}[OP]["locked_minutes"] == 10

    assert c.post("/api/users/%s/unlock" % OP).status_code == 200
    row = user_row(OP)
    assert row["locked_until"] == 0 and row["failed_count"] == 0, row
    assert {u["login_id"]: u for u in c.get("/api/users").get_json()["users"]}[OP]["locked_minutes"] == 0


@test("deactivate stops the account signing in, reactivate lets it back - "
     "including an account that was deactivated before reactivate existed")
def t_deactivate_reactivate_round_trip():
    base()
    c = as_admin()
    assert c.post("/api/users/%s/deactivate" % OP).status_code == 200
    assert user_row(OP)["active"] == 0

    # deactivated accounts really are refused at login, not merely flagged
    with store.conn() as (cx, cur):
        icon_auth.set_temp_password(cur, SA, OP, "CorrectHorse99")
    login = APP.app.test_client().post(
        "/login", json={"login_id": OP, "credential": "CorrectHorse99"})
    assert login.status_code == 401, "a deactivated account signed in"

    assert c.post("/api/users/%s/reactivate" % OP).status_code == 200
    assert user_row(OP)["active"] == 1
    back = APP.app.test_client().post(
        "/login", json={"login_id": OP, "credential": "CorrectHorse99"})
    assert back.status_code == 200 and back.get_json()["ok"], back.get_json()


@test("an account switched off directly in the database - as one "
     "deactivated before this round would be - reactivates the same way")
def t_reactivate_pre_existing():
    base()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET active=0 WHERE login_id=%s", (OP,))
    assert as_admin().post("/api/users/%s/reactivate" % OP).status_code == 200
    assert user_row(OP)["active"] == 1


@test("nobody can deactivate or reactivate themselves out of the hierarchy")
def t_no_self_service():
    base()
    r = as_admin().post("/api/users/%s/deactivate" % ADMIN)
    assert r.get_json()["why"] == "Cannot deactivate yourself.", r.get_json()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET active=0 WHERE login_id=%s", (ADMIN,))
    r2 = as_admin().post("/api/users/%s/reactivate" % ADMIN)
    assert r2.get_json()["why"] == "Cannot reactivate yourself.", r2.get_json()


@test("every action is gated to Admin and Super Admin - an operator is "
     "refused, an anonymous caller gets 401")
def t_actions_are_gated():
    base()
    op = client_as(OP, "FQC Operator")
    anon = APP.app.test_client()
    for action in ("reset-password", "reset-totp", "unlock",
                   "deactivate", "reactivate"):
        assert op.post("/api/users/%s/%s" % (OP, action), json={}).status_code == 403
        assert anon.post("/api/users/%s/%s" % (OP, action), json={}).status_code == 401


# --------------------------------------------------------------------------
# 3 - create
# --------------------------------------------------------------------------

def create(c, **body):
    return c.post("/api/users", json=body)


@test("an Admin can create an operator, who lands with a forced password "
     "change and shows up on the list immediately")
def t_create_operator():
    base()
    r = create(as_admin(), login_id="newop", display_name="New Op",
               role="FQC Operator", temp_password="CorrectHorse99",
               station="FQC-01")
    assert r.status_code == 200, r.get_json()
    row = user_row("newop")
    assert row["role"] == "FQC Operator" and row["station"] == "FQC-01", row
    assert row["must_change_pw"] == 1, "a temp password was not marked temporary"
    listed = {u["login_id"] for u in as_admin().get("/api/users").get_json()["users"]}
    assert "newop" in listed


@test("there is NO path to Super Admin from this screen - refused for an "
     "Admin and for a Super Admin alike. The only door is "
     "icon_auth_cli.py, run on the server")
def t_super_admin_cannot_be_created():
    base()
    for c, who in ((as_admin(), "Admin"), (as_super(), "Super Admin")):
        r = create(c, login_id="sa_new", display_name="Sneaky",
                   role="Super Admin", temp_password="CorrectHorse99")
        assert r.status_code == 403, "%s got %s" % (who, r.status_code)
        assert "icon_auth_cli.py" in r.get_json()["why"], r.get_json()
        assert user_row("sa_new") is None, "%s created a Super Admin" % who


@test("creating an Admin is Super-Admin-only, and returns the enrolment "
     "link rather than a password - an Admin account has no password path")
def t_create_admin_is_super_admin_only():
    base()
    refused = create(as_admin(), login_id="admin9", display_name="Admin Nine",
                     role="Admin")
    assert refused.status_code == 403, refused.get_json()
    assert refused.get_json()["why"] == \
        "Only a Super Admin can create an Admin account.", refused.get_json()
    assert user_row("admin9") is None

    ok = create(as_super(), login_id="admin9", display_name="Admin Nine",
                role="Admin")
    assert ok.status_code == 200, ok.get_json()
    d = ok.get_json()
    assert len(d["token"]) == 32 and "admin9" in d["enrol_url"], d
    assert user_row("admin9")["role"] == "Admin"
    assert not user_row("admin9")["pw_hash"], \
        "an Admin was created with a password"


@test("a weak temp password is refused with the policy's own sentence, and "
     "creates nobody")
def t_create_weak_password():
    base()
    r = create(as_super(), login_id="weakop", display_name="Weak Op",
               role="FQC Operator", temp_password="abc")
    assert r.status_code == 400, r.get_json()
    assert r.get_json()["why"] == "Password must be at least 8 characters.", \
        r.get_json()
    assert user_row("weakop") is None


@test("a duplicate login ID, an unknown role and a missing name are clear "
     "400s - not a 500 out of a constraint violation")
def t_create_bad_input():
    base()
    c = as_super()
    create(c, login_id="dup", display_name="Dup", role="FQC Operator",
           temp_password="CorrectHorse99")

    cases = [
        (dict(login_id="dup", display_name="Again", role="FQC Operator",
              temp_password="CorrectHorse99"), "That login ID already exists."),
        (dict(login_id="x1", display_name="X", role="Wizard",
              temp_password="CorrectHorse99"),
         "'Wizard' is not a role this screen can create."),
        (dict(login_id="x2", display_name="", role="FQC Operator",
              temp_password="CorrectHorse99"), "A name is required."),
        (dict(login_id="", display_name="X", role="FQC Operator",
              temp_password="CorrectHorse99"), "A login ID is required."),
    ]
    for body, want in cases:
        r = create(c, **body)
        assert r.status_code == 400, (body, r.status_code)
        assert r.get_json()["why"] == want, (body, r.get_json())


@test("create is gated like every other admin surface")
def t_create_is_gated():
    base()
    body = dict(login_id="nope", display_name="Nope", role="FQC Operator",
                temp_password="CorrectHorse99")
    assert create(client_as(OP, "FQC Operator"), **body).status_code == 403
    assert APP.app.test_client().post("/api/users", json=body).status_code == 401
    assert user_row("nope") is None


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
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
    sys.exit(1 if failed else 0)
