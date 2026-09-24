"""
ICON TRACE - Round 23: every write endpoint's role gate, proved.

    python test_role_gates.py

This is the file that proves the original vulnerability is closed. Until
this round, who you were (X-User-Name) and what you were allowed to do
(X-User-Role) were both client-sent headers - anyone with devtools could
set either to anything, and 36 of the 41-odd write endpoints checked
neither. Business-logic tests passing says nothing about that; this says it.

The map is not re-typed here. It is read back out of app.py's own
decorators, so this file cannot drift from what is actually deployed: add
a write endpoint without a gate and the coverage test below fails; change
a gate and this file tests the new one.

What is asserted is the GATE, not the endpoint's business logic. Each
endpoint is called with a deliberately empty body, so:

    allowed role  -> anything EXCEPT 401/403 (a 400 "bad request" is a
                     pass: the gate let it through and the body was junk)
    wrong role    -> 403 exactly, "I know who you are, and no"
    no session    -> 401 exactly, "who are you"

401 and 403 are kept distinct on purpose, and that distinction is itself
asserted for every endpoint.
"""

import os, re, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_gates_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store
import app as APP
import auth_test_helper as AUTH

ALL_ROLES = AUTH.ALL_ROLES

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# --------------------------------------------------------------------------
# Read the real map back out of app.py's decorators
# --------------------------------------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))
_SRC = open(os.path.join(BASE, "app.py"), encoding="utf-8").read().split("\n")

# Not role-gated by design, each for its own reason, and each covered by
# its own test file instead of this one:
#   /login                        public - there is no session yet
#   /logout                       kills its own session
#   /api/session/extend           role-independent, does its own 401
#   /api/session/change-password  the ONE thing an account holding a
#                                 temporary password may do; require_role()
#                                 refuses everything else while
#                                 must_change_pw stands, so gating this
#                                 would lock such an account out entirely
#   /enrol                        public by necessity - this is what
#                                 somebody does BEFORE they can sign in,
#                                 and the enrolment token is the whole of
#                                 the authorisation
_AUTH_ROUTES = {"/login", "/logout", "/api/session/extend",
                "/api/session/change-password", "/enrol"}

_PARAM = {"int": "1", "path": "X-1", "string": "X-1"}


def _concrete(path):
    """/api/box/<int:box_id>/scan -> /api/box/1/scan"""
    def sub(m):
        kind = m.group(1) or "string"
        return _PARAM.get(kind, "1")
    return re.sub(r"<(?:(\w+):)?\w+>", sub, path)


def _screen_roles(screen_id):
    import icon_auth
    sid = icon_auth.SUBVIEWS.get(screen_id, screen_id)
    return tuple(r for r in ALL_ROLES
                 if icon_auth.default_perms_for_role(r)[sid]["write"])


def read_map():
    """[(path, methods, allowed_roles_tuple)] straight from the source."""
    out, i = [], 0
    while i < len(_SRC):
        s = _SRC[i].strip()
        if not (s.startswith("@app.route(") and
                re.search(r"(POST|PUT|DELETE|PATCH)", s)):
            i += 1
            continue
        paths, j = [], i
        while j < len(_SRC) and _SRC[j].strip().startswith("@app.route("):
            m = re.search(r'@app\.route\("([^"]+)"(.*)', _SRC[j].strip())
            meths = re.findall(r"(GET|POST|PUT|DELETE|PATCH)", m.group(2)) or ["GET"]
            paths.append((m.group(1), meths))
            j += 1
        window = "\n".join(_SRC[j:j + 14])
        g = re.search(r"@require_role\((\*?[A-Za-z_][\w]*|[^)]*)\)", window)
        sg = re.search(r'@require_screen_write\("([\w-]+)"\)', window)
        roles = None
        if sg and (not g or sg.start() < g.start()):
            # Round 27: gated on the account's own write flag for a screen.
            # Every test account is seeded with its role's defaults (as a
            # real new account is), so the roles that pass are exactly the
            # roles whose defaults grant write there - and every assertion
            # below still holds with no change to what it means.
            g = None
            roles = _screen_roles(sg.group(1)) or None
        if g:
            token = g.group(1).strip()
            if token.startswith("*"):
                const = getattr(APP, token[1:], None)
                roles = tuple(const) if const else None
            else:
                roles = tuple(x.strip().strip("\"'")
                              for x in token.split(",") if x.strip())
        for p, meths in paths:
            if p in _AUTH_ROUTES:
                continue
            out.append((p, [m for m in meths if m != "GET"] or meths, roles))
        i = j
    return out


ENDPOINTS = read_map()


def call(client, path, method):
    fn = {"POST": client.post, "PUT": client.put,
          "DELETE": client.delete, "PATCH": client.patch}[method]
    # An empty JSON body on purpose - the gate runs before any of these
    # endpoints look at what was sent.
    return fn(_concrete(path), json={})


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


