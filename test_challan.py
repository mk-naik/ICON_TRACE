"""
ICON TRACE - tests for Create Challan.

    python test_challan.py

THE RULE THIS FILE DEFENDS

    A challan's quantity is always the sum of the boxes actually ticked -
    never read from, or bent to fit, the invoice. It must exactly equal what
    the invoice declares, and there is no override anywhere in this path:
    the same rule the invoice-confirm screen already enforces on quantity is
    enforced again here, not weakened because the number now comes from
    boxes instead of a scan count.

    A box goes on one challan. Ticking it onto a second one - including a
    draft, which reserves the same way a real challan does - is refused, and
    the boxes stay in the order they were ticked, not resorted by number.

    The sequence is drawn once, at Save as draft, and a submit later never
    redraws it - a challan started before midnight keeps the number it was
    given no matter when it is actually confirmed.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_challan_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


WATT = 630
MODEL = "ISEN630-G12R"
OTHER_WATT = 625
OTHER_MODEL = "ISEN625-G12R"
SS = os.path.join(TMP, "ss.csv")
EL = os.path.join(TMP, "el", "OK")
os.makedirs(EL, exist_ok=True)

AGNI_GSTIN = "15AACCA2122Q1ZT"          # seeded customer C0001
AGNI_NAME = "AGNI GREEN POWER LIMITED (MZ)"
BOROSIL_CODE = "C0002"


def serial(i, watt=WATT):
    body = "ICON%dR12907100%02d" % (watt, i)
    return body


def setup():
    store.wipe()
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS, "el_root": os.path.dirname(EL),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_a_root": "", "el_b_root": ""})
    return APP.app.test_client()


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


def packed_box(c, idx, watt=WATT, model=MODEL, grade="A", customer=None,
              capacity=None):
    """A closed pallet holding the modules at those indexes."""
    _seed_serials(idx, watt, model)
    if capacity is None:
        capacity = len(idx)
    for i in idx:
        r = c.post("/api/fqc", json={"serial": serial(i, watt), "outcome": "pass"})
        assert r.status_code == 200, r.get_json()
    b = c.post("/api/box/open", json={"grade": grade, "model": model,
                                      "capacity": capacity,
                                      "customer": customer}).get_json()
    for i in idx:
        r = c.post("/api/box/%d/scan" % b["box_id"],
                   json={"serial": serial(i, watt)})
        assert r.status_code == 200, r.get_json()
    c.post("/api/box/%d/close" % b["box_id"], json={})
    return b["box_id"]


def make_invoice(qty, model=MODEL, buyer_name=AGNI_NAME, buyer_gstin=AGNI_GSTIN,
                 ewb_valid_upto=None, irn=None, invoice_no=None):
    if ewb_valid_upto is None:
        ewb_valid_upto = (datetime.date.today() +
                          datetime.timedelta(days=10)).isoformat()
    data = {"buyer_name": buyer_name, "buyer_gstin": buyer_gstin,
            "declared_qty": qty, "declared_model": model,
            "ewb_no": "111122223333", "ewb_valid_upto": ewb_valid_upto,
            "invoice_no": invoice_no or ("INV-%d" % (id(qty) % 100000)),
            "irn": irn, "consignee_same_as_buyer": 1}
    with store.conn() as (cx, cur):
        return db.insert_invoice(cur, data, "test.pdf", "deadbeef" + str(qty),
                                 {"fields": {}, "compare_only": {}, "qr": {}},
                                 False, {}, "tester")


def challan_row(chid):
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT * FROM challan WHERE challan_id=%s",
                         (chid,))


def state_of(s):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, s) or {}).get("state")


def box_row(bid):
    with store.conn() as (cx, cur):
        return dict(store.box_row(cur, bid))


# --------------------------------------------------------------------------
# quantity - the rule with no exception
# --------------------------------------------------------------------------

@test("creating with no invoice selected is refused")
def t_no_invoice():
    c = setup()
    b = packed_box(c, [0, 1])
    r = c.post("/api/challan", json={"action": "create", "boxes": [b]})
    assert r.status_code == 400, "a challan was created against nothing"
    assert "invoice" in r.get_json()["why"].lower(), r.get_json()
    assert challan_row_count() == 0


def challan_row_count():
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT COUNT(*) AS n FROM challan")["n"]


@test("a quantity mismatch is refused, naming both numbers")
def t_qty_mismatch():
    c = setup()
    b = packed_box(c, [0, 1])                 # 2 modules
    inv = make_invoice(qty=5)                  # invoice says 5
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 400
    why = r.get_json()["why"]
    assert "5" in why and "2" in why, why
    assert challan_row_count() == 0


@test("no override exists for a quantity mismatch")
def t_qty_no_override():
    c = setup()
    b = packed_box(c, [0, 1])
    inv = make_invoice(qty=5)
    # every field an override might plausibly ride in on, sent anyway
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv, "override": True,
                                     "force": True, "confirm_mismatch": True,
                                     "qty": 2})
    assert r.status_code == 400, "a mismatch was overridden"
    assert challan_row_count() == 0


@test("matching quantity, with a real invoice, creates the challan")
def t_qty_matches():
    c = setup()
    b = packed_box(c, [0, 1, 2])
    inv = make_invoice(qty=3)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["qty"] == 3 and d["status"] == "issued"
    assert challan_row_count() == 1


@test("quantity is always the sum of boxes ticked, never the invoice figure")
def t_qty_is_boxes_not_invoice():
    c = setup()
    b1 = packed_box(c, [0, 1])
    b2 = packed_box(c, [2, 3, 4])
    inv = make_invoice(qty=5)
    r = c.post("/api/challan", json={"action": "create",
                                     "boxes": [b1, b2], "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    ch = challan_row(r.get_json()["challan_id"])
    assert ch["qty"] == 5, ch["qty"]
    assert ch["declared_qty"] == 5


# --------------------------------------------------------------------------
# one box, one challan
# --------------------------------------------------------------------------

@test("a box already on a live challan cannot be selected onto another")
def t_box_not_reselectable():
    c = setup()
    b = packed_box(c, [0, 1])
    inv1 = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv1})
    assert r.status_code == 200, r.get_json()

    inv2 = make_invoice(qty=2)
    r2 = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                      "invoice_id": inv2})
    assert r2.status_code == 400, "the same box rode on two challans"
    assert "already on challan" in r2.get_json()["why"], r2.get_json()


@test("a box on a live challan is excluded from the available list")
def t_box_excluded_from_list():
    c = setup()
    b = packed_box(c, [0, 1])
    before = {r["box_id"] for r in c.get("/api/challan/boxes").get_json()}
    assert b in before
    inv = make_invoice(qty=2)
    c.post("/api/challan", json={"action": "create", "boxes": [b],
                                 "invoice_id": inv})
    after = {r["box_id"] for r in c.get("/api/challan/boxes").get_json()}
    assert b not in after, "a taken box still offered itself for selection"


@test("boxes stay in the order they were ticked, not box-number order")
def t_load_order():
    c = setup()
    # opened in this order, so the SECOND box carries the HIGHER box number
    first_opened = packed_box(c, [0])
    second_opened = packed_box(c, [1])
    assert second_opened > first_opened, \
        "fixture assumption broke: ids are not increasing"
    inv = make_invoice(qty=2)
    # ticked in the OPPOSITE order to how they were opened/numbered
    r = c.post("/api/challan", json={"action": "create",
                                     "boxes": [second_opened, first_opened],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT box_no, load_order FROM challan_box "
                               "WHERE challan_id=%s ORDER BY load_order",
                          (r.get_json()["challan_id"],))
    # a re-sort by box number would put first_opened's lower-numbered label
    # first; ticked order demands second_opened's label first instead
    assert rows[0]["box_no"] == APP._box_label(box_row(second_opened)), \
        "the ticked order was not honoured, boxes were resorted: %s" % rows
    assert rows[1]["box_no"] == APP._box_label(box_row(first_opened)), rows


# --------------------------------------------------------------------------
# the invoice gate
# --------------------------------------------------------------------------

@test("an expired e-Way Bill blocks creation")
def t_expired_ewb():
    c = setup()
    b = packed_box(c, [0, 1])
    past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    inv = make_invoice(qty=2, ewb_valid_upto=past)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 400
    assert "e-way bill" in r.get_json()["why"].lower(), r.get_json()
    assert challan_row_count() == 0


@test("an e-Way Bill valid today or later does not block")
def t_ewb_not_yet_expired():
    c = setup()
    b = packed_box(c, [0, 1])
    today = datetime.date.today().isoformat()
    inv = make_invoice(qty=2, ewb_valid_upto=today)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()


@test("a superseded invoice blocks creation and names the newer one")
def t_superseded_invoice():
    c = setup()
    b = packed_box(c, [0, 1])
    old = make_invoice(qty=2, invoice_no="INV-OLD", irn="IRN-OLD")
    new = make_invoice(qty=2, invoice_no="INV-NEW", irn="IRN-NEW")
    with store.conn() as (cx, cur):
        db.supersede_invoice(cur, old, new)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": old})
    assert r.status_code == 400
    why = r.get_json()["why"]
    assert "INV-NEW" in why, why
    assert challan_row_count() == 0
    # and the newer one works
    r2 = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                      "invoice_id": new})
    assert r2.status_code == 200, r2.get_json()


# --------------------------------------------------------------------------
# draft: reservation now, dispatch later
# --------------------------------------------------------------------------

@test("Save as draft reserves the boxes; a second selection is refused")
def t_draft_reserves():
    c = setup()
    b = packed_box(c, [0, 1])
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["status"] == "draft"
    # the module is NOT dispatched yet - only reserved
    assert state_of(serial(0)) == "packed", state_of(serial(0))

    inv2 = make_invoice(qty=2)
    r2 = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                      "invoice_id": inv2})
    assert r2.status_code == 400, "a drafted box was drafted again elsewhere"
    assert "already on challan" in r2.get_json()["why"], r2.get_json()


@test("submitting a draft on a REPACKED box does not also re-check its "
     "retired parent - box_serial keeps rows for both")
def t_submit_after_repack():
    # Repack deliberately keeps the retired parent's box_serial rows so
    # "what did this pallet hold?" stays answerable - which means a naive
    # serial -> box_serial join for one CHILD box's serial also matches its
    # retired PARENT. Submit has to recover only the live box, the same way
    # serial_in_live_box() already does everywhere else.
    c = setup()
    parent = packed_box(c, [0, 1, 2])
    r = c.post("/api/box/%d/repack" % parent,
              json={"reason": "customer split", "groups":
                    [{"serials": [serial(0), serial(1), serial(2)]}]})
    assert r.status_code == 200, r.get_json()
    child = r.get_json()["children"][0]["box_id"]
    assert box_row(child)["state"] == "closed"
    assert box_row(parent)["state"] == "retired"

    inv = make_invoice(qty=3)
    r = c.post("/api/challan", json={"action": "draft", "boxes": [child],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    chid = r.get_json()["challan_id"]

    r2 = c.post("/api/challan/%d/submit" % chid, json={})
    assert r2.status_code == 200, r2.get_json()
    assert state_of(serial(0)) == "dispatched"


@test("the sequence drawn at draft is reused at submit, never redrawn")
def t_draft_seq_reused_at_submit():
    c = setup()
    b = packed_box(c, [0, 1])
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                     "invoice_id": inv})
    chid, fy, seq = r.get_json()["challan_id"], r.get_json()["fy"], \
        r.get_json()["seq"]

    # prove submit never draws a new number, rather than merely observing
    # that the two happen to match
    real_draw = db.draw_challan_seq
    db.draw_challan_seq = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("submit must not draw a new sequence"))
    try:
        r2 = c.post("/api/challan/%d/submit" % chid, json={})
    finally:
        db.draw_challan_seq = real_draw
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()["fy"] == fy and r2.get_json()["seq"] == seq
    assert state_of(serial(0)) == "dispatched"


@test("submit re-checks: an invoice that expired between draft and submit blocks")
def t_submit_rechecks():
    c = setup()
    b = packed_box(c, [0, 1])
    soon = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    inv = make_invoice(qty=2, ewb_valid_upto=soon)
    r = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                     "invoice_id": inv})
    chid = r.get_json()["challan_id"]
    # the e-Way Bill lapses while the draft sits open
    with store.conn() as (cx, cur):
        cur.execute("UPDATE invoice SET ewb_valid_upto=%s WHERE invoice_id=%s",
                    ((datetime.date.today() -
                      datetime.timedelta(days=1)).isoformat(), inv))
    r2 = c.post("/api/challan/%d/submit" % chid, json={})
    assert r2.status_code == 400
    assert "e-way bill" in r2.get_json()["why"].lower(), r2.get_json()
    assert challan_row(chid)["status"] == "draft"
    assert state_of(serial(0)) == "packed", "submitted despite the refusal"


@test("discarding a draft frees the boxes it reserved")
def t_discard_frees_boxes():
    c = setup()
    b = packed_box(c, [0, 1])
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                     "invoice_id": inv})
    chid = r.get_json()["challan_id"]
    r2 = c.post("/api/challan/%d/discard" % chid, json={})
    assert r2.status_code == 200, r2.get_json()
    ids = {row["box_id"] for row in c.get("/api/challan/boxes").get_json()}
    assert b in ids, "discarding a draft did not free its box"
    assert challan_row(chid)["status"] == "cancelled"
    # and it can now go on a real challan
    inv2 = make_invoice(qty=2)
    r3 = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                      "invoice_id": inv2})
    assert r3.status_code == 200, r3.get_json()


@test("only a draft can be discarded")
def t_discard_only_draft():
    c = setup()
    b = packed_box(c, [0, 1])
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    chid = r.get_json()["challan_id"]
    r2 = c.post("/api/challan/%d/discard" % chid, json={})
    assert r2.status_code == 400
    assert challan_row(chid)["status"] == "issued"


# --------------------------------------------------------------------------
# customer, and General Stock
# --------------------------------------------------------------------------

@test("a box owned by a different customer than the invoice's buyer blocks")
def t_wrong_owner_blocks():
    c = setup()
    b = packed_box(c, [0, 1], customer=BOROSIL_CODE)
    inv = make_invoice(qty=2)              # buyer resolves to AGNI, C0001
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 400
    why = r.get_json()["why"].upper()
    assert "BOROSIL" in why and "AGNI" in why, r.get_json()["why"]


@test("a General Stock box is assigned to the buyer at challan, not blocked")
def t_general_stock_assigned():
    c = setup()
    b = packed_box(c, [0, 1], customer=None)
    assert box_row(b)["customer"] is None
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    assert box_row(b)["customer"] == "C0001", \
        "General Stock never became the buyer's: %r" % box_row(b)["customer"]


@test("a box stored under the STOCK pseudo-customer's NAME is General "
     "Stock too, not an unmovable owner")
def t_general_stock_by_stored_name():
    # box.customer is meant to hold a CODE, but real boxes have turned up
    # holding "ICON STOCK" - the display name - instead of "STOCK". That is
    # a Packing-side data bug this screen does not fix at the source, but a
    # challan still has to recognise what it plainly means: nobody real
    # owns this box yet.
    c = setup()
    b = packed_box(c, [0, 1], customer="ICON STOCK")
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    assert box_row(b)["customer"] == "C0001", \
        "a box spelt 'ICON STOCK' was treated as a foreign owner: %r" % \
        box_row(b)["customer"]


@test("assign_customer_on_challan never overwrites an existing customer")
def t_assign_does_not_overwrite():
    c = setup()
    b = packed_box(c, [0, 1], customer=BOROSIL_CODE)
    with store.conn() as (cx, cur):
        db.assign_customer_on_challan(cur, b, "C0001", "tester")
    assert box_row(b)["customer"] == BOROSIL_CODE, \
        "a box that already had an owner was reassigned"


@test("General Stock boxes for different, unresolvable buyers may still "
     "mix if the invoice buyer itself cannot be resolved")
def t_unresolvable_buyer_does_not_crash():
    c = setup()
    b = packed_box(c, [0, 1], customer=None)
    inv = make_invoice(qty=2, buyer_name="SOME BRAND NEW COMPANY LTD",
                       buyer_gstin="99ZZZZZ9999Z1Z9")
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    # nothing to resolve the buyer to - the box is left as it was, not
    # invented into a customer code that does not exist
    assert box_row(b)["customer"] is None


# --------------------------------------------------------------------------
# what packing already refuses, this refuses too
# --------------------------------------------------------------------------

@test("an ungraded (historical) box cannot go on a challan")
def t_ungraded_box_blocks():
    c = setup()
    b = packed_box(c, [0, 1])
    with store.conn() as (cx, cur):
        cur.execute("UPDATE box SET grade=NULL WHERE box_id=%s", (b,))
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 400
    assert "no grade" in r.get_json()["why"].lower(), r.get_json()


@test("an open (unclosed) box cannot go on a challan")
def t_open_box_blocks():
    c = setup()
    _seed_serials([0, 1])
    c.post("/api/fqc", json={"serial": serial(0), "outcome": "pass"})
    ob = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                       "capacity": 1}).get_json()
    c.post("/api/box/%d/scan" % ob["box_id"], json={"serial": serial(0)})
    inv = make_invoice(qty=1)
    r = c.post("/api/challan", json={"action": "create",
                                     "boxes": [ob["box_id"]],
                                     "invoice_id": inv})
    assert r.status_code == 400
    assert "not a closed pallet" in r.get_json()["why"], r.get_json()


# --------------------------------------------------------------------------
# KW - always derived, mixed models included
# --------------------------------------------------------------------------

@test("KW is derived per box and sums correctly for a single model")
def t_kw_single_model():
    c = setup()
    b = packed_box(c, [0, 1], watt=WATT, model=MODEL)     # 2 x 630W
    inv = make_invoice(qty=2, model=MODEL)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    assert abs(r.get_json()["kw"] - 1.26) < 1e-9, r.get_json()["kw"]


@test("mixed-model boxes on one challan compute the correct combined KW")
def t_kw_mixed_models():
    c = setup()
    b1 = packed_box(c, [0, 1], watt=WATT, model=MODEL)          # 2 x 630
    b2 = packed_box(c, [0, 1, 2], watt=OTHER_WATT, model=OTHER_MODEL)  # 3 x 625
    inv = make_invoice(qty=5, model=None)
    r = c.post("/api/challan", json={"action": "create",
                                     "boxes": [b1, b2], "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    expect = (2 * WATT + 3 * OTHER_WATT) / 1000.0
    # the API rounds KW to 2dp for display, same as v4's toFixed(1) did for
    # its own total - compare against that rounding, not the raw float,
    # since 3.135 has no exact binary representation and round() may take
    # either neighbour
    assert abs(r.get_json()["kw"] - round(expect, 2)) < 1e-9, \
        (r.get_json()["kw"], expect)
    ch = challan_row(r.get_json()["challan_id"])
    # the stored (weighted-average) wattage, multiplied back by qty, still
    # gives the exact true total watts - the print and Excel routes derive
    # KW as wattage * qty, and were not touched to make this work
    assert abs(ch["wattage"] * ch["qty"] - (2 * WATT + 3 * OTHER_WATT)) < 1e-6, \
        ch["wattage"]
    assert "+" in ch["model"], ch["model"]


# --------------------------------------------------------------------------
# what actually gets written
# --------------------------------------------------------------------------

@test("Create moves every serial to dispatched; draft leaves them packed")
def t_serial_states():
    c = setup()
    b1 = packed_box(c, [0, 1])
    inv1 = make_invoice(qty=2)
    c.post("/api/challan", json={"action": "draft", "boxes": [b1],
                                 "invoice_id": inv1})
    assert state_of(serial(0)) == "packed"

    b2 = packed_box(c, [10, 11])
    inv2 = make_invoice(qty=2)
    c.post("/api/challan", json={"action": "create", "boxes": [b2],
                                 "invoice_id": inv2})
    assert state_of(serial(10)) == "dispatched"


@test("challan_serial carries the true per-module wattage, not the average")
def t_challan_serial_wattage_exact():
    c = setup()
    b1 = packed_box(c, [0, 1], watt=WATT, model=MODEL)
    b2 = packed_box(c, [0], watt=OTHER_WATT, model=OTHER_MODEL)
    inv = make_invoice(qty=3, model=None)
    r = c.post("/api/challan", json={"action": "create",
                                     "boxes": [b1, b2], "invoice_id": inv})
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT serial, wattage FROM challan_serial "
                               "WHERE challan_id=%s", (r.get_json()["challan_id"],))
    got = {row["serial"]: row["wattage"] for row in rows}
    assert got[serial(0, OTHER_WATT)] == OTHER_WATT, got


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
