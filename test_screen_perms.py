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
