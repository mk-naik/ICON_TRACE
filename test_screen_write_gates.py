"""
ICON TRACE - Round 27: write endpoints gated on the account's own per-screen
write flag, proved endpoint by endpoint.

    python test_screen_write_gates.py

The map is not re-typed here. It is read back out of app.py's own
@require_screen_write("<screen>") decorators, so this file cannot drift from
what is deployed, and each endpoint gets the same three cases generated for
it:

    write flag True on its screen   -> past the gate (anything but 401 and
                                       the gate's own 403 - a 400 on an
                                       empty body is the gate letting it in)
    write flag False, or no row     -> 403 "Not permitted for your role."
    no session                      -> 401 "Sign in required."

The account used is chosen to make the flag, not the role, the only thing
that can explain the answer: a Quality account (whose role reaches none of
these screens but Needs Review) is GIVEN write and must pass; a Super Admin
(whose role reaches all of them) has it TAKEN AWAY and must be refused.

Then must_change_pw through the new gate, and the surface that stays on
role gates. The six inline _require_role checks inside individual
endpoints have their own file, test_inner_role_checks.py.
"""

import os, re, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_scrgate_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# --------------------------------------------------------------------------
# The map, read out of app.py
# --------------------------------------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))
_SRC = open(os.path.join(BASE, "app.py"), encoding="utf-8").read().split("\n")
_PARAM = {"int": "1", "path": "X-1", "string": "X-1"}


def _concrete(path):
    return re.sub(r"<(?:(\w+):)?\w+>",
                  lambda m: _PARAM.get(m.group(1) or "string", "1"), path)


def read_screen_map():
    """[(path, method, screen, function)] for every route whose gate is
    @require_screen_write. One row per route line, write method first."""
    out = []
    for i, line in enumerate(_SRC):
        m = re.match(r'@require_screen_write\("([\w-]+)"\)$', line.strip())
        if not m:
            continue
        fn = next(re.match(r"def (\w+)\(", _SRC[k]).group(1)
                  for k in range(i + 1, i + 6) if _SRC[k].startswith("def "))
        k = i - 1
        while k >= 0 and not _SRC[k].startswith("@app.route("):
            k -= 1                      # skip comments between route and gate
        while k >= 0 and _SRC[k].startswith("@app.route("):
            r = re.search(r'@app\.route\("([^"]+)"(.*)', _SRC[k])
            meths = re.findall(r"(POST|PUT|DELETE|PATCH)", r.group(2))
            out.append((r.group(1), meths[0], m.group(1), fn))
            k -= 1
    return out


SCREEN_MAP = read_screen_map()

# What the map must be - the review-before-apply map from the Round 27
# report, written down once so a silent re-mapping fails here.
EXPECTED = {
    "challan":   {"api_challan_create", "api_challan_cancel",
                  "api_challan_discard", "api_challan_edit_draft",
                  "api_challan_edit_save", "api_challan_submit",
                  "api_challan_checks"},
    "gp":        {"api_gatepass", "api_gatepass_update", "gatepass"},
    "invoice":   {"api_invoice_confirm", "api_invoice_parse",
                  "invoice_cancel", "invoice_confirm", "invoice_parse"},
    "disp":      {"dispatch"},
    "review":    {"api_review_resolve"},
    "fqc":       {"api_fqc_grade", "fqc"},
    "loadver":   {"api_loading_confirm", "api_loading_submit"},
    "pack":      {"api_box_abandon", "api_box_capacity", "api_box_close",
                  "api_box_remove", "api_box_repack", "api_box_scan",
                  "api_box_open", "packing"},
    "repack":    {"api_repack"},
    "plan":      {"api_allocation_create", "api_allocation_cancel",
                  "api_allocation_update", "planning"},
    "indent":    {"api_indent_create", "api_indent_update", "indent_new"},
    "loss":      {"api_loss_event_open", "api_loss_event_close"},
    "prodentry": {"api_prodentry"},
}

_GATE_403 = "Not permitted for your role."


def call(c, path, method):
    fn = {"POST": c.post, "PUT": c.put, "DELETE": c.delete,
          "PATCH": c.patch}[method]
    return fn(_concrete(path), json={})


