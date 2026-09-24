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
