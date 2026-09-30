"""
ICON TRACE - Round 29: the boot payload stops being public.

    python test_boot_payload.py

Until this round GET / - which is also the sign-in page - embedded every
indent with its customer and delivery date, the BOM, cell efficiencies,
open pallets and customers with GSTIN, for anybody who asked, and
/api/boot returned the same with no gate at all.

The data is seeded with markers that exist nowhere in the page's own
markup (asserted), so "not in the page" means the server did not send it.
What is checked is what reaches the browser - the response body and the
page Chromium actually holds - not boot_public()'s return value.

Then the page itself, fetching the payload at sign-in inside enterApp():
a fresh sign-in and a reload of a signed-in page are tested SEPARATELY,
because a fetch placed in the /login handler would pass the first and
leave the second with an empty B. The screen asserted is Planning's
indent list: applyBoot() builds it (and v4's INDENTS) from B.indents and
from nothing else - the Indent screen itself would not do, it loads its
own list from /api/indents.
"""

import json, os, re, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_boot_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import icon_customers                                        # noqa: E402
import icon_models                                           # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


BASE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = open(os.path.join(BASE, "templates", "icon_trace.html"), encoding="utf-8").read()

INDENT_NO = "R29-SECRET/2026"
DELIVERY = "2026-11-27"
MATERIAL = "R29 Secret Backsheet"
CELL_EFF = "27.9%"
# Only the GSTINs v4's own markup does not already carry - some of its demo
# rows use real customers' GSTINs, and those prove nothing either way.
GSTINS = [c["gstin"] for c in icon_customers.all_customers()
          if c.get("gstin") and c["gstin"] not in TEMPLATE]
MARKERS = [INDENT_NO, DELIVERY, MATERIAL, CELL_EFF] + GSTINS

# boot_payload() at d9574c2, key for key - read off its return statement.
# A field that goes missing from /api/boot fails here by name.
TOP_KEYS = {"live", "build", "db_file", "indents", "challan_seq", "prod",
            "shifts", "range", "customers", "open_boxes", "models", "items",
            "materials", "mat_cats", "cell_eff", "config", "counts",
            # Round 30: the change sequence this payload is current as of.
            # Added deliberately - the page uses it as the mark the change
            # feed counts from, so it belongs with the data, not beside it.
            "change_seq"}
NESTED = {"challan_seq": {"fy", "next"}, "config": {"pallet_ceiling"},
          "counts": {"serials", "invoices", "challans", "boxes", "indents",
                    "needs_review", "drafts"},
          "range": {"from", "to"}}
ROW_KEYS = {
    "indents": {"indent_no", "customer", "build_type", "delivery_by", "lines"},
    "customers": {"code", "name", "gstin", "state", "stock"},
    "open_boxes": {"box_id", "seq", "pack_date", "model", "grade", "qty",
                   "capacity", "customer"},
    "models": {"watt", "tc", "model", "series", "cells", "ct", "size",
               "produced", "lh"},
    "items": {"item_code", "model", "cell_type", "wattage"},
}
PUBLIC_KEYS = {"build", "live", "db_file"}

PI_LOGIN, PI_PW = "pi.boot", "CorrectHorse99"
TEMP_LOGIN, TEMP_PW, NEW_PW = "temp.boot", "TempHorse55", "OwnHorse7788"


def world():
    store.wipe()
    AUTH.ensure_auth_schema()
    key = os.path.join(os.path.dirname(store.DB_PATH), ".icon_totp_key")
    if not os.path.exists(key):
        icon_auth.create_key()
    icon_auth.COOLDOWN_STEPS = ()
    sa = APP.app.test_client()
    AUTH.test_login(sa)
    item = icon_models.all_items()[0]["item_code"]
    r = sa.post("/api/indent", json={"indent_no": INDENT_NO, "indent_date": "2026-09-09",
                                     "customer": "ADITYA GREEN ENERGY PVT LTD",
                                     "delivery_by": DELIVERY,
                                     "items": [{"item_code": item, "qty": 120}]})
    assert r.status_code == 200, r.get_json()
    r = sa.post("/api/material", json={"name": MATERIAL, "uom": "Nos"})
    assert r.status_code == 200, r.get_json()
    r = sa.put("/api/cell-efficiencies", json={"values": ["25.1%", CELL_EFF]})
    assert r.status_code == 200, r.get_json()
    model = icon_models.all_models()[0]["model"]
    r = sa.post("/api/box/open", json={"grade": "A", "model": model, "capacity": 2})
    assert r.status_code == 200, r.get_json()
    with store.conn() as (cx, cur):
        for login, pw, must in ((PI_LOGIN, PI_PW, 0), (TEMP_LOGIN, TEMP_PW, 1)):
            cur.execute("INSERT INTO app_user (login_id, display_name, role, station, "
                        "pw_hash, must_change_pw, created_at, created_by) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (login, "Boot " + login, "Production Incharge", "FQC-01",
                         icon_auth.hash_pw(pw), must, 1000000, "test"))
            icon_auth.set_screen_perms(cur, "cli", login,
                                       icon_auth.default_perms_for_role("Production Incharge"))
    return sa