def past_gate(r):
    if r.status_code == 401:
        return False
    if r.status_code == 403:
        return (r.get_json(silent=True) or {}).get("why") != _GATE_403
    return True


def gate_refused(r):
    return r.status_code == 403 and \
        (r.get_json(silent=True) or {}).get("why") == _GATE_403


def set_perm(login_id, screen, view, write):
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, "cli", login_id,
                                   {screen: {"view": view, "write": write}})


def drop_perm(login_id, screen):
    with store.conn() as (cx, cur):
        cur.execute("DELETE FROM user_screen_perm WHERE screen_id=%s AND "
                    "user_id=(SELECT user_id FROM app_user WHERE login_id=%s)",
                    (screen, login_id))


def write_flag(login_id, screen):
    with store.conn() as (cx, cur):
        return icon_auth.get_screen_perms(cur, login_id)[screen]["write"]


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


# --------------------------------------------------------------------------
# The map itself
# --------------------------------------------------------------------------

@test("the map read out of app.py is exactly the reviewed map - 40 view "
     "functions on 13 screens, every one a real, non-excluded screen")
def t_map_is_the_reviewed_map():
    got = {}
    for _p, _m, screen, fn in SCREEN_MAP:
        got.setdefault(screen, set()).add(fn)
    assert got == EXPECTED, "map drifted:\n  got      %s\n  expected %s" % (
        sorted((k, sorted(v)) for k, v in got.items()),
        sorted((k, sorted(v)) for k, v in EXPECTED.items()))
    assert sum(len(v) for v in got.values()) == 40
    for s in got:
        assert s in icon_auth.SCREEN_IDS and s not in icon_auth.EXCLUDED_SCREENS, s
    print("      %d route lines, %d functions" % (
        len(SCREEN_MAP), sum(len(v) for v in got.values())))


@test("admin and items can never be put on a per-user flag - "
     "require_screen_write refuses them, and a typo, at import time")
def t_excluded_screens_refused_at_decoration():
    for bad in ("admin", "items", "no-such-screen"):
        try:
            APP.require_screen_write(bad)
        except ValueError as e:
            print("      %-15s -> ValueError: %s" % (bad, e))
        else:
            raise AssertionError("require_screen_write(%r) was accepted" % bad)
    # A sub-view resolves to its parent rather than being refused.
    assert APP.require_screen_write("gp-list")(lambda: None).icon_screen == "gp"


@test("the critical surface stays on role gates, untouched: master data, "
     "settings, challan import and user management")
def t_critical_surface_keeps_role_gates():
    want = {
        "/api/material": "_R_MASTER", "/api/material/<int:n>": "_R_MASTER",
        "/api/cell-efficiencies": "_R_MASTER", "/api/db/reset": "_R_MASTER",
        "/api/settings": "_R_MASTER", "/settings": "_R_ADMIN",
        "/admin/challan-import": "_R_ADMIN", "/api/users": "_R_ADMIN",
        "/api/users/<login_id>/reset-password": "_R_ADMIN",
        "/api/users/<login_id>/reset-totp": "_R_ADMIN",
        "/api/users/<login_id>/unlock": "_R_ADMIN",
        "/api/users/<login_id>/deactivate": "_R_ADMIN",
        "/api/users/<login_id>/reactivate": "_R_ADMIN",
        "/api/export/xlsx": "_R_EVERY", "/api/quality": "_R_QUALITY",
    }
    for path, const in want.items():
        i = next(n for n, l in enumerate(_SRC)
                 if l.startswith('@app.route("%s"' % path))
        window = "\n".join(_SRC[i:i + 10])
        assert "@require_role(*%s)" % const in window, (path, window)
        assert "@require_screen_write" not in window.split("def ")[0], path


# --------------------------------------------------------------------------
# Mechanical, per endpoint
# --------------------------------------------------------------------------

@test("write flag TRUE on the endpoint's screen gets past the gate on every "
     "endpoint - for a Quality account whose ROLE reaches none of them")
def t_flag_true_passes():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Quality")["login_id"]
    bad = []
    for path, meth, screen, _fn in SCREEN_MAP:
        set_perm(me, screen, True, True)
        r = call(c, path, meth)
        if not past_gate(r):
            bad.append("%s %s [%s] -> %s" % (meth, path, screen, r.status_code))
        if screen != "review":           # Quality's own default stays as it was
            set_perm(me, screen, False, False)
    assert not bad, "flag was True, still refused:\n  " + "\n  ".join(bad)
    print("      %d endpoints passed with write granted" % len(SCREEN_MAP))