# The role gate's own refusal, word for word. It matters that this is
# distinguishable: /api/db/reset carries a SECOND, independent guard from
# Stage 0 (ICON_ALLOW_RESET) which also answers 403, and "the role gate
# refused you" and "this server has resets switched off" are different
# facts. Both apply; neither replaces the other.
_GATE_403 = "Not permitted for your role."


def past_gate(resp):
    """True when the role gate allowed this through, whatever the endpoint
    then decided on its own account (a 400 on an empty body, or the reset
    endpoint's own disabled-here 403)."""
    if resp.status_code == 401:
        return False
    if resp.status_code == 403:
        return (resp.get_json() or {}).get("why") != _GATE_403
    return True


# --------------------------------------------------------------------------

@test("every write endpoint in app.py carries a role gate - none was "
     "missed, and a new ungated one will fail this test")
def t_every_write_endpoint_is_gated():
    ungated = [p for p, _m, roles in ENDPOINTS if roles is None]
    # /api/review/resolve is gated per-branch inside the handler (the
    # allowed role depends on the item type), but still carries a blanket
    # decorator, so it is not expected here.
    assert not ungated, ("write endpoints with no @require_role or "
                         "@require_screen_write: %s" % ungated)
    assert len(ENDPOINTS) >= 45, \
        "only found %d write endpoints - the reader is broken" % len(ENDPOINTS)


@test("no session at all: every write endpoint answers 401 'Sign in "
     "required.' - never 403, never a business-logic answer")
def t_anonymous_gets_401_everywhere():
    fresh()
    c = APP.app.test_client()
    bad = []
    for path, meths, roles in ENDPOINTS:
        r = call(c, path, meths[0])
        if r.status_code != 401:
            bad.append("%s %s -> %s" % (meths[0], path, r.status_code))
    assert not bad, "endpoints reachable without a session:\n  " + "\n  ".join(bad)


@test("a session in an ALLOWED role gets past the gate on every endpoint - "
     "never 401, never 403 (a 400 on an empty body is the gate letting it "
     "through, which is the point)")
def t_allowed_role_passes_every_gate():
    bad = []
    for path, meths, roles in ENDPOINTS:
        fresh()
        c = APP.app.test_client()
        AUTH.test_login(c, role=roles[0])
        r = call(c, path, meths[0])
        if not past_gate(r):
            bad.append("%s %s as %s -> %s %s"
                       % (meths[0], path, roles[0], r.status_code,
                          (r.get_json() or {}).get("why")))
    assert not bad, "allowed role refused:\n  " + "\n  ".join(bad)


@test("a session in a DISALLOWED role gets 403 'Not permitted for your "
     "role.' on every endpoint that has one - the real proof a spoofed "
     "role no longer works, because there is no longer a role to spoof")
def t_disallowed_role_gets_403_everywhere():
    bad = []
    for path, meths, roles in ENDPOINTS:
        outsiders = [r for r in ALL_ROLES if r not in roles]
        if not outsiders:
            continue                      # /api/export/xlsx permits everyone
        fresh()
        c = APP.app.test_client()
        AUTH.test_login(c, role=outsiders[0])
        r = call(c, path, meths[0])
        if r.status_code != 403:
            bad.append("%s %s as %s -> %s (expected 403)"
                       % (meths[0], path, outsiders[0], r.status_code))
    assert not bad, "disallowed role NOT refused:\n  " + "\n  ".join(bad)


@test("master data (materials, cell efficiencies, database reset) is Super "
     "Admin alone - an Admin is refused, which is the one place Admin is "
     "deliberately not enough")
def t_master_data_is_super_admin_only():
    master = [(p, m) for p, m, r in ENDPOINTS if r == ("Super Admin",)]
    assert len(master) >= 3, "expected materials/cell-eff/reset, got %s" % master
    for path, meths in master:
        fresh()
        c = APP.app.test_client()
        AUTH.test_login(c, role="Admin")
        r = call(c, path, meths[0])
        assert r.status_code == 403 and \
            (r.get_json() or {}).get("why") == _GATE_403, \
            "%s %s let an Admin past the role gate (%s)" % (meths[0], path,
                                                            r.status_code)
        fresh()
        c2 = APP.app.test_client()
        AUTH.test_login(c2, role="Super Admin")
        r2 = call(c2, path, meths[0])
        assert past_gate(r2), \
            "%s %s refused a Super Admin (%s)" % (meths[0], path, r2.status_code)


@test("/api/db/reset keeps BOTH guards - Stage 0's ICON_ALLOW_RESET and "
     "this round's Super-Admin-only role gate. Neither replaces the other, "
     "and they refuse for visibly different reasons")
