"""
ICON TRACE - Round 28 acceptance: the case that drove per-user permissions.

    python test_dashrath_case.py

Three people share "Dispatch Operator" and need different screens. This
proves the MECHANISM with one of them - not the real person's final
permissions, which Mukesh sets in the editor afterwards:

    view  - the five Dispatch screens (Stock & Dispatch, Tax Invoice,
            Challan, Loading Verification, Gate Pass) and Management
            Overview. Nothing else.
    write - Stock & Dispatch and Gate Pass only.

So: Challan and Invoice open and show real data, and refuse a save;
Stock & Dispatch and Gate Pass save; New Pallet and Repack (the whole
Packing section), Production and FQC are unreachable; the overview
landing page shows. Asserted on the server, then on the running page.
"""

import csv, datetime, os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_dashrath_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


DISPATCH = ("disp", "invoice", "challan", "loadver", "gp")
VIEW = set(DISPATCH) | {"mgmt"}
WRITE = {"disp", "gp"}
LOGIN = "dashrath"
_GATE_403 = "Not permitted for your role."
RO_REASON = "Your account can view this screen but not save changes."

WATT, MODEL = 625, "ISEN625-G12R"
SS = os.path.join(TMP, "ss.csv")
EL_OK = os.path.join(TMP, "el", "OK")
os.makedirs(EL_OK, exist_ok=True)


def serial(i):
    return "ICON625R129071%04d" % i


def gate_refused(r):
    return r.status_code == 403 and \
        (r.get_json(silent=True) or {}).get("why") == _GATE_403


def past_gate(r):
    return r.status_code != 401 and not gate_refused(r)