@test("write flag FALSE on the endpoint's screen is 403 'Not permitted for "
     "your role.' on every endpoint - for a Super Admin, whose ROLE reaches "
     "all of them, and even with view left on")
def t_flag_false_refused():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Super Admin")["login_id"]
    bad = []
    for path, meth, screen, _fn in SCREEN_MAP:
        set_perm(me, screen, True, False)
        r = call(c, path, meth)
        if not gate_refused(r):
            bad.append("%s %s [%s] -> %s %s" % (meth, path, screen, r.status_code,
                       (r.get_json(silent=True) or {}).get("why")))
        set_perm(me, screen, True, True)
    assert not bad, "write was False, not refused:\n  " + "\n  ".join(bad)
    print("      %d endpoints refused with write withdrawn" % len(SCREEN_MAP))


@test("NO ROW for the endpoint's screen is 403 on every endpoint - absence "
     "is no access, never 'fall back to the role'")
def t_no_row_refused():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Super Admin")["login_id"]
    bad = []
    for path, meth, screen, _fn in SCREEN_MAP:
        drop_perm(me, screen)
        r = call(c, path, meth)
        if not gate_refused(r):
            bad.append("%s %s [%s] -> %s" % (meth, path, screen, r.status_code))
        set_perm(me, screen, True, True)
    assert not bad, "no row, not refused:\n  " + "\n  ".join(bad)


@test("an account with no permission rows at all - a pre-Round-26 account "
     "the migration has not reached - is refused on every endpoint")
def t_unmigrated_account_refused():
    fresh()
    with store.conn() as (cx, cur):
        cur.execute("INSERT INTO app_user (login_id, display_name, role, "
                    "station, created_at, created_by) VALUES "
                    "('old.admin', 'Old Admin', 'Admin', 'DISPATCH-01', 1, 'test')")
        u = store.one(cur, "SELECT * FROM app_user WHERE login_id='old.admin'")
        sid = icon_auth.create_session(cur, dict(u), station="DISPATCH-01",
                                       ip="127.0.0.1")
    c = APP.app.test_client()
    c.set_cookie("icon_sid", sid)
    bad = [p for p, m, _s, _f in SCREEN_MAP if not gate_refused(call(c, p, m))]
    assert not bad, bad


@test("no session is 401 'Sign in required.' on every endpoint")
def t_no_session_401():
    fresh()
    c = APP.app.test_client()
    bad = []
    for path, meth, screen, _fn in SCREEN_MAP:
        r = call(c, path, meth)
        if r.status_code != 401 or \
                (r.get_json(silent=True) or {}).get("why") != "Sign in required.":
            bad.append("%s %s -> %s" % (meth, path, r.status_code))
    assert not bad, bad


@test("must_change_pw is still refused through the new gate on every "
     "endpoint, write flag or not - and clears once the password is set")
def t_must_change_pw_through_new_gate():
    fresh()
    c = APP.app.test_client()
    me = AUTH.test_login(c, role="Super Admin")["login_id"]
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET must_change_pw=1 WHERE login_id=%s", (me,))
    bad = []
    for path, meth, screen, _fn in SCREEN_MAP:
        assert write_flag(me, screen) is True
        r = call(c, path, meth)
        if r.status_code != 403 or (r.get_json(silent=True) or {}).get("why") != \
                "Set your own password before saving anything.":
            bad.append("%s %s -> %s" % (meth, path, r.status_code))
    assert not bad, bad
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET must_change_pw=0 WHERE login_id=%s", (me,))
    assert past_gate(c.post("/api/challan/checks", json={}))


# --------------------------------------------------------------------------

if __name__ == "__main__":
    print("%d write route lines read out of app.py's @require_screen_write\n"
          % len(SCREEN_MAP))
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    for name, fn in _results:
        try:
            fn()
            print("  PASS  %-*s" % (width, name))
            passed += 1
        except Exception as e:
            print("  FAIL  %-*s  %s" % (width, name, e))
            traceback.print_exc()
            failed += 1
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
