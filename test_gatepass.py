"""
ICON TRACE - tests for Gate Pass's module mode.

    python test_gatepass.py

THE RULE THIS FILE DEFENDS

    A gate pass linked to a real challan (module mode - the only path that
    ever sends challan_id) is refused unless every pallet on that challan is
    confirmed loaded. This is enforced from the fact that a real challan_id
    was sent, never from a client-asserted "is_solar" flag - a client that
    omits the flag while still linking a real, incomplete challan is refused
    exactly the same as one that sends it, the same no-override discipline
    the quantity gate and the e-Way Bill expiry check already hold.

    Standalone gate passes (no challan_id at all) are untouched by any of
    this - today's working flow, unchanged.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_gatepass_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


WATT = 630
MODEL = "ISEN630-G12R"
SS = os.path.join(TMP, "ss.csv")
EL = os.path.join(TMP, "el", "OK")
os.makedirs(EL, exist_ok=True)

AGNI_GSTIN = "15AACCA2122Q1ZT"          # seeded customer C0001
AGNI_NAME = "AGNI GREEN POWER LIMITED (MZ)"


def serial(i, watt=WATT):
    return "ICON%dR12907100%02d" % (watt, i)


def setup():
    store.wipe()
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS, "el_root": os.path.dirname(EL),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_a_root": "", "el_b_root": ""})
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


def _seed_serials(idx, watt=WATT, model=MODEL):
    rows = []
    for i in idx:
        s = serial(i, watt)
        if not os.path.exists(os.path.join(EL, s + ".jpg")):
            open(os.path.join(EL, s + ".jpg"), "w").close()
        rows.append(["2026-09-09 10:%02d:00" % (i % 60), s, "%d.0" % (watt + 0.5),
                     "12.1", "48.9", "11.8", "52.5", "96.1", "0.41", "0.4",
                     "210.0", "23.1", "25", "25", "1000"])
    mode = "a" if os.path.exists(SS) else "w"
    with open(SS, mode, newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    with store.conn() as (cx, cur):
        for i in idx:
            s = serial(i, watt)
            if db.find_serial(cur, s):
                continue
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": model,
                "wattage": watt, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned"})


def packed_box(c, idx, watt=WATT, model=MODEL, grade="A", customer=None):
    """A closed pallet holding the modules at those indexes."""
    _seed_serials(idx, watt, model)
    for i in idx:
        r = c.post("/api/fqc", json={"serial": serial(i, watt), "outcome": "pass"})
        assert r.status_code == 200, r.get_json()
    b = c.post("/api/box/open", json={"grade": grade, "model": model,
                                      "capacity": len(idx),
                                      "customer": customer}).get_json()
    for i in idx:
        r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(i, watt)})
        assert r.status_code == 200, r.get_json()
    c.post("/api/box/%d/close" % b["box_id"], json={})
    return b["box_id"]


def make_invoice(qty, buyer_name=AGNI_NAME, buyer_gstin=AGNI_GSTIN, invoice_no=None):
    data = {"buyer_name": buyer_name, "buyer_gstin": buyer_gstin,
            "declared_qty": qty, "declared_model": MODEL,
            "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                               datetime.timedelta(days=10)).isoformat(),
            "invoice_no": invoice_no, "irn": None,
            "consignee_same_as_buyer": 1}
    with store.conn() as (cx, cur):
        return db.insert_invoice(cur, data, "test.pdf", "deadbeef-gp-" + invoice_no,
                                 {"fields": {}, "compare_only": {}, "qr": {}},
                                 False, {}, "tester")


def issue(c, box_ids, invoice_id):
    """Create + submit a challan so it is status='issued'."""
    r = c.post("/api/challan", json={"action": "create", "boxes": box_ids,
                                     "invoice_id": invoice_id})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["challan_id"]


def load_all(c, challan_id):
    """Confirm and submit every pallet on a challan - fully loaded."""
    boxes = c.get("/api/loading/%d" % challan_id).get_json()["boxes"]
    for b in boxes:
        r = c.post("/api/loading/%d/confirm" % challan_id,
                   json={"box_no": b["box_no"]})
        assert r.status_code == 200, r.get_json()
    r = c.post("/api/loading/%d/submit" % challan_id, json={})
    assert r.status_code == 200, r.get_json()


def gp_count():
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT COUNT(*) AS n FROM gatepass")["n"]


@test("standalone mode (no challan_id at all) is untouched - today's "
     "working flow, regardless of anything else in the system")
def t_standalone_untouched():
    c = setup()
    r = c.post("/api/gatepass", json={"kind": "RGP", "party": "Standalone",
                                      "description": "Test equipment", "qty": 1})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["ok"]
    assert gp_count() == 1


@test("a module-mode gate pass against an incomplete challan is refused, "
     "naming exactly how many pallets are still pending - the same wording "
     "the print/excel routes already use, not a second version of it")
def t_module_mode_refused_incomplete():
    c = setup()
    b1 = packed_box(c, [0, 1])
    b2 = packed_box(c, [2, 3])
    inv = make_invoice(qty=4, invoice_no="INV-GP-1")
    chid = issue(c, [b1, b2], inv)
    # nothing confirmed yet - 0 of 2 pallets

    r = c.post("/api/gatepass", json={"is_solar": True, "challan_id": chid,
                                      "kind": "NRGP", "party": "AGNI",
                                      "description": "Modules"})
    assert r.status_code == 400, r.get_json()
    why = r.get_json()["why"]
    assert "0 of 2" in why, why
    assert not r.get_json()["ok"]
    assert gp_count() == 0, "a refused gate pass still wrote a row"


@test("loading a fully-loaded challan auto-creates its gate pass - a "
     "person no longer POSTs this manually, and a manual attempt against "
     "the same challan afterward is refused as a duplicate, not a second "
     "real record")
def t_module_mode_succeeds_when_loaded():
    c = setup()
    b1 = packed_box(c, [10, 11])
    inv = make_invoice(qty=2, invoice_no="INV-GP-2")
    chid = issue(c, [b1], inv)
    load_all(c, chid)               # this is what actually creates it now
    assert gp_count() == 1, "loading submit did not auto-create the gate pass"

    r = c.post("/api/gatepass", json={"is_solar": True, "challan_id": chid,
                                      "kind": "NRGP", "party": "AGNI",
                                      "description": "Modules"})
    assert r.status_code == 400, \
        "a second gate pass was created for a challan that already has one"
    assert "already has a gate pass" in r.get_json()["why"], r.get_json()
    assert gp_count() == 1, "the duplicate attempt still wrote a second row"


@test("a real bug this file was written to catch: omitting is_solar (or "
     "sending it False) while still linking a real, incomplete challan_id "
     "is refused exactly the same - the rule is keyed on the challan_id "
     "being real, never on the client's own flag. Simulated directly, not "
     "through the button state a bypassed client would never show")
def t_bypass_is_solar_flag_still_refused():
    c = setup()
    b1 = packed_box(c, [20, 21])
    b2 = packed_box(c, [22, 23])
    inv = make_invoice(qty=4, invoice_no="INV-GP-3")
    chid = issue(c, [b1, b2], inv)

    # is_solar omitted entirely - exactly what a client bypassing the
    # checkbox's own JS gate would send
    r = c.post("/api/gatepass", json={"challan_id": chid, "kind": "NRGP",
                                      "party": "AGNI", "description": "Modules"})
    assert r.status_code == 400, \
        "omitting is_solar let an incomplete challan's gate pass through: " + str(r.get_json())
    assert "Loading verification is not complete" in r.get_json()["why"]
    assert gp_count() == 0


@test("is_solar explicitly False changes nothing either - the challan_id "
     "itself is what the server acts on")
def t_bypass_is_solar_false_still_refused():
    c = setup()
    b1 = packed_box(c, [30, 31])
    inv = make_invoice(qty=2, invoice_no="INV-GP-4")
    chid = issue(c, [b1], inv)

    r = c.post("/api/gatepass", json={"is_solar": False, "challan_id": chid,
                                      "kind": "NRGP", "party": "AGNI",
                                      "description": "Modules"})
    assert r.status_code == 400, r.get_json()
    assert gp_count() == 0


@test("a challan_id that does not exist is refused, not silently treated "
     "as no challan at all")
def t_nonexistent_challan_refused():
    c = setup()
    r = c.post("/api/gatepass", json={"challan_id": 999999, "kind": "NRGP",
                                      "party": "AGNI", "description": "Modules"})
    assert r.status_code == 400, r.get_json()
    assert "no longer exists" in r.get_json()["why"].lower()
    assert gp_count() == 0


@test("a draft (not yet issued) challan_id is refused - only a live, "
     "issued challan can back a gate pass")
def t_draft_challan_refused():
    c = setup()
    b1 = packed_box(c, [40, 41])
    inv = make_invoice(qty=2, invoice_no="INV-GP-5")
    r0 = c.post("/api/challan", json={"action": "draft", "boxes": [b1],
                                      "invoice_id": inv})
    draft_id = r0.get_json()["challan_id"]

    r = c.post("/api/gatepass", json={"challan_id": draft_id, "kind": "NRGP",
                                      "party": "AGNI", "description": "Modules"})
    assert r.status_code == 400, r.get_json()
    assert "issued" in r.get_json()["why"].lower()
    assert gp_count() == 0


@test("a historical challan (predates Loading Verification entirely) is "
     "exempt from the loading gate, the same exemption print/excel "
     "already give it - not a second, drifted copy of that rule")
def t_historical_challan_exempt():
    c = setup()
    with store.conn() as (cx, cur):
        chid = store.insert(cur, "challan", {
            "fy": 2025, "seq": 1, "challan_date": "2025-06-01", "qty": 36,
            "status": "issued", "origin": "historical",
            "created_by": "historical-import"})
        store.insert(cur, "challan_box", {
            "challan_id": chid, "box_no": "OLDBOX1", "qty": 36,
            "loading_status": "pending", "load_order": 1,
            "pack_date": "2025-06-01"})

    r = c.post("/api/gatepass", json={"is_solar": True, "challan_id": chid,
                                      "kind": "NRGP", "party": "AGNI",
                                      "description": "Modules"})
    assert r.status_code == 200, r.get_json()
    assert gp_count() == 1


@test("a cancelled challan_id is refused - status must be issued, not "
     "merely once-real")
def t_cancelled_challan_refused():
    c = setup()
    b1 = packed_box(c, [50, 51])
    inv = make_invoice(qty=2, invoice_no="INV-GP-6")
    chid = issue(c, [b1], inv)
    r0 = c.post("/api/challan/%d/cancel" % chid, json={"reason": "test"})
    assert r0.status_code == 200, r0.get_json()

    r = c.post("/api/gatepass", json={"challan_id": chid, "kind": "NRGP",
                                      "party": "AGNI", "description": "Modules"})
    assert r.status_code == 400, r.get_json()
    assert gp_count() == 0


@test("GET /api/challan/<id> exposes the aggregate loading status the "
     "client reads to gate Issue before submitting - reusing the same "
     "_loading_agg_status() Loading Verification's own list already calls, "
     "not a second version of that aggregation")
def t_challan_detail_exposes_loading_agg():
    c = setup()
    b1 = packed_box(c, [60, 61])
    b2 = packed_box(c, [62, 63])
    inv = make_invoice(qty=4, invoice_no="INV-GP-7")
    chid = issue(c, [b1, b2], inv)

    d = c.get("/api/challan/%d" % chid).get_json()
    assert d["challan"]["loading_agg"] == "pending", d["challan"]
    assert d["challan"]["loading_n_total"] == 2, d["challan"]
    assert d["challan"]["loading_n_loaded"] == 0, d["challan"]
    assert "0 of 2" in (d["challan"]["loading_why"] or ""), d["challan"]

    load_all(c, chid)
    d2 = c.get("/api/challan/%d" % chid).get_json()
    assert d2["challan"]["loading_agg"] == "loaded", d2["challan"]
    assert d2["challan"]["loading_n_loaded"] == 2, d2["challan"]
    assert d2["challan"]["loading_why"] is None, d2["challan"]


@test("the gate pass print route's QR resolves back to the real record - "
     "identity only, the same minimal shape every other printed QR uses")
def t_print_qr_resolves_to_real_record():
    c = setup()
    r = c.post("/api/gatepass", json={"kind": "RGP", "party": "Standalone",
                                      "description": "Test equipment", "qty": 1})
    gp_no = r.get_json()["gp_no"]
    assert gp_no, r.get_json()
    import icon_barcode as bc
    payload = bc.gp_qr_payload(gp_no)
    assert payload == "ICONTRACE|GATEPASS|%s" % gp_no, payload
    parts = payload.split("|")
    assert parts[0] == "ICONTRACE" and parts[1] == "GATEPASS" and parts[2] == gp_no

    pr = c.get("/gatepass/%s/print" % gp_no)
    assert pr.status_code == 200, pr.status_code
    body = pr.get_data(as_text=True)
    assert gp_no in body


if __name__ == "__main__":
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
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