def embedded_boot(html):
    m = re.search(r"window\.ICON_BOOT = (\{.*?\});</script>", html, re.S)
    assert m, "no ICON_BOOT in the page"
    return json.loads(m.group(1))


# --------------------------------------------------------------------------
# the server
# --------------------------------------------------------------------------

@test("GET / signed out carries no indent, customer, GSTIN, BOM or cell-"
     "efficiency data - in the response body, and in the page Chromium holds "
     "- while the same markers ARE in /api/boot for a session")
def t_public_page_carries_no_data():
    sa = world()
    for m in MARKERS:
        assert m not in TEMPLATE, "marker %r is in the page's own markup" % m
    private = json.dumps(sa.get("/api/boot").get_json())
    for m in MARKERS:
        assert m in private, "marker %r never reached the payload - test proves nothing" % m

    anon = APP.app.test_client()
    body = anon.get("/").get_data(as_text=True)
    leaked = [m for m in MARKERS if m in body]
    assert not leaked, "signed-out page carries: %s" % leaked
    boot = embedded_boot(body)
    assert set(boot) == PUBLIC_KEYS, boot

    with H.browser() as b:
        pg = b.new_page()
        pg.goto(H.base_url() + "/")
        pg.wait_for_selector("#liLoginId", timeout=15000)
        pg.wait_for_timeout(1500)
        seen = pg.evaluate("document.documentElement.outerHTML + "
                           "document.body.innerText + JSON.stringify(window.ICON_BOOT)")
        leaked = [m for m in MARKERS if m in seen]
        assert not leaked, "the browser holds: %s" % leaked
        print("      ICON_BOOT in the browser: %s" % pg.evaluate("JSON.stringify(window.ICON_BOOT)"))
    print("      %d markers (%d GSTINs) - in /api/boot, absent from GET /" % (
        len(MARKERS), len(GSTINS)))


@test("GET /api/boot: 401 with no session; with one, the full payload, key "
     "for key the shape of d9574c2's boot_payload() - top level, nested "
     "objects and each row")
def t_api_boot():
    sa = world()
    anon = APP.app.test_client()
    r = anon.get("/api/boot")
    assert r.status_code == 401 and r.get_json() == {"ok": False, "why": "Sign in required."}, \
        (r.status_code, r.get_json())
    d = sa.get("/api/boot").get_json()
    assert set(d) == TOP_KEYS, "missing %s, extra %s" % (TOP_KEYS - set(d), set(d) - TOP_KEYS)
    for k, want in NESTED.items():
        assert set(d[k]) == want, (k, set(d[k]))
    for k, want in ROW_KEYS.items():
        assert d[k], "%s is empty - cannot check its rows" % k
        assert set(d[k][0]) == want, (k, set(d[k][0]))
    assert isinstance(d["prod"], list) and isinstance(d["shifts"], list)
    assert isinstance(d["materials"], list) and isinstance(d["cell_eff"], list)
    # any role with a session - a session is the bar, not a screen
    op = APP.app.test_client()
    AUTH.test_login(op, role="Quality")
    assert set(op.get("/api/boot").get_json()) == TOP_KEYS
    print("      401 signed out; %d keys signed in" % len(d))


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------

def _page(b):
    pg = b.new_page(viewport={"width": 1500, "height": 950})
    pg.errors, pg.calls = [], []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("requestfinished", lambda r: pg.calls.append(
        "%s %s" % (r.method, r.url.split("/", 3)[-1].split("?")[0])))
    return pg


def _sign_in(pg, login, pw):
    pg.goto(H.base_url() + "/")
    pg.wait_for_selector("#liLoginId", timeout=15000)
    pg.fill("#liLoginId", login)
    pg.fill("#liCredential", pw)
    pg.click("#liSubmit")


def _planning_shows_indent(pg):
    assert pg.evaluate("Object.keys(INDENTS)") == [INDENT_NO], pg.evaluate("Object.keys(INDENTS)")
    pg.evaluate("go('plan')")
    pg.wait_for_timeout(600)
    opts = pg.evaluate("Array.prototype.map.call(document.querySelectorAll('#pIndent option'),"
                       " function (o) { return o.value; })")
    assert INDENT_NO in opts, opts
    return opts


