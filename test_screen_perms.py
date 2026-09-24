"""
ICON TRACE - Round 26: per-screen permissions, the foundation.

    python test_screen_perms.py

This round changes nobody's access. It adds the table Round 27 will
enforce from and Round 28 will edit, and seeds it so every account's rows
say exactly what its role already grants. Most of what is tested here is
that "exactly": the registry against the live nav, the role defaults
against ROLES as the running page actually builds it, and the migration
screen by screen.
"""

import html, os, re, shutil, subprocess, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_perms_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store
import icon_auth

icon_auth.COOLDOWN_STEPS = ()
icon_auth.create_key()

BASE = os.path.dirname(os.path.abspath(__file__))
V4 = open(os.path.join(BASE, "templates", "icon_trace.html"), encoding="utf-8").read()
LIVE = open(os.path.join(BASE, "static", "icon_live.js"), encoding="utf-8").read()

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


# --------------------------------------------------------------------------
# The live nav, read from the files rather than from anybody's memory of it
# --------------------------------------------------------------------------

def live_nav():
    """{screen_id: (label, section)} from v4's nav plus NEW_VIEWS."""
    nav = re.search(r'<nav class="side" id="sidenav">(.*?)</nav>', V4, re.S).group(1)
    out, section = {}, None
    for m in re.finditer(r'<div class="nav-sec"[^>]*>([^<]+)</div>|'
                         r'<button class="nav-i"[^>]*data-v="([^"]+)"[^>]*>(.*?)</button>',
                         nav, re.S):
        if m.group(1):
            section = m.group(1).strip()
            continue
        label = re.sub(r"<em>.*?</em>|<b[^>]*>.*?</b>|<[^>]+>", "", m.group(3), flags=re.S)
        out[m.group(2)] = (html.unescape(label).strip(), section)

    block = re.search(r"var NEW_VIEWS = \[(.*?)\n  \];", LIVE, re.S).group(1)
    for entry in re.finditer(r"\{ id: '([^']+)',\s*label: '([^']+)'(.*?)\}", block, re.S):
        vid, label, rest = entry.groups()
        anchor = re.search(r"(?:after|before): '([^']+)'", rest)
        section = out[anchor.group(1)][1] if anchor and anchor.group(1) in out else None
        out[vid] = (label, section)
    return out


@test("the registry is exactly the live nav - every data-v in v4 and every "
     "NEW_VIEWS entry, same label, same section - minus admin and items")
def t_registry_matches_live_nav():
    nav = live_nav()
    live_ids = set(nav) - icon_auth.EXCLUDED_SCREENS
    assert live_ids == icon_auth.SCREEN_IDS, \
        "registry drifted from the nav:\n  only in nav:      %s\n  only in registry: %s" % (
            sorted(live_ids - icon_auth.SCREEN_IDS),
            sorted(icon_auth.SCREEN_IDS - live_ids))
    for sid, label, section in icon_auth.SCREENS:
        assert nav[sid] == (label, section), \
            "%s: registry says %r, nav says %r" % (sid, (label, section), nav[sid])


@test("admin and items are in the nav but never in the registry - the "
     "Super-Admin-only surface is not per-user togglable")
def t_critical_surface_excluded():
    nav = live_nav()
    for sid in ("admin", "items"):
        assert sid in nav, "%s is not in the nav any more - revisit this test" % sid
        assert sid not in icon_auth.SCREEN_IDS, "%s is per-user togglable" % sid


@test("every sub-view the live layer adds to ROLES maps to a real screen in "
     "the registry, so Round 27 can resolve it")
def t_subviews_resolve():
    for sub, parent in icon_auth.SUBVIEWS.items():
        assert parent in icon_auth.SCREEN_IDS, (sub, parent)
    pushed = set(re.findall(r"views\.push\('([^']+)'\)", LIVE)) | \
        {v for v in re.findall(r"'([a-z-]+)'",
                               re.search(r"var ROLES=\{(.*?)\};", V4, re.S).group(1))
         if "-" in v}
    stray = {v for v in pushed
             if v not in icon_auth.SCREEN_IDS and v not in icon_auth.SUBVIEWS
             and v not in icon_auth.EXCLUDED_SCREENS}
    assert not stray, "views in ROLES with no screen to belong to: %s" % sorted(stray)


