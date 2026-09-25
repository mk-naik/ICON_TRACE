"""
ICON TRACE - free text typed into the system never runs as script.

    python test_stored_xss.py

A tagged <img onerror> is planted, through the real API, in every
free-text field an operator or a PDF can put into the record - indent
notes, a material's name, an invoice's buyer, a challan's transporter,
driver and consignee, a gate pass's party and description, an FQC reason,
a Quality resolution, an abandoned pallet's reason, a loss event's
machine, a production entry's incharge, a new user's display name. Then
every screen, the challan detail and Search & Trace are opened as a Super
Admin, and nothing may have run.

Found overnight on 25 Sep: three of these ran - a gate pass's party (the
gate-pass list's Customer filter), an invoice's buyer (the invoice list -
it comes out of an uploaded PDF), and a loss event's machine (v4's
renderLoss()). For those three the payload is also asserted present as
visible TEXT, so "did not run" cannot mean "was never shown".
"""

import csv, datetime, os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_xss_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "t.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
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


MODEL = "ISEN625-G12R"


def X(tag):
    return ('"><img src=x onerror="window.__xss=(window.__xss||[])'
            '.concat([\'%s\'])">' % tag)


def serial(i):
    return "ICON625R129071%04d" % i


def seed():
    store.wipe()
    AUTH.ensure_auth_schema()
    ss = os.path.join(TMP, "ss.csv")
    el = os.path.join(TMP, "el", "OK")
    os.makedirs(el, exist_ok=True)
    with open(ss, "w", newline="") as fh:
        csv.writer(fh).writerows([["2026-09-09 10:%02d:00" % i, serial(i), "630.5", "12.1",
            "48.9", "11.8", "52.5", "96.1", "0.41", "0.4", "210.0", "23.1", "25", "25",
            "1000"] for i in range(6)])
    for i in range(6):
        open(os.path.join(el, serial(i) + ".jpg"), "w").close()
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": ss, "el_root": os.path.dirname(el),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_a_root": "", "el_b_root": ""})
        for i in range(6):
            store.insert(cur, "serial", {"serial": serial(i), "build_instance": 1,
                "model": MODEL, "wattage": 625, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09", "shift": 1,
                "sequence": i, "state": "planned"})
    c = APP.app.test_client()
    AUTH.test_login(c)

    def ok(r, what):
        assert r.status_code == 200, (what, r.status_code, r.get_json(silent=True))
        return r.get_json()

    today = datetime.date.today().isoformat()
    item = icon_models.all_items()[0]["item_code"]
    ok(c.post("/api/indent", json={"indent_no": "XSS-1", "indent_date": "2026-09-09",
       "customer": "ICON STOCK", "area": X("indent.area"), "lot_name": X("indent.lot"),
       "delivery_text": X("indent.dtext"), "prepared_by": X("indent.prep"),
       "approved_by": X("indent.appr"), "special_instructions": X("indent.note"),
       "items": [{"item_code": item, "qty": 10}]}), "indent")
    ok(c.post("/api/material", json={"name": X("material.name"), "uom": "Nos"}), "material")
    ok(c.post("/api/fqc", json={"serial": serial(0), "outcome": "pass"}), "fqc")
    b = ok(c.post("/api/box/open", json={"grade": "A", "model": MODEL, "capacity": 1}), "box")
    ok(c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(0)}), "scan")
    ok(c.post("/api/box/%d/close" % b["box_id"], json={}), "close")
    with store.conn() as (cx, cur):
        inv = db.insert_invoice(cur, {"buyer_name": X("invoice.buyer"),
            "buyer_gstin": "22AAAAA0000A1Z5", "declared_qty": 1, "declared_model": MODEL,
            "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() + datetime.timedelta(days=10)).isoformat(),
            "invoice_no": "INV-XSS-1", "irn": None, "consignee_same_as_buyer": 1},
            "t.pdf", "feedxss", {"fields": {}, "compare_only": {}, "qr": {}}, False, {}, "tester")
    ch = ok(c.post("/api/challan", json={"action": "draft", "boxes": [b["box_id"]],
            "invoice_id": inv, "transporter": X("challan.transporter"),
            "driver_name": X("challan.driver"), "driver_mobile": "9999999999",
            "lr_no": X("challan.lr"), "vehicle_no": "CG04AB1234",
            "consignee_same_as_buyer": False, "consignee_name": X("challan.cname"),
            "consignee_address": X("challan.caddr")}), "challan")["challan_id"]
    ok(c.post("/api/challan/%d/submit" % ch, json={}), "submit")
    ok(c.post("/api/gatepass", json={"kind": "RGP", "party": X("gp.party"),
       "description": X("gp.desc"), "qty": 1, "delivery_address": X("gp.addr")}), "gatepass")
    ok(c.post("/api/fqc", json={"serial": serial(1), "outcome": "reject",
       "reason": "OV-QUALITY - " + X("fqc.reason")}), "reject")
    ok(c.post("/api/review/resolve", json={"type": "quality_grade", "id": serial(1),
       "grade": "GY", "reason": X("review.reason")}), "resolve")
    b2 = ok(c.post("/api/box/open", json={"grade": "A", "model": MODEL, "capacity": 2}), "box2")
    ok(c.post("/api/box/%d/abandon" % b2["box_id"], json={"reason": X("box.abandon")}), "abandon")
    ok(c.post("/api/loss_event", json={"line": "A", "mach": X("loss.mach"),
       "reason": "LOP-MACH", "kind": "P", "start": "09:00", "mode": "Live",
       "date": today, "shift": "A"}), "loss")
    ok(c.post("/api/prodentry", json={"date": today, "shift": "A",
       "incharge": X("prod.incharge"), "start_serial": serial(2),
       "end_serial": serial(3)}), "prodentry")
    ok(c.post("/api/users", json={"login_id": "xss.user", "display_name": X("user.name"),
       "role": "FQC Operator", "station": "FQC-01", "temp_password": "CorrectHorse99"}), "user")
    return ch


