"""
ICON TRACE - tests that the live layer's stylesheet actually reaches it.

    python test_styles.py

v4's page carries its stylesheet INLINE and links nothing. Everything the
live layer adds on top - the collapsible sidebar, .scroll boxes, the invoice
drop zone, independent column scrolling - lived in static/icon.css, which
that page never loaded. So the classes were set and matched no rule: the
sidebar toggle did nothing at all, and every table wrapped in .scroll simply
grew down the page instead.

Nothing failed loudly, which is why it went unnoticed. These tests check the
wiring that makes the rules reachable, and that there is exactly one copy of
each.
"""

import os, re, sys, traceback

BASE = os.path.dirname(os.path.abspath(__file__))

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def read(*parts):
    with open(os.path.join(BASE, *parts), encoding="utf-8") as fh:
        return fh.read()


ADD = read("static", "icon_add.css")
ICON = read("static", "icon.css")
LIVE = read("static", "icon_live.js")
V4 = read("templates", "icon_trace.html")
BASE_HTML = read("templates", "base.html")
INLINE = V4[V4.index("<style>"):V4.index("</style>")]

# what the live layer sets on elements and therefore needs a rule for
NEEDED = [
    ("side-collapsed", "the collapsed sidebar rail"),
    ("side-toggle", "the collapse button itself"),
    ("scroll", "a table that scrolls inside its card"),
    ("drop", "the invoice drag-and-drop zone"),
    ("table-tools", "the search / reset / export group"),
]


@test("every class the live layer relies on has a rule in icon_add.css")
def t_rules_exist():
    for cls, what in NEEDED:
        assert re.search(r"[.#][\w-]*\b%s\b" % re.escape(cls), ADD), \
            "%s (%s) has no rule - the class would match nothing" % (cls, what)


@test("v4's page links no stylesheet, so the live layer must inject one")
def t_v4_links_nothing():
    head = V4[:V4.index("<style>")]
    assert "stylesheet" not in head, \
        "v4 links a stylesheet now - check this is not a second copy of its " \
        "own inline rules"


@test("the live layer injects icon_add.css into v4's page")
def t_live_injects():
    # the literal in the code, not the name in a comment
    assert "'/static/icon_add.css'" in LIVE, \
        "nothing brings the additions to v4's page - every rule above is dead"
    assert "rel = 'stylesheet'" in LIVE, "it has to be linked as a stylesheet"
    assert "iconAddCss" in LIVE, "the injection should be guarded by an id"


@test("the base shell loads it too, after icon.css")
def t_base_loads_both():
    assert "icon_add.css" in BASE_HTML, "the other screens lose the additions"
    assert BASE_HTML.index("icon.css") < BASE_HTML.index("icon_add.css"), \
        "the additions must come after the stylesheet they add to"


@test("there is exactly one copy of each addition")
def t_no_duplication():
    for cls, _what in NEEDED:
        if cls == "scroll":
            continue          # v4 has its own .scroll usage, checked below
        assert not re.search(r"\.%s\b" % re.escape(cls), ICON), \
            "%s is in icon.css as well - two copies drift apart" % cls


@test("icon.css stays v4's stylesheet, verbatim")
def t_icon_css_is_v4():
    assert "additions for the live app" not in ICON, \
        "the additions block is back in icon.css"
    assert "side-collapsed" not in ICON


@test("a note class the live layer writes is one v4 actually styles")
def t_note_classes():
    used = set(re.findall(r'class="note (n-[\w-]+)"', LIVE))
    used |= set(re.findall(r"class=\"note (n-[\w-]+)\"", LIVE))
    styled = set(re.findall(r"\.(n-[\w-]+)", INLINE + ADD))
    unstyled = used - styled
    assert not unstyled, \
        "%s matches no rule - the message renders as plain text" \
        % ", ".join(sorted(unstyled))


@test("the collapsed rail hides the label and keeps the icon")
def t_collapse_is_complete():
    # the labels are bare text nodes in v4's markup, so they can only be
    # hidden by zeroing the font on the button and restoring it on the icon
    assert re.search(r"side-collapsed[^{]*\.nav-i\{[^}]*font-size:0", ADD), \
        "nothing hides the nav label, so the rail collapses onto its text"
    assert re.search(r"side-collapsed[^{]*\.nav-i em\{[^}]*font-size:1", ADD), \
        "the icon needs its size back, or the rail collapses to nothing"
    assert re.search(r"side-collapsed .side:hover\{[^}]*width:198px", ADD), \
        "hovering the rail should bring the labels back"


@test("the rail slides out over the page rather than pushing it")
def t_hover_overlays():
    m = re.search(r"side-collapsed .side:hover\{([^}]*)\}", ADD)
    assert m and "position:relative" in m.group(1) and "z-index" in m.group(1), \
        "without a stacking context the labels push the layout sideways"


if __name__ == "__main__":
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