# --------------------------------------------------------------------------
# Section 2 - the table and its functions
# --------------------------------------------------------------------------

def fresh():
    store.DB_PATH = os.path.join(TMP, "t%d.db" % len(os.listdir(TMP)))
    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)
        icon_auth.create_superadmin(cur, "sa1", "Super One")
        icon_auth.create_admin(cur, "cli", "admin1", "Admin One")
        icon_auth.create_admin(cur, "cli", "admin2", "Admin Two")
        icon_auth.create_operator(cur, "admin1", "op1", "Op One",
                                  "Dispatch Operator", "CorrectHorse99")


def live_roles_from_the_page():
    """ROLES exactly as the running page holds it after sign-in - v4's
    literal, plus every runtime change the live layer makes - read out of a
    real browser. The independent answer default_perms_for_role() is checked
    against, rather than re-running the same parser and agreeing with it."""
    import ui_harness as H
    import auth_test_helper as AUTH
    store.wipe()
    AUTH.ensure_auth_schema()
    try:
        with H.browser() as b:
            pg = H.open_page(b, wait_ms=1200, role="Super Admin")
            return pg.evaluate(
                "Object.fromEntries(Object.entries(ROLES).map("
                "([k, v]) => [k, v.views.slice()]))")
    finally:
        H.cleanup()


@test("default_perms_for_role() matches ROLES as the RUNNING page builds it, "
     "role by role and screen by screen - read out of a real browser after "
     "sign-in, so the live layer's runtime additions are included")
def t_defaults_match_the_running_page():
    page = live_roles_from_the_page()
    assert "Quality" in page, "the live layer's Quality role is missing from the page"
    for role, views in page.items():
        want_view = {icon_auth.SUBVIEWS.get(v, v) for v in views} & icon_auth.SCREEN_IDS
        got = icon_auth.default_perms_for_role(role)
        for sid in icon_auth.SCREEN_IDS:
            assert got[sid]["view"] == (sid in want_view), \
                "%s / %s: default says view=%s, the page says %s" % (
                    role, sid, got[sid]["view"], sid in want_view)
            assert got[sid]["write"] == (sid in want_view and
                                         sid not in icon_auth.READ_ONLY_SCREENS), (role, sid)


@test("the read-only screens default to write:false for every role; review "
     "does not, because it is where Quality resolves items")
def t_read_only_defaults():
    for role in ("Admin", "Production Incharge", "FQC Operator", "Packing Operator",
                 "Dispatch Operator", "Quality", "Super Admin"):
        d = icon_auth.default_perms_for_role(role)
        for sid in icon_auth.READ_ONLY_SCREENS:
            assert d[sid]["write"] is False, (role, sid)
    assert icon_auth.default_perms_for_role("Quality")["review"] == \
        {"view": True, "write": True}


@test("an unknown role gets no screens at all rather than an error or a "
     "guess")
def t_unknown_role_gets_nothing():
    d = icon_auth.default_perms_for_role("Wizard")
    assert set(d) == icon_auth.SCREEN_IDS
    assert not any(p["view"] or p["write"] for p in d.values())


@test("an account with no rows at all reads as every screen closed - the "
     "safe default, not an error and not open access")
def t_no_rows_is_no_access():
    fresh()
    with store.conn() as (cx, cur):
        cur.execute("INSERT INTO app_user (login_id, display_name, role, created_at) "
                    "VALUES ('bare', 'Bare', 'Admin', 1)")
        p = icon_auth.get_screen_perms(cur, "bare")
        ghost = icon_auth.get_screen_perms(cur, "nobody-at-all")
    for got in (p, ghost):
        assert set(got) == icon_auth.SCREEN_IDS
        assert not any(v["view"] or v["write"] for v in got.values()), got