def world():
    """A real invoice and a real, submitted challan (so Challan and Invoice
    have something to show), and the Dashrath-shaped account."""
    store.wipe()
    AUTH.ensure_auth_schema()
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(
            [["2026-09-09 10:%02d:00" % i, serial(i), "630.5", "12.1", "48.9",
              "11.8", "52.5", "96.1", "0.41", "0.4", "210.0", "23.1", "25",
              "25", "1000"] for i in range(2)])
    for i in range(2):
        open(os.path.join(EL_OK, serial(i) + ".jpg"), "w").close()
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS, "el_root": os.path.dirname(EL_OK),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_a_root": "", "el_b_root": ""})
        for i in range(2):
            store.insert(cur, "serial", {
                "serial": serial(i), "build_instance": 1, "model": MODEL,
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned"})
    sa = APP.app.test_client()
    AUTH.test_login(sa)
    assert sa.post("/api/fqc", json={"serial": serial(0), "outcome": "pass"}).status_code == 200
    b = sa.post("/api/box/open", json={"grade": "A", "model": MODEL, "capacity": 1}).get_json()
    assert sa.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)}).status_code == 200
    assert sa.post("/api/box/%d/close" % b["box_id"], json={}).status_code == 200
    with store.conn() as (cx, cur):
        inv = db.insert_invoice(cur, {
            "buyer_name": "Agni Solar", "buyer_gstin": "22AAAAA0000A1Z5",
            "declared_qty": 1, "declared_model": MODEL, "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                               datetime.timedelta(days=10)).isoformat(),
            "invoice_no": "INV-DASHRATH-1", "irn": None,
            "consignee_same_as_buyer": 1}, "t.pdf", "feedda",
            {"fields": {}, "compare_only": {}, "qr": {}}, False, {}, "tester")
    r = sa.post("/api/challan", json={"action": "draft", "boxes": [b["box_id"]],
                                      "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    ch = r.get_json()["challan_id"]
    assert sa.post("/api/challan/%d/submit" % ch, json={}).status_code == 200

    AUTH.make_user("Dispatch Operator", login_id=LOGIN, name="Dashrath Pal")
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, "cli", LOGIN, {
            s: {"view": s in VIEW, "write": s in WRITE} for s in icon_auth.SCREEN_IDS})
    return {"invoice_id": inv, "challan_id": ch, "box_id": b["box_id"]}


def dashrath():
    c = APP.app.test_client()
    AUTH.test_login(c, role="Dispatch Operator", login_id=LOGIN)
    return c


# --------------------------------------------------------------------------
# on the server
# --------------------------------------------------------------------------

@test("Challan and Invoice open and show real data - the invoice, the "
     "challan and its detail all read back")
def t_reads_challan_and_invoice():
    w = world()
    c = dashrath()
    invs = c.get("/api/invoices").get_json()["invoices"]
    assert any(i.get("invoice_no") == "INV-DASHRATH-1" for i in invs), invs
    assert c.get("/api/invoice/%d" % w["invoice_id"]).status_code == 200
    chs = c.get("/api/challans").get_json()
    rows = chs.get("challans", chs) if isinstance(chs, dict) else chs
    assert any(x.get("challan_id") == w["challan_id"] for x in rows), chs
    assert c.get("/api/challan/%d" % w["challan_id"]).status_code == 200
    assert c.get("/api/loading/challans").status_code == 200
    print("      invoice INV-DASHRATH-1 and challan #%d read back" % w["challan_id"])


@test("...and refuse every save: creating or submitting a challan, confirming "
     "or parsing an invoice, confirming a pallet at loading - 403")
def t_cannot_save_challan_or_invoice():
    w = world()
    c = dashrath()
    for method, path, body in (
            ("post", "/api/challan", {"action": "draft", "boxes": [w["box_id"]],
                                       "invoice_id": w["invoice_id"]}),
            ("post", "/api/challan/%d/submit" % w["challan_id"], {}),
            ("post", "/api/challan/%d/discard" % w["challan_id"], {"reason": "x"}),
            ("post", "/api/invoice/confirm", {}),
            ("post", "/api/invoice/parse", {}),
            ("post", "/api/loading/%d/confirm" % w["challan_id"], {})):
        r = getattr(c, method)(path, json=body)
        assert gate_refused(r), (path, r.status_code, r.get_json(silent=True))
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM challan")["n"]
    assert n == 1, "a refused save still created a challan"


@test("Stock & Dispatch and Gate Pass save: both pass their write gates")
def t_can_save_disp_and_gp():
    world()
    c = dashrath()
    r = c.post("/api/gatepass", json={})
    assert past_gate(r), (r.status_code, r.get_json(silent=True))
    r = c.post("/dispatch", data={})
    assert past_gate(r), r.status_code
    assert c.get("/api/gatepasses").status_code == 200
    assert c.get("/api/stock_dispatch").status_code == 200


@test("New Pallet and Repack are unreachable - every read and every write of "
     "both is refused - and so are Production and FQC")
def t_packing_production_fqc_unreachable():
    w = world()
    c = dashrath()
    for path in ("/api/boxes", "/api/box/check?serial=X", "/api/box/%d" % w["box_id"],
                 "/api/packing/log", "/api/indents", "/api/allocations",
                 "/api/prodentries", "/api/loss_events", "/api/fqc/recent",
                 "/api/fqc/lookup?serial=X", "/api/hold", "/api/review",
                 "/api/trace/find?q=X"):
        assert gate_refused(c.get(path)), path
    for path in ("/api/box/open", "/api/repack", "/api/box/%d/repack" % w["box_id"],
                 "/api/fqc", "/api/prodentry", "/api/indent"):
        assert gate_refused(c.post(path, json={})), path


@test("the overview landing page shows: Management Overview and the three "
     "dashboards it reads all answer")
def t_overview_readable():
    world()
    c = dashrath()
    for path in ("/mgmt", "/api/prod/dashboard", "/api/fqc/dashboard",
                 "/api/stock_dispatch", "/api/prod"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code)


# --------------------------------------------------------------------------
# on the running page
# --------------------------------------------------------------------------

@test("on the page: exactly six screens in the nav, home is Stock & Dispatch, "
     "New Pallet and Repack refused with v4's own message, Challan and Invoice "
     "show data with every save control disabled and the reason given, Stock & "
     "Dispatch and Gate Pass live - and not one refused request or page error")
def t_on_the_page():
    world()
    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "round28_shots")
    os.makedirs(shots, exist_ok=True)
    with H.browser() as b:
        refused = []
        pg = b.new_page(viewport={"width": 1500, "height": 950})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("response", lambda r: refused.append("%d %s" % (r.status, r.url))
              if r.status in (401, 403) else None)
        sid = AUTH.make_session_id(role="Dispatch Operator", login_id=LOGIN)
        pg.context.add_cookies([{"name": "icon_sid", "value": sid,
                                 "domain": "127.0.0.1", "path": "/"}])
        pg.goto(H.base_url() + "/")
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(1500)

        nav = pg.evaluate("Array.prototype.map.call(document.querySelectorAll("
                          "'#sidenav .nav-i[data-v]:not(.hide)'), function(b){return b.dataset.v})")
        assert set(nav) == VIEW, nav
        assert pg.evaluate("document.querySelector('.view.on').id") == "v-disp"

        for v in ("pack", "repack", "plan", "fqc"):
            pg.evaluate("go(%r)" % v)
            pg.wait_for_timeout(300)
            assert not pg.evaluate("document.getElementById('v-%s').classList.contains('on')" % v), v
            assert "does not have access" in pg.inner_text("#toast"), pg.inner_text("#toast")

        pg.evaluate("go('mgmt')"); pg.wait_for_timeout(900)
        assert pg.evaluate("document.getElementById('v-mgmt').classList.contains('on')")
        pg.screenshot(path=os.path.join(shots, "dashrath_mgmt.png"))

        for v, must_lock in (("challan", ["Create challan", "Save as draft"]),
                             ("invoice", ["New invoice"])):
            pg.evaluate("go(%r)" % v); pg.wait_for_timeout(1200)
            sec = "#v-" + v
            assert pg.is_visible(sec + " .ro-note"), v
            assert RO_REASON in pg.inner_text(sec + " .ro-note")
            for label in must_lock:
                btn = pg.locator(sec + " button", has_text=label).first
                assert btn.is_disabled(), (v, label)
                assert btn.get_attribute("title") == RO_REASON, (v, label)
            pg.screenshot(path=os.path.join(shots, "dashrath_%s.png" % v))
        pg.evaluate("go('challan-list')"); pg.wait_for_timeout(1200)
        assert "INV-DASHRATH-1" in pg.inner_text("#v-challan-list") or \
            pg.locator("#v-challan-list tbody tr").count() > 0, "no challan data shown"
        # the nav button, as a person reaches it - its onclick is what paints the list
        pg.click('#sidenav .nav-i[data-v="invoice"]')
        # Waits for the row rather than a fixed 1200ms: under a full suite the
        # fetch behind this list can take longer than that, and the sleep made
        # the whole file fail on a loaded machine and pass on a quiet one.
        try:
            pg.wait_for_function(
                "document.getElementById('v-invoice')"
                ".innerText.indexOf('INV-DASHRATH-1') >= 0", timeout=15000)
        except Exception:
            raise AssertionError("no invoice data shown: %r"
                                 % pg.inner_text("#v-invoice")[:200])
        pg.screenshot(path=os.path.join(shots, "dashrath_invoice.png"))

        for v in ("disp", "gp"):
            pg.evaluate("go(%r)" % v); pg.wait_for_timeout(900)
            assert pg.locator("#v-%s .ro-note" % v).count() == 0, v
            assert pg.locator("#v-%s .ro-locked" % v).count() == 0, v
        assert pg.locator("#v-disp button", has_text="Create challan").first.is_enabled()

        assert refused == [], refused
        assert pg.errors == [], pg.errors
        print("      nav %s, home v-disp, 0 refused requests, 0 page errors" % sorted(nav))


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