def t_reset_has_both_guards():
    fresh()
    admin = APP.app.test_client()
    AUTH.test_login(admin, role="Admin")
    r_role = admin.post("/api/db/reset", json={})
    assert r_role.status_code == 403
    assert r_role.get_json()["why"] == _GATE_403, \
        "the role gate did not refuse an Admin: %s" % r_role.get_json()

    fresh()
    sa = APP.app.test_client()
    AUTH.test_login(sa, role="Super Admin")
    r_flag = sa.post("/api/db/reset", json={})
    # ICON_ALLOW_RESET is not set for the test suite, so the second guard
    # is what refuses here - proving the role gate did not swallow it.
    assert r_flag.status_code == 403
    assert "ICON_ALLOW_RESET" in r_flag.get_json()["why"], \
        "expected the reset flag guard, got %s" % r_flag.get_json()


@test("settings are master data, not ordinary Admin config: an Admin is "
     "refused on BOTH the JSON route and the HTML form, and neither writes "
     "anything - the form would otherwise be a way round the gate")
def t_settings_is_super_admin_only():
    import db
    for role, want in (("Admin", 403), ("Super Admin", 200)):
        fresh()
        c = APP.app.test_client()
        AUTH.test_login(c, role=role)

        r = c.post("/api/settings", json={"grade_a_min": "317"})
        assert r.status_code == want, \
            "POST /api/settings as %s -> %s" % (role, r.status_code)

        f = c.post("/settings", data={"grade_b_min": "271"})
        assert f.status_code == want, \
            "POST /settings (form) as %s -> %s" % (role, f.status_code)

        with store.conn() as (cx, cur):
            cfg = db.get_config(cur)
        if want == 403:
            assert cfg.get("grade_a_min") != "317" and \
                   cfg.get("grade_b_min") != "271", \
                "an Admin's refused save still reached app_config: %s" % cfg
        else:
            assert cfg.get("grade_a_min") == "317", cfg
            assert cfg.get("grade_b_min") == "271", \
                "the form did not save for a Super Admin: %s" % cfg


@test("an Admin can still READ the settings page and prepare an import - "
     "master data is Super Admin to write, not to look at")
def t_admin_keeps_read_access_to_master_screens():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c, role="Admin")
    assert c.get("/settings").status_code == 200
    assert c.get("/admin/challan-import").status_code == 200
    # CHECK writes nothing, so it stays open to Admin...
    assert c.post("/admin/challan-import",
                 data={"action": "check"}).status_code == 200
    # ...while LOAD, which writes the batch in, does not.
    assert c.post("/admin/challan-import",
                 data={"action": "load"}).status_code == 403


@test("401 and 403 stay distinct on the same endpoint: no session is 'who "
     "are you', a known-but-wrong role is 'I know who you are and the "
     "answer is no'")
def t_401_and_403_are_distinct():
    path, meths, roles = next((p, m, r) for p, m, r in ENDPOINTS
                             if r and len(r) < len(ALL_ROLES))
    outsider = next(r for r in ALL_ROLES if r not in roles)

    fresh()
    anon = APP.app.test_client()
    r_anon = call(anon, path, meths[0])

    fresh()
    wrong = APP.app.test_client()
    AUTH.test_login(wrong, role=outsider)
    r_wrong = call(wrong, path, meths[0])

    assert r_anon.status_code == 401, r_anon.status_code
    assert r_wrong.status_code == 403, r_wrong.status_code
    assert r_anon.get_json()["why"] != r_wrong.get_json()["why"]


@test("the audit trail records the session's real name, not anything the "
     "client sent - a forged X-User-Name header changes nothing")
def t_audit_records_session_identity():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c, role="Packing Operator")
    r = c.post("/api/box/open",
              json={"grade": "A", "model": "ISEN630-G12R", "capacity": 2},
              headers={"X-User-Name": "Somebody Else",
                       "X-User-Role": "Super Admin"})
    assert r.status_code == 200, r.get_json()
    box_id = r.get_json()["box_id"]
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM box WHERE box_id=%s", (box_id,))
    opened_by = (row or {}).get("opened_by") or (row or {}).get("created_by")
    assert opened_by == "Test Packing Operator", \
        "audit recorded %r - the forged header won" % opened_by


@test("a forged X-User-Role header cannot promote anyone: the same wrong-"
     "role session is still refused while claiming to be Super Admin")
def t_forged_role_header_is_ignored():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c, role="FQC Operator")
    r = c.post("/api/material", json={"name": "X", "uom": "Nos"},
              headers={"X-User-Role": "Super Admin"})
    assert r.status_code == 403, \
        "a forged X-User-Role header got past the gate (%s)" % r.status_code


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    print("\n%d write endpoints read out of app.py\n" % len(ENDPOINTS))
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