def _order(calls, first, then):
    assert first in calls and then in calls, calls
    assert calls.index(first) < calls.index(then), calls


@test("(a) a FRESH sign-in: /api/boot is fetched after /login, and Planning's "
     "indent list - built only from the payload - shows the indent")
def t_fresh_sign_in():
    world()
    with H.browser() as b:
        pg = _page(b)
        _sign_in(pg, PI_LOGIN, PI_PW)
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(1200)
        _order(pg.calls, "POST login", "GET api/boot")
        assert pg.calls.count("GET api/boot") == 1, pg.calls
        opts = _planning_shows_indent(pg)
        assert pg.errors == [], pg.errors
        print("      calls: %s" % [c for c in pg.calls if c.split(" ", 1)[1] in ("login", "api/boot", "api/session")])
        print("      #pIndent options: %s" % opts)


@test("(b) a signed-in page RELOADED: the reload path fetches /api/boot too "
     "(after /api/session), and Planning's indent list shows the indent")
def t_reload():
    world()
    with H.browser() as b:
        pg = _page(b)
        _sign_in(pg, PI_LOGIN, PI_PW)
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(800)
        pg.calls.clear()
        pg.reload()
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(1200)
        assert "POST login" not in pg.calls, pg.calls
        _order(pg.calls, "GET api/session", "GET api/boot")
        # the page AS SERVED on reload still embeds the public payload only
        # (window.ICON_BOOT is B's object, so after the fetch it rightly
        # holds the data in memory - the served script tag is what matters)
        assert set(embedded_boot(pg.content())) == PUBLIC_KEYS
        opts = _planning_shows_indent(pg)
        assert pg.errors == [], pg.errors
        print("      calls: %s" % [c for c in pg.calls if c.split(" ", 1)[1] in ("login", "api/boot", "api/session")])
        print("      #pIndent options: %s" % opts)


@test("a temporary-password account goes to change-password and /api/boot is "
     "NOT fetched - on sign-in or on reload - until the new password is set")
def t_temp_password_no_boot():
    world()
    with H.browser() as b:
        pg = _page(b)
        _sign_in(pg, TEMP_LOGIN, TEMP_PW)
        pg.wait_for_selector("#cpCurrent", timeout=15000)
        pg.wait_for_timeout(1200)
        assert "GET api/boot" not in pg.calls, pg.calls
        assert not pg.evaluate("document.getElementById('app').classList.contains('on')")
        pg.reload()
        pg.wait_for_selector("#cpCurrent", timeout=15000)
        pg.wait_for_timeout(1200)
        assert "GET api/boot" not in pg.calls, pg.calls
        pg.fill("#cpCurrent", TEMP_PW)
        pg.fill("#cpNew", NEW_PW)
        pg.fill("#cpAgain", NEW_PW)
        pg.click("#cpSubmit")
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(1200)
        _order(pg.calls, "POST api/session/change-password", "GET api/boot")
        _planning_shows_indent(pg)
        assert pg.errors == [], pg.errors
        print("      no boot before; after: %s" % [c for c in pg.calls if "boot" in c or "change-password" in c])


@test("if the payload cannot be fetched the app is NOT entered half-built - "
     "back to the sign-in card with the reason")
def t_boot_failure():
    world()
    with H.browser() as b:
        pg = _page(b)
        pg.route("**/api/boot", lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"ok": false}'))
        _sign_in(pg, PI_LOGIN, PI_PW)
        pg.wait_for_timeout(4500)          # the splash's minimum, and then some
        assert not pg.evaluate("document.getElementById('app').classList.contains('on')")
        assert pg.is_visible("#liLoginId")
        msg = pg.inner_text("#login")
        assert "could not be loaded" in msg, msg
        print("      shown: %r" % [l for l in msg.splitlines() if "loaded" in l][0])


# --------------------------------------------------------------------------
# the two sidebar badges that were v4's own frozen demo numbers forever -
# "Needs review 5", "Drafts 4" - for every account, however real data changed
# --------------------------------------------------------------------------

@test("/api/nav_badges: 401 with no session; with one, the real, live counts "
      "- not v4's frozen 5 and 4")