@test("create_operator, create_admin and create_superadmin each leave a full "
     "row per screen behind, equal to their role's defaults - read back from "
     "the table, not inferred from the call not raising")
def t_new_accounts_are_seeded():
    fresh()
    with store.conn() as (cx, cur):
        for login_id, role in (("op1", "Dispatch Operator"), ("admin1", "Admin"),
                               ("sa1", "Super Admin")):
            n = store.one(cur, "SELECT COUNT(*) AS n FROM user_screen_perm p "
                               "JOIN app_user u ON u.user_id=p.user_id "
                               "WHERE u.login_id=%s", (login_id,))["n"]
            assert n == len(icon_auth.SCREEN_IDS), (login_id, n)
            assert icon_auth.get_screen_perms(cur, login_id) == \
                icon_auth.default_perms_for_role(role), login_id


@test("hierarchy: an Admin may set an operator's screens, and gets the same "
     "'Not found.' as everywhere else for another Admin, a Super Admin or a "
     "ghost")
def t_set_perms_hierarchy():
    fresh()
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, "admin1", "op1",
                                   {"challan": {"view": True, "write": False}})
        assert icon_auth.get_screen_perms(cur, "op1")["challan"] == \
            {"view": True, "write": False}
        for target in ("admin2", "sa1", "no-such-person"):
            try:
                icon_auth.set_screen_perms(cur, "admin1", target,
                                           {"gp": {"view": False, "write": False}})
                assert False, "an Admin changed %s's permissions" % target
            except icon_auth.AuthError as e:
                assert str(e) == "Not found.", (target, str(e))
        # a Super Admin can
        icon_auth.set_screen_perms(cur, "sa1", "admin2",
                                   {"gp": {"view": False, "write": False}})
        assert icon_auth.get_screen_perms(cur, "admin2")["gp"]["view"] is False


@test("nobody can change their own permissions - the hierarchy check allows "
     "acting on yourself, and here that would let a restricted account "
     "simply give itself the screen back")
def t_no_self_grant():
    fresh()
    with store.conn() as (cx, cur):
        try:
            icon_auth.set_screen_perms(cur, "admin1", "admin1",
                                       {"gp": {"view": True, "write": True}})
            assert False, "an Admin changed its own permissions"
        except icon_auth.AuthError as e:
            assert str(e) == "Cannot change your own permissions.", str(e)


@test("an unknown screen, a write-without-view and a malformed entry are "
     "refused outright - and refused BEFORE anything is written, so a typo "
     "does not half-apply")
def t_bad_input_refused():
    fresh()
    with store.conn() as (cx, cur):
        before = icon_auth.get_screen_perms(cur, "op1")
        for perms, want in (
            ({"chalan": {"view": True, "write": True}}, "Unknown screen: chalan."),
            ({"admin": {"view": True, "write": True}}, "Unknown screen: admin."),
            ({"gp": {"view": False, "write": True}}, "gp: write access without view access."),
            ({"gp": True}, "Access for gp must say view and write."),
            ({"gp": {"view": False, "write": False},
              "typo": {"view": True, "write": True}}, "Unknown screen: typo."),
        ):
            try:
                icon_auth.set_screen_perms(cur, "admin1", "op1", perms)
                assert False, "accepted %r" % perms
            except icon_auth.AuthError as e:
                assert str(e) == want, (perms, str(e))
        assert icon_auth.get_screen_perms(cur, "op1") == before, \
            "a refused call still changed something"


@test("a partial map changes only the screens it names - sending one "
     "screen cannot wipe the other nineteen")
def t_partial_map_is_a_merge():
    fresh()
    with store.conn() as (cx, cur):
        before = icon_auth.get_screen_perms(cur, "op1")
        icon_auth.set_screen_perms(cur, "admin1", "op1",
                                   {"invoice": {"view": False, "write": False}})
        after = icon_auth.get_screen_perms(cur, "op1")
    changed = {s for s in icon_auth.SCREEN_IDS if before[s] != after[s]}
    assert changed == {"invoice"}, changed


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
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