@test("every screen, the challan detail and Search & Trace, opened as a Super "
     "Admin over free text full of <img onerror> - nothing runs, and the three "
     "fields that used to run are on screen as plain text")
def t_nothing_runs():
    ch = seed()
    with H.browser() as b:
        pg = H.open_page(b, wait_ms=1500, role="Super Admin", login_id="sa1")
        views = pg.evaluate("Array.prototype.map.call(document.querySelectorAll("
                            "'#sidenav .nav-i[data-v]:not(.hide)'), function(x){return x.dataset.v})")
        for v in views + ["challan-list", "gp-list", "loading-list"]:
            nav = pg.locator('#sidenav .nav-i[data-v="%s"]' % v)
            if nav.count():
                nav.first.click()          # the nav button, as a person does
            else:
                pg.evaluate("go(%r)" % v)
            pg.wait_for_timeout(800)
            if v == "gp-list":
                gp_text = pg.evaluate("Array.prototype.map.call(document.querySelectorAll("
                                      "'#gpLCustomer option'), function(o){return o.textContent}).join('|')")
            if v == "invoice":
                inv_text = pg.inner_text("#invoiceListBody")
            if v == "loss":
                loss_text = pg.inner_text("#openRows")
        pg.evaluate("clOpenDetail(%d)" % ch); pg.wait_for_timeout(1200)
        pg.evaluate("go('search')"); pg.wait_for_timeout(600)
        for q in (serial(0), serial(1), "INV-XSS-1", "CG04AB1234"):
            pg.fill("#qBox", q)
            pg.evaluate("doSearch()"); pg.wait_for_timeout(1000)
        pg.evaluate("go('admin')"); pg.wait_for_timeout(1000)
        ran = pg.evaluate("window.__xss || []")
        assert ran == [], "script ran from: %s" % sorted(set(ran))
        for where, text, tag in (("gate-pass Customer filter", gp_text, "gp.party"),
                                 ("invoice list", inv_text, "invoice.buyer"),
                                 ("loss open events", loss_text, "loss.mach")):
            assert "onerror=" in text and tag in text, \
                "%s never showed the text: %r" % (where, text[:200])
        assert pg.errors == [], pg.errors
        print("      %d screens + challan detail + 4 searches; 0 payloads ran" % (len(views) + 3))


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