def t_nav_badges_endpoint():
    world()
    anon = APP.app.test_client()
    assert anon.get("/api/nav_badges").status_code == 401
    sa = APP.app.test_client()
    AUTH.test_login(sa)
    d = sa.get("/api/nav_badges").get_json()
    assert d == {"needs_review": 0, "drafts": 0}, d

    with store.conn() as (cx, cur):
        import db
        db.ingest_review_item(cur, "not_in_master_unplanned",
                              "ICON625R1292130999", "raw-badge-test", "test")
        cur.execute("INSERT INTO challan (fy, seq, challan_date, status, "
                    "model, wattage, qty, origin, created_at, created_by) "
                    "VALUES (%s,%s,%s,'draft',%s,%s,%s,'system',%s,%s)",
                    ("26-27", 9001, "2026-09-09", "ISEN625-G12R", 625, 1,
                     "2026-09-09T10:00:00", "test"))
    d = sa.get("/api/nav_badges").get_json()
    assert d == {"needs_review": 1, "drafts": 1}, d
    # /api/boot's own counts agree - the first paint after sign-in is
    # already right, with no extra round trip for it
    boot_counts = sa.get("/api/boot").get_json()["counts"]
    assert boot_counts["needs_review"] == 1 and boot_counts["drafts"] == 1, boot_counts


@test("the sidebar shows the real counts, not v4's frozen markup - Needs "
      "review has no id at all in that markup to hang a live number on, so "
      "this is also proof the live layer finds it a different way")
def t_nav_badges_on_screen():
    world()
    with store.conn() as (cx, cur):
        import db
        db.ingest_review_item(cur, "not_in_master_unplanned",
                              "ICON625R1292130998", "raw-badge-ui", "test")
        cur.execute("INSERT INTO challan (fy, seq, challan_date, status, "
                    "model, wattage, qty, origin, created_at, created_by) "
                    "VALUES (%s,%s,%s,'draft',%s,%s,%s,'system',%s,%s)",
                    ("26-27", 9002, "2026-09-09", "ISEN625-G12R", 625, 1,
                     "2026-09-09T10:00:00", "test"))
    with H.browser() as b:
        pg = _page(b)
        _sign_in(pg, PI_LOGIN, PI_PW)
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(600)
        review_badge = pg.eval_on_selector('.nav-i[data-v="review"] b', "e => e.textContent")
        draft_badge = pg.eval_on_selector('#draftBadge', "e => e.textContent")
        assert review_badge == "1", "still v4's frozen number: %r" % review_badge
        assert draft_badge == "1", "still v4's frozen number: %r" % draft_badge


# --------------------------------------------------------------------------
# Planning's Indent No. select keeps its own selection
# --------------------------------------------------------------------------

@test("iconRefresh() (fired after a submit) rebuilds the Indent No. select "
      "without losing what was chosen - it used to always revert to '-- "
      "select --' while Indent Item and everything derived from it (Customer, "
      "Ordered, Already allocated...) stayed exactly as they were, so the two "
      "halves of the same screen disagreed about which indent this was")
def t_indent_select_survives_refresh():
    world()
    with H.browser() as b:
        pg = _page(b)
        _sign_in(pg, PI_LOGIN, PI_PW)
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.evaluate("go('plan')")
        pg.wait_for_timeout(400)
        pg.click("#newPlanBtn")          # the plan form starts collapsed
        pg.wait_for_selector("#pIndent", state="visible", timeout=5000)
        pg.select_option("#pIndent", INDENT_NO)
        assert pg.eval_on_selector("#pIndent", "e => e.value") == INDENT_NO
        pg.evaluate("iconRefresh()")
        pg.wait_for_timeout(600)
        assert pg.eval_on_selector("#pIndent", "e => e.value") == INDENT_NO, \
            "the selection reverted to blank after a refresh"
        # a SECOND indent that gets cancelled between the choice and the
        # refresh genuinely is no longer valid - blank is correct THERE
        r = pg.request.post(H.base_url() + "/api/indent", data=json.dumps({
            "indent_no": "R29-GONE/2026", "indent_date": "2026-09-09",
            "customer": "ADITYA GREEN ENERGY PVT LTD", "delivery_by": DELIVERY,
            "items": [{"item_code": icon_models.all_items()[0]["item_code"], "qty": 5}]}),
            headers={"Content-Type": "application/json"})
        assert r.ok, r.text()
        pg.evaluate("iconRefresh()"); pg.wait_for_timeout(400)
        pg.select_option("#pIndent", "R29-GONE/2026")
        with store.conn() as (cx, cur):
            cur.execute("UPDATE indent SET status='cancelled' WHERE indent_no=%s",
                       ("R29-GONE/2026",))
        pg.evaluate("iconRefresh()")
        pg.wait_for_timeout(600)
        assert pg.eval_on_selector("#pIndent", "e => e.value") == "", \
            "an indent that is genuinely gone must not stay selected"


# --------------------------------------------------------------------------

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
                traceback.print_exc()
                failed += 1
    finally:
        H.cleanup()
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
