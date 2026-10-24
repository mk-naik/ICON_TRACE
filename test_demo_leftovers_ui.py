"""
ICON TRACE - v4's words about things this system does not have are gone.

    python test_demo_leftovers_ui.py      (needs Playwright + Chromium)

v4 was a design prototype, and some of its explanatory text describes the
prototype rather than ICON TRACE: features that were never built, figures
that were nobody's data. Found by the overnight audit (24 Oct 2026), which
searched every screen for v4's sample values and text.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


@test("Management Overview's Needs a decision card says what it does - not v4's "
      "aging alert, challan approvals and 'one real box waited 67 days'")
def t_mgmt_footer():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = H.open_page(b, "mgmt", wait_ms=2000)
        foot = pg.evaluate("() => document.getElementById('mgBlocked').closest('.card')"
                           ".querySelector('.card-f').innerText")
        for gone in ("67 days", "aging alert", "challan approval"):
            assert gone not in foot, foot
        assert "Open goes to the screen where it is decided" in foot, foot
        assert pg.errors == [], pg.errors


@test("Admin > Stations & sources counts each station's real accounts - not v4's "
      "sample staff - lists a station an account names that the list lacks, and "
      "no longer claims a station_config table the server reads")
def t_station_accounts():
    store.wipe(); AUTH.ensure_auth_schema()
    for login, role, station in (("op.a1", "FQC Operator", "FQC-01"),
                                 ("op.a2", "FQC Operator", "FQC-01"),
                                 ("op.p2", "Packing Operator", "PACK-02"),
                                 ("op.x", "FQC Operator", "FQC-03")):
        AUTH.make_user(role, login_id=login, station=station)
    with H.browser() as b:
        pg = H.open_page(b, "admin", wait_ms=1500)
        pg.click('#adTabs button[onclick*="\'stations\'"]')
        pg.wait_for_function("() => !/…/.test(document.getElementById('stationRows').innerText)",
                             timeout=8000)
        rows = pg.eval_on_selector_all("#stationRows tr", "rs => rs.map(r => "
                                       "[r.cells[0].innerText.trim(), r.cells[r.cells.length - 2].innerText.trim()])")
        got = dict(rows)
        assert got.get("FQC-01") == "2" and got.get("PACK-02") == "1", rows
        assert got.get("FQC-02") == "0" and got.get("FQC-03") == "1", rows
        note = pg.inner_text("#ad-stations > .note")
        assert "when the server starts" not in note and "nothing reads it" in note, note
        assert pg.errors == [], pg.errors


@test("a first visit is not told its session timed out; the station chip does not "
      "name a station_config table")
def t_first_visit_and_chip():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = b.new_page()
        pg.goto(H.base_url() + "/")
        pg.wait_for_selector("#liLoginId", timeout=15000)
        pg.wait_for_timeout(2500)
        msg = pg.inner_text("#liMsg") if pg.query_selector("#liMsg") else ""
        assert "timed out" not in msg, msg
        pg.close()
        pg = H.open_page(b, None, role="Packing Operator", login_id="pk.chip")
        title = pg.evaluate("document.getElementById('tbStation').title")
        assert "station_config" not in title and "written on your account" in title, title
        assert pg.errors == [], pg.errors


@test("a button that only opens another screen is disabled, with why, for an account "
      "that cannot open that screen - also one drawn after the page loaded")
def t_go_buttons_follow_access():
    store.wipe(); AUTH.ensure_auth_schema()
    NEW_ENTRY = "#v-dash button[onclick^=\"go('fqc'\"]"
    with H.browser() as b:
        pk = H.open_page(b, "dash", wait_ms=1200, role="Packing Operator", login_id="pk.go")
        assert pk.is_disabled(NEW_ENTRY), "a Packing Operator is offered FQC Entry"
        assert pk.get_attribute(NEW_ENTRY, "title") == "Not one of your screens"
        # drawn later, the way a detail panel or a list row is
        pk.evaluate("() => document.getElementById('v-dash').insertAdjacentHTML('beforeend', "
                    "'<button id=\"lateGo\" onclick=\"go(\\'review\\')\">Open</button>')")
        pk.wait_for_timeout(300)
        assert pk.is_disabled("#lateGo"), "a row drawn later still offers a screen it cannot open"
        assert pk.errors == [], pk.errors
        sa = H.open_page(b, "dash", wait_ms=1200, role="Super Admin", login_id="sa.go")
        assert sa.is_enabled(NEW_ENTRY), "Super Admin lost FQC Entry's button"
        pi = H.open_page(b, "mgmt", wait_ms=1500, role="Production Incharge", login_id="pi.go")
        disp = "#v-mgmt button[onclick^=\"go('disp'\"]"
        assert pi.is_disabled(disp), "a Production Incharge is offered Stock & Dispatch"
        assert pi.errors == [] and sa.errors == [], (pi.errors, sa.errors)


@test("before a screen's data arrives, its filter lists hold only 'All' - not v4's "
      "sample wattages (625W ... 590W) and models")
def t_filter_lists_before_data():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = b.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        # the answers that refill these lists never come
        for pat in ("**/api/prod/dashboard*", "**/api/fqc/dashboard*", "**/api/stock_dispatch*"):
            pg.route(pat, lambda route: route.abort())
        sid = AUTH.make_session_id(role="Super Admin", login_id="sa.lists")
        pg.context.add_cookies([{"name": "icon_sid", "value": sid,
                                 "domain": "127.0.0.1", "path": "/"}])
        pg.goto(H.base_url() + "/")
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(1500)
        opts = lambda i: pg.evaluate("(i) => Array.from(document.getElementById(i).options)"
                                     ".map(o => o.text)", i)
        assert opts("mgWatt") == ["All"], opts("mgWatt")
        assert opts("dpModel") == ["All"], opts("dpModel")
        for sel in ("mgCust", "dpCust", "fDashCust"):
            assert not set(opts(sel)) & {"SAI BABUJI PROJECTS", "SG MEDA", "MSEDCL"}, opts(sel)


@test("Stock & Dispatch counts in words that agree - '1 box ready', not '1 boxes ready'")
def t_stock_words():
    import test_challan as T                 # real pallets: FQC'd modules, a closed box
    c = T.setup()
    T.packed_box(c, [500, 501])
    with H.browser() as b:
        pg = H.open_page(b, "disp", wait_ms=2000)
        pg.wait_for_function("() => /ready/.test(document.querySelector('#v-disp .kpi .d').innerText)",
                             timeout=8000)
        assert pg.inner_text("#v-disp .kpi .d").strip() == "1 box ready", \
            pg.inner_text("#v-disp .kpi .d")
        labels = pg.eval_on_selector_all("#v-disp .kpi .d", "ds => ds.map(d => d.innerText)")
        assert not [l for l in labels if "(es)" in l or "(s)" in l or "1 boxes" in l], labels
        assert pg.errors == [], pg.errors


@test("Create Challan's Outputs card says when a challan prints - not 'Save as draft or "
      "Create first' under a draft that prints nothing - and its footer no station")
def t_challan_outputs_card():
    import test_challan as T
    c = T.setup()
    box = T.packed_box(c, [520, 521])
    inv = T.make_invoice(qty=2, invoice_no="INV-OUT-1")
    with H.browser() as b:
        pg = H.open_page(b, role="Super Admin", login_id="sa.out", wait_ms=1200)
        pg.evaluate("go('challan')"); pg.wait_for_timeout(1200)
        card = pg.evaluate("() => document.getElementById('chDocRows').closest('.card').innerText")
        assert "from which station" not in card, card
        assert "loaded" in pg.inner_text("#chDocRows"), pg.inner_text("#chDocRows")
        assert "Save as draft or Create first" not in card, card
        pg.select_option("#chInvoiceSel", str(inv)); pg.wait_for_timeout(1200)
        pg.evaluate("(id) => chToggleBox(id, true)", box); pg.wait_for_timeout(1200)
        pg.click("#chDraftBtn"); pg.wait_for_timeout(1800)
        rows = pg.inner_text("#chDocRows")
        assert "A draft has its number but is not printed" in rows, rows
        assert pg.errors == [], pg.errors


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
