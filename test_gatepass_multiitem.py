"""
ICON TRACE - tests for the rebuilt Gate Pass screen: the merged landing
list, multi-item standalone gate passes, and editing one.

    python test_gatepass_multiitem.py

THE RULES THIS FILE DEFENDS

  1. The landing list is ONE feed - module-linked and standalone gate
     passes together, never two lists the screen has to merge itself.

  2. Neither end of the date filter may be later than today - a real
     constraint, not a convention the picker merely suggests.

  3. A new standalone gate pass with several items persists every one of
     them in gatepass_item, correctly linked back to the gate pass.

  4. A module-linked gate pass is never editable - not from a hidden
     button, from the API itself: PUT is refused outright, regardless of
     what the UI would have shown.

  5. A standalone gate pass can be edited, and the edit lands in place -
     no supersede series, because unlike a challan a gate pass carries no
     invoice-reconciliation stakes that a later disagreement could arise
     against.

  6. Printing never breaks: a gate pass created before this change (the
     old single description/qty shape) still renders, and a new
     multi-item one shows every item row.

Each test names the rule it defends, so a failure says which decision broke.
"""

import datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_gpmulti_")
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
AGNI_GSTIN = "15AACCA2122Q1ZT"
AGNI_NAME = "AGNI GREEN POWER LIMITED (MZ)"


def setup():
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)          # a real Super Admin session (Round 23)
    return c


def serial(i):
    return "ICON%dR12907200%02d" % (WATT, i)


def packed_box(c, idx):
    with store.conn() as (cx, cur):
        for i in idx:
            store.insert(cur, "serial", {
                "serial": serial(i), "build_instance": 1, "model": MODEL,
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned",
                "grade": "A"})
            db.set_serial(cur, serial(i), state="graded")
    b = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                      "capacity": len(idx)}).get_json()
    for i in idx:
        r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": serial(i)})
        assert r.status_code == 200, r.get_json()
    c.post("/api/box/%d/close" % b["box_id"], json={})
    return b["box_id"]


def make_invoice(qty, invoice_no):
    data = {"buyer_name": AGNI_NAME, "buyer_gstin": AGNI_GSTIN,
            "declared_qty": qty, "declared_model": MODEL,
            "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                              datetime.timedelta(days=10)).isoformat(),
            "invoice_no": invoice_no, "irn": None,
            "consignee_same_as_buyer": 1}
    with store.conn() as (cx, cur):
        return db.insert_invoice(cur, data, "test.pdf", "deadbeef-" + invoice_no,
                                 {"fields": {}, "compare_only": {}, "qr": {}},
                                 False, {}, "tester")


def issue(c, box_ids, invoice_id):
    r = c.post("/api/challan", json={"action": "create", "boxes": box_ids,
                                     "invoice_id": invoice_id})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["challan_id"]


def load_all(c, challan_id):
    boxes = c.get("/api/loading/%d" % challan_id).get_json()["boxes"]
    for b in boxes:
        r = c.post("/api/loading/%d/confirm" % challan_id,
                   json={"box_no": b["box_no"]})
        assert r.status_code == 200, r.get_json()
    r = c.post("/api/loading/%d/submit" % challan_id, json={})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def module_gatepass(c, box_ids, invoice_no, qty):
    """Submitting Loading Verification is what creates a module gate pass
    now - nobody POSTs /api/gatepass with is_solar for this any more."""
    inv = make_invoice(qty, invoice_no)
    chid = issue(c, box_ids, inv)
    submitted = load_all(c, chid)
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM gatepass WHERE challan_id=%s", (chid,))
    assert row, "loading submit did not auto-create the gate pass"
    return {"gp_no": row["gp_no"], "gatepass_id": row["gp_id"],
           "challan_id": chid}


THREE_ITEMS = [
    {"description": "Laptop for repair", "unit": "Nos", "qty": 1, "remark": "urgent"},
    {"description": "Cell stock to Unit-1", "unit": "Kg", "qty": 50, "remark": None},
    {"description": "Spare frame set", "unit": "Set", "qty": 2, "remark": ""},
]


