"""
ICON TRACE - the one shared way a test gets a real, authenticated session.

TEST-ONLY. This is never imported by the running application and is never
exposed as a route - the only way to reach it is for a test file to import
it deliberately, which is exactly the gate Round 23 asked for. It creates a
genuine app_user row and a genuine auth_session row and puts the real cookie
on the test client; what it skips is the credential ceremony (password
policy, TOTP enrolment, the login timing floor), because a test of the
packing quantity gate should not have to spend 350ms proving it can type a
password.

    import auth_test_helper as AUTH
    ...
    def base():
        store.wipe()
        c = APP.app.test_client()
        AUTH.test_login(c)              # Super Admin by default
        return c

Default role is Super Admin on purpose: the existing suite is about business
logic, not access control, and those tests should not have to reason about
permissions they were never written to test. The files that ARE about roles
(test_review.py, test_fqc.py, test_role_gates.py) pass a real role instead.
"""

import store
import icon_auth

# A person is bound to a station; it is who they are, not a per-session
# choice. These are the same station ids v4's own screens use.
_DEFAULT_STATION = {
    "FQC Operator": "FQC-01",
    "Packing Operator": "PACK-01",
    "Dispatch Operator": "DISPATCH-01",
    "Production Incharge": "FQC-01",
    "Quality": "FQC-01",
    "Admin": "DISPATCH-01",
    "Super Admin": "DISPATCH-01",
}

_LOGIN_ID = {
    "FQC Operator": "test.fqc",
    "Packing Operator": "test.pack",
    "Dispatch Operator": "test.dispatch",
    "Production Incharge": "test.incharge",
    "Quality": "test.quality",
    "Admin": "test.admin",
    "Super Admin": "test.super",
}

ALL_ROLES = ("Super Admin", "Admin", "Production Incharge", "FQC Operator",
             "Packing Operator", "Dispatch Operator", "Quality")


def ensure_auth_schema():
    """store.wipe() deletes the database file outright and only rebuilds
    schema_sqlite.sql's own tables - icon_auth's are a separate schema it
    knows nothing about, so they have to be asked for again after a wipe."""
    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)


def make_user(role="Super Admin", login_id=None, name=None, station=None):
    """A real app_user row of `role`, reused if this role already has one."""
    login_id = login_id or _LOGIN_ID.get(role, "test.user")
    name = name or ("Test " + role)
    station = station if station is not None else _DEFAULT_STATION.get(role)
    ensure_auth_schema()
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM app_user WHERE login_id=%s",
                        (login_id,))
        if not row:
            cur.execute(
                "INSERT INTO app_user (login_id, display_name, role, station, "
                "created_at, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
                (login_id, name, role, station, 1000000, "test"))
            row = store.one(cur, "SELECT * FROM app_user WHERE login_id=%s",
                            (login_id,))
        return dict(row)


def make_session_id(role="Super Admin", login_id=None, name=None,
                    station=None):
    """Just the session id, for a caller that sets the cookie itself -
    a Playwright browser context, rather than a Flask test client."""
    u = make_user(role, login_id=login_id, name=name, station=station)
    with store.conn() as (cx, cur):
        return icon_auth.create_session(
            cur, {"user_id": u["user_id"], "login_id": u["login_id"],
                  "display_name": u["display_name"], "role": u["role"]},
            station=u.get("station"), ip="127.0.0.1")


def test_login(client, role="Super Admin", login_id=None, name=None,
               station=None):
    """Put a real session for `role` on `client`. Returns the session row's
    own details, so a test can assert against the same name the audit trail
    will record."""
    u = make_user(role, login_id=login_id, name=name, station=station)
    with store.conn() as (cx, cur):
        sid = icon_auth.create_session(
            cur, {"user_id": u["user_id"], "login_id": u["login_id"],
                  "display_name": u["display_name"], "role": u["role"]},
            station=u.get("station"), ip="127.0.0.1")
    client.set_cookie("icon_sid", sid)
    return {"session_id": sid, "login_id": u["login_id"], "role": u["role"],
            "name": u["display_name"], "station": u.get("station")}


def sign_out(client):
    """Drop the cookie without going through /logout - for a test that wants
    to prove an endpoint refuses an anonymous caller."""
    client.delete_cookie("icon_sid")