def standalone_gatepass(c, items=None, party="Repair vendor", kind="NRGP"):
    r = c.post("/api/gatepass", json={"kind": kind, "party": party,
                                      "items": items if items is not None else THREE_ITEMS})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


# --------------------------------------------------------------------------
# 1 - one merged feed
# --------------------------------------------------------------------------

@test("the landing list shows both module and standalone gate passes "
     "together, not two separate feeds")
def t_landing_merges_both():
    c = setup()
    b = packed_box(c, [0, 1])
    mod = module_gatepass(c, [b], "INV-GPM-1", 2)
    sa = standalone_gatepass(c)

    d = c.get("/api/gatepasses").get_json()
    nos = [r["gp_no"] for r in d["rows"]]
    assert mod["gp_no"] in nos, d
    assert sa["gp_no"] in nos, d
    assert len(d["rows"]) == 2, d["rows"]
    by_no = {r["gp_no"]: r for r in d["rows"]}
    assert by_no[mod["gp_no"]]["challan_id"], "module row lost its challan_id"
    assert not by_no[sa["gp_no"]]["challan_id"], "standalone row got a challan_id"


# --------------------------------------------------------------------------
# 2 - the date filter refuses a future date
# --------------------------------------------------------------------------

@test("the date filter refuses a future date - a real constraint, not a "
     "convention the picker merely suggests")
def t_date_filter_refuses_future():
    c = setup()
    standalone_gatepass(c)
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    r = c.get("/api/gatepasses?to=" + tomorrow)
    assert r.status_code == 400, r.get_json()
    assert r.get_json()["ok"] is False

    r2 = c.get("/api/gatepasses?from=" + tomorrow)
    assert r2.status_code == 400, r2.get_json()

    today = datetime.date.today().isoformat()
    r3 = c.get("/api/gatepasses?from=" + today + "&to=" + today)
    assert r3.status_code == 200, r3.get_json()
    assert len(r3.get_json()["rows"]) == 1


# --------------------------------------------------------------------------
# 3 - multi-item create persists every row, correctly linked
# --------------------------------------------------------------------------

@test("a new standalone gate pass with 3 added items persists all 3 rows "
     "in gatepass_item, correctly linked")
def t_multiitem_create_persists():
    c = setup()
    gp = standalone_gatepass(c)
    with store.conn() as (cx, cur):
        rows = [dict(r) for r in db.gatepass_items(cur, gp["gatepass_id"])]
    assert len(rows) == 3, rows
    descs = [r["description"] for r in rows]
    assert "Laptop for repair" in descs, rows
    assert "Cell stock to Unit-1" in descs, rows
    assert "Spare frame set" in descs, rows
    assert all(r["gatepass_id"] == gp["gatepass_id"] for r in rows), rows
    kg_row = [r for r in rows if r["unit"] == "Kg"][0]
    assert kg_row["qty"] == 50, kg_row

    # gatepass.description/qty stay NULL for a new multi-item row - the
    # real content lives in gatepass_item, not a stale summary of it.
    with store.conn() as (cx, cur):
        gp_row = store.one(cur, "SELECT * FROM gatepass WHERE gp_id=%s",
                          (gp["gatepass_id"],))
    assert gp_row["description"] is None, gp_row
    assert gp_row["qty"] is None, gp_row


@test("an item with no description, a bad unit, or a non-positive quantity "
     "is refused before anything is written")
def t_item_validation():
    c = setup()
    r = c.post("/api/gatepass", json={"kind": "NRGP", "party": "X",
                                      "items": [{"description": "", "unit": "Nos", "qty": 1}]})
    assert r.status_code == 400, r.get_json()
    r2 = c.post("/api/gatepass", json={"kind": "NRGP", "party": "X",
                                       "items": [{"description": "A", "unit": "Litres", "qty": 1}]})
    assert r2.status_code == 400, r2.get_json()
    r3 = c.post("/api/gatepass", json={"kind": "NRGP", "party": "X",
                                       "items": [{"description": "A", "unit": "Nos", "qty": 0}]})
    assert r3.status_code == 400, r3.get_json()
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM gatepass")["n"]
    assert n == 0, "a refused item still wrote a gate pass"


# --------------------------------------------------------------------------
# 4 - a module-linked gate pass is never editable
# --------------------------------------------------------------------------

@test("a module-linked gate pass has no Edit action available anywhere - "
     "enforced by the API itself, not only by the UI never showing one")
def t_module_linked_never_editable():
    c = setup()
    b = packed_box(c, [10, 11])
    mod = module_gatepass(c, [b], "INV-GPM-2", 2)

    r = c.put("/api/gatepass/%d" % mod["gatepass_id"], json={
        "kind": "NRGP", "party": "someone else",
        "items": [{"description": "x", "unit": "Nos", "qty": 1}]})
    assert r.status_code == 400, r.get_json()
    assert "challan" in r.get_json()["why"].lower(), r.get_json()

    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM gatepass WHERE gp_id=%s",
                       (mod["gatepass_id"],))
    assert row["party"] == AGNI_NAME, "the module-linked row was edited anyway"


# --------------------------------------------------------------------------
# 5 - a standalone gate pass can be edited, in place
# --------------------------------------------------------------------------

@test("a standalone gate pass can be edited and the change persists, "
     "mutated in place - no supersede series, since a gate pass carries "
     "no invoice-reconciliation stakes a later disagreement could arise "
     "against")
def t_standalone_edit_persists():
    c = setup()
    gp = standalone_gatepass(c, party="Original Vendor")
    original_id = gp["gatepass_id"]
    original_no = gp["gp_no"]

    new_items = [{"description": "Replacement laptop", "unit": "Nos",
                 "qty": 1, "remark": None}]
    r = c.put("/api/gatepass/%d" % original_id, json={
        "kind": "NRGP", "party": "Corrected Vendor",
        "vehicle_no": "CG04AB1234", "items": new_items})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["gp_no"] == original_no, \
        "editing minted a new gate pass number - this should mutate in place"

    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT * FROM gatepass WHERE gp_id=%s", (original_id,))
        items = [dict(r2) for r2 in db.gatepass_items(cur, original_id)]
        n_total = store.one(cur, "SELECT COUNT(*) AS n FROM gatepass")["n"]
    assert row["party"] == "Corrected Vendor", row
    assert row["vehicle_no"] == "CG04AB1234", row
    assert row["gp_id"] == original_id, "a new row was created instead of mutating"
    assert n_total == 1, "editing created a second gate pass row"
    assert len(items) == 1 and items[0]["description"] == "Replacement laptop", items


@test("editing a standalone gate pass with no items is refused")
def t_edit_requires_items():
    c = setup()
    gp = standalone_gatepass(c)
    r = c.put("/api/gatepass/%d" % gp["gatepass_id"],
             json={"kind": "NRGP", "party": "X", "items": []})
    assert r.status_code == 400, r.get_json()


# --------------------------------------------------------------------------
# 6 - printing never breaks, old or new shape
# --------------------------------------------------------------------------

@test("printing a gate pass created before this change (the old "
     "single-field shape) still renders correctly - no crash on missing "
     "gatepass_item rows")
def t_print_old_shape_still_works():
    c = setup()
    r = c.post("/api/gatepass", json={"kind": "RGP", "party": "Legacy Party",
                                      "description": "Old-style equipment",
                                      "qty": 4})
    gp_no = r.get_json()["gp_no"]
    pr = c.get("/gatepass/%s/print" % gp_no)
    assert pr.status_code == 200, pr.status_code
    body = pr.get_data(as_text=True)
    assert "Old-style equipment" in body, body
    assert gp_no in body


@test("printing a new multi-item gate pass shows every item row on the "
     "document")
def t_print_multiitem_shows_every_row():
    c = setup()
    gp = standalone_gatepass(c)
    pr = c.get("/gatepass/%s/print" % gp["gp_no"])
    assert pr.status_code == 200, pr.status_code
    body = pr.get_data(as_text=True)
    for item in THREE_ITEMS:
        assert item["description"] in body, \
            "%r missing from the printed document" % item["description"]
    # the total quantity sums every item, not just the old single field
    assert ">53<" in body, body   # 1 + 50 + 2


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
