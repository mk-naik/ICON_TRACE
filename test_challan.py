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
import auth_test_helper as AUTH

_results = []

# Round 34: cancelling an issued challan is now Admin/Super Admin + a TOTP
# step-up. setup() provisions the Super Admin account's secret into this, and
# _cancel_body() attaches a fresh code so the tests below still exercise the
# unchanged refusal RULES (issued-only, no referencing gate pass) through the
# new gate.
_TOTP_SECRET = None


def _cancel_body(extra=None):
    """A cancel request that passes every gate: a fresh authenticator code and
    - since the reason became mandatory, never defaulted - a reason."""
    b = dict(extra or {})
    b.setdefault("reason", "test cancellation")
    b["totp_code"] = AUTH.totp_code(_TOTP_SECRET)
    return b


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
    c = APP.app.test_client()
    info = AUTH.test_login(c)   # a real Super Admin session (Round 23)
    global _TOTP_SECRET
    _TOTP_SECRET = AUTH.provision_totp(info["login_id"])   # Round 34 step-up
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
    assert "already on" in r2.get_json()["why"], r2.get_json()


@test("no invoice selected: the box list is empty, not the full "
     "unfiltered list")
def t_boxes_empty_without_invoice():
    c = setup()
    packed_box(c, [0, 1], customer=None)          # a real, biddable box
    r = c.get("/api/challan/boxes")
    assert r.status_code == 200
    assert r.get_json() == [], \
        "boxes were offered with no invoice to filter them against"


@test("selecting an invoice shows General Stock and that invoice's own "
     "customer - a box owned by a DIFFERENT customer does not appear")
def t_boxes_filtered_by_invoice_customer():
    # realistic and populated: two real closed boxes, one General Stock,
    # one already allocated to a customer the invoice does not belong to
    c = setup()
    general = packed_box(c, [10, 11], customer=None)
    foreign = packed_box(c, [12, 13], customer=BOROSIL_CODE)
    inv = make_invoice(qty=2)                      # buyer resolves to C0001 (AGNI)
    rows = c.get("/api/challan/boxes?invoice_id=%d" % inv).get_json()
    ids = {r["box_id"] for r in rows}
    assert general in ids, "General Stock did not appear"
    assert foreign not in ids, \
        "a box belonging to a different customer was offered anyway"


@test("a box already owned by THIS invoice's own customer appears too")
def t_boxes_include_own_customer():
    c = setup()
    own = packed_box(c, [14, 15], customer="C0001")     # AGNI, same as below
    other = packed_box(c, [16, 17], customer=BOROSIL_CODE)
    inv = make_invoice(qty=2)                            # buyer -> C0001 (AGNI)
    ids = {r["box_id"] for r in
          c.get("/api/challan/boxes?invoice_id=%d" % inv).get_json()}
    assert own in ids, "a box already belonging to the invoice's own buyer was hidden"
    assert other not in ids


@test("switching the invoice re-filters - a box no longer visible under "
     "the old invoice becomes visible under the new one")
def t_boxes_refilter_on_invoice_switch():
    c = setup()
    borosil_box = packed_box(c, [18, 19], customer=BOROSIL_CODE)
    inv_agni = make_invoice(qty=2)                        # -> C0001 AGNI
    with store.conn() as (cx, cur):
        inv_borosil = db.insert_invoice(cur, {
            "buyer_name": "BOROSIL RENEWABLES LIMITED", "buyer_gstin": None,
            "declared_qty": 2, "declared_model": MODEL,
            "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                              datetime.timedelta(days=10)).isoformat(),
            "invoice_no": "INV-BOROSIL", "irn": None,
            "consignee_same_as_buyer": 1},
            "test.pdf", "deadbeefborosil",
            {"fields": {}, "compare_only": {}, "qr": {}}, False, {}, "tester")

    under_agni = {r["box_id"] for r in
                 c.get("/api/challan/boxes?invoice_id=%d" % inv_agni).get_json()}
    assert borosil_box not in under_agni

    under_borosil = {r["box_id"] for r in
                    c.get("/api/challan/boxes?invoice_id=%d" % inv_borosil).get_json()}
    assert borosil_box in under_borosil, \
        "switching invoices did not re-filter to the new buyer's own boxes"


@test("a box on a live challan is excluded from the available list")
def t_box_excluded_from_list():
    c = setup()
    b = packed_box(c, [0, 1])
    inv = make_invoice(qty=2)
    before = {r["box_id"] for r in
             c.get("/api/challan/boxes?invoice_id=%d" % inv).get_json()}
    assert b in before
    c.post("/api/challan", json={"action": "create", "boxes": [b],
                                 "invoice_id": inv})
    after = {r["box_id"] for r in
            c.get("/api/challan/boxes?invoice_id=%d" % inv).get_json()}
    assert b not in after, "a taken box still offered itself for selection"


@test("a serial already on a historical challan (last February, say) "
     "blocks a new one - checked against the whole database, not assumed")
def t_dup_serial_against_history():
    # Simulates an old document loaded straight into challan_serial - the
    # historical importer's own path - where the serial's own state was
    # never advanced. This is real data, not a live "on_challan" box flag:
    # the point of the rule is that it checks the master table itself.
    c = setup()
    b = packed_box(c, [0, 1])
    with store.conn() as (cx, cur):
        old_chid = store.insert(cur, "challan", {
            "fy": 2024, "seq": 88, "challan_date": "2025-02-14", "qty": 1,
            "status": "issued", "created_by": "historical-import"})
        store.insert(cur, "challan_serial", {
            "challan_id": old_chid, "serial": serial(0), "build_instance": 1,
            "format_version": 2, "date_produced": "2026-09-09", "shift": 1,
            "sequence": 0, "wattage": WATT})
    inv = make_invoice(qty=2)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 400, "a serial dispatched last February shipped again"
    why = r.get_json()["why"]
    assert serial(0) in why, why
    assert "14.02.2025" in why or "2025" in why, why


@test("the same serial ticked via two different boxes at once is refused, "
     "not assumed impossible")
def t_dup_serial_within_ticket():
    # serial_in_live_box() should make this impossible through the normal
    # API - but repack has already shown box_serial can end up holding a
    # serial under more than one box_id, so this is checked directly rather
    # than trusted as a structural given.
    c = setup()
    b1 = packed_box(c, [0])
    b2 = packed_box(c, [1])
    with store.conn() as (cx, cur):
        # simulate the anomaly directly: b2 also claims b1's serial
        store.insert(cur, "box_serial", {"box_id": b2, "serial": serial(0),
                                         "build_instance": 1,
                                         "added_by": "anomaly"})
    inv = make_invoice(qty=3)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b1, b2],
                                     "invoice_id": inv})
    assert r.status_code == 400, "one serial rode on two boxes in one challan"
    assert serial(0) in r.get_json()["why"], r.get_json()


@test("clean boxes are never falsely flagged for a duplicate serial")
def t_dup_serial_clean_case():
    c = setup()
    b = packed_box(c, [0, 1])
    inv = make_invoice(qty=2)
    r = c.post("/api/challan/checks", json={"boxes": [b], "invoice_id": inv})
    d = r.get_json()
    assert not any(x["code"] == "E-DUPSERIAL" for x in d["blocking"]), d
    assert d["ok"], d


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
    assert "already on" in r2.get_json()["why"], r2.get_json()


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


@test("submitting a draft answers with the quantity it dispatched, like Create - "
      "the screen said 'undefined serial(s) now dispatched' from a body without it")
def t_submit_answers_qty():
    c = setup()
    b = packed_box(c, [0, 1, 2])
    inv = make_invoice(qty=3)
    chid = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                        "invoice_id": inv}).get_json()["challan_id"]
    d = c.post("/api/challan/%d/submit" % chid, json={}).get_json()
    assert d["ok"] and d["qty"] == 3, d
    assert "kw" in d and d.get("suffix") is None, d


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
    ids = {row["box_id"] for row in
          c.get("/api/challan/boxes?invoice_id=%d" % inv).get_json()}
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


@test("the Create Challan picker reaches an invoice older than the newest 100 "
      "(the 'already on a live challan' filter runs before the limit; audit 9 Oct)")
def t_picker_reaches_old_invoice():
    c = setup()
    old = make_invoice(qty=2, invoice_no="INV-OLD-WAITING")
    for k in range(101):
        iid = make_invoice(qty=1, invoice_no="INV-HELD-%03d" % k)
        with store.conn() as (cx, cur):
            store.insert(cur, "challan", {"fy": 2026, "seq": 1000 + k,
                "challan_date": "2026-09-09", "qty": 1, "status": "issued",
                "invoice_id": iid, "created_by": "t"})
    ids = [i["id"] for i in
           c.get("/api/invoices?for_challan=1").get_json()["invoices"]]
    assert old in ids, "an unclaimed invoice behind 100 claimed ones was dropped"
    assert len(ids) == 1, ids


@test("the invoice list names the LIVE challans against an invoice by number - "
      "a cancelled or superseded one is not listed (audit 9 Oct)")
def t_invoice_list_names_live_challans():
    c = setup()
    b1 = packed_box(c, [160, 161])
    b2 = packed_box(c, [162, 163])
    inv = make_invoice(qty=2, invoice_no="INV-LISTCOL")

    def col():
        return [i for i in c.get("/api/invoices").get_json()["invoices"]
                if i["id"] == inv][0]["challan"]
    chid = make_issued_challan(c, [b1], inv)
    no = c.get("/api/challan/%d" % chid).get_json()["challan"]["challan_no"]
    assert col() == no, (col(), no)
    r = c.post("/api/challan/%d/edit-save" % chid, json={"boxes": [b2], "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    assert col() == r.get_json()["no"], col()
    r = c.post("/api/challan/%d/cancel" % r.get_json()["challan_id"],
               json=_cancel_body())
    assert r.status_code == 200, r.get_json()
    assert col() is None, col()


@test("simultaneous drafts never share a number, and a pallet ticked on two "
      "at once goes on only one of them (audit 9 Oct: six at once took 11, 11, "
      "12, 12, 13, 14)")
def t_concurrent_drafts():
    import threading
    c = setup()
    pals = [packed_box(c, [200 + 2 * k, 201 + 2 * k]) for k in range(8)]
    shared = packed_box(c, [240, 241])
    invs = [make_invoice(qty=2, invoice_no="INV-RACE-%d" % k) for k in range(10)]
    clients = []
    for k in range(10):
        ck = APP.app.test_client()
        AUTH.test_login(ck, login_id="race.%d" % k)
        clients.append(ck)
    out = []

    def draft(k, boxes):
        r = clients[k].post("/api/challan", json={
            "action": "draft", "boxes": boxes, "invoice_id": invs[k]})
        out.append((r.status_code, r.get_json()))

    def all_at_once(jobs):
        del out[:]
        th = [threading.Thread(target=draft, args=j) for j in jobs]
        for t in th:
            t.start()
        for t in th:
            t.join()
    for _round in range(3):
        all_at_once([(k, [pals[k]]) for k in range(8)])
        seqs = [d["seq"] for st, d in out if st == 200]
        assert len(seqs) == 8 and len(set(seqs)) == 8, sorted(seqs)
        for st, d in out:
            c.post("/api/challan/%d/discard" % d["challan_id"], json={})
    all_at_once([(8, [shared]), (9, [shared])])
    assert sorted(st for st, _ in out) == [200, 400], out


@test("a SUPERSEDED challan cannot be discarded: it stays superseded, never "
      "rewritten 'cancelled' (audit 9 Oct)")
def t_discard_refuses_superseded():
    c = setup()
    b1 = packed_box(c, [140, 141])
    b2 = packed_box(c, [142, 143])
    inv = make_invoice(qty=2, invoice_no="INV-DISCSUP")
    chid = make_issued_challan(c, [b1], inv)
    r = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b2], "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    r2 = c.post("/api/challan/%d/discard" % chid, json={})
    assert r2.status_code == 400, r2.get_json()
    row = challan_row(chid)
    assert row["status"] == "superseded", row["status"]
    assert row["cancelled_reason"] is None, row["cancelled_reason"]


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


@test("an invoice whose buyer is not in the customer master takes General "
      "Stock only - another customer's pallet is refused, as it is never "
      "offered (audit 9 Oct)")
def t_unknown_buyer_refuses_owned_pallet():
    c = setup()
    owned = packed_box(c, [250, 251], customer=BOROSIL_CODE)
    stock = packed_box(c, [252, 253], customer=None)
    inv = make_invoice(qty=2, buyer_name="SOME BRAND NEW COMPANY LTD",
                       buyer_gstin="99ZZZZZ9999Z1Z9", invoice_no="INV-UNKNOWN-B")
    offered = [b["box_id"] for b in
               c.get("/api/challan/boxes?invoice_id=%d" % inv).get_json()]
    assert stock in offered and owned not in offered, offered
    r = c.post("/api/challan", json={"action": "create", "boxes": [owned],
                                     "invoice_id": inv})
    assert r.status_code == 400 and "customer master" in r.get_json()["why"], r.get_json()
    assert challan_row_count() == 0
    r = c.post("/api/challan", json={"action": "create", "boxes": [stock],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()


@test("a challan date that is not a date is refused with its reason, on "
      "create and on an edit - not a 500, and no number is used up (audit 9 Oct)")
def t_bad_challan_date_refused():
    c = setup()
    b1 = packed_box(c, [260, 261])
    b2 = packed_box(c, [262, 263])
    inv = make_invoice(qty=2, invoice_no="INV-BADDATE")
    r = c.post("/api/challan", json={"action": "draft", "boxes": [b1],
                                     "invoice_id": inv, "challan_date": "31/12/2026"})
    assert r.status_code == 400 and "not a date" in r.get_json()["why"], r.get_json()
    assert challan_row_count() == 0
    chid = make_issued_challan(c, [b1], inv)
    seq = challan_row(chid)["seq"]
    assert seq == 1, "the refused draft used up a number: %s" % seq
    r = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b2], "invoice_id": inv, "challan_date": "tomorrow"})
    assert r.status_code == 400 and "not a date" in r.get_json()["why"], r.get_json()
    assert challan_row(chid)["status"] == "issued"


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



# --------------------------------------------------------------------------
# lifecycle: cancel issued, gate pass lock, edit, invoice/box exclusion
# --------------------------------------------------------------------------

def make_issued_challan(c, box_ids, invoice_id):
    """Create + immediately submit a challan so it is in status='issued'."""
    # Save as draft, then submit so we test the full flow
    r = c.post("/api/challan", json={"action": "create",
                                     "boxes": box_ids,
                                     "invoice_id": invoice_id})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["challan_id"]


def add_gatepass(c, challan_id):
    """Create a gate pass referencing the given challan_id."""
    with store.conn() as (cx, cur):
        import datetime as _dt
        d = _dt.date.today()
        seq = db.draw_gp_seq(cur, d)
        no = db.render_gp_no(d, seq)
        rec = {"gp_no": no, "gp_date": d.isoformat(), "kind": "NRGP",
               "party": "Test", "challan_no": "IS-TEST/0001",
               "challan_id": challan_id}
        db.create_gatepass(cur, rec, "test")
        return no


@test("a challan already referenced by a gate pass cannot be cancelled")
def t_gp_blocks_cancel():
    c = setup()
    b = packed_box(c, [20, 21])
    inv = make_invoice(qty=2, invoice_no="INV-GPCAN")
    chid = make_issued_challan(c, [b], inv)
    add_gatepass(c, chid)
    r = c.post("/api/challan/%d/cancel" % chid, json=_cancel_body())
    assert r.status_code == 400, "cancelled despite gate pass reference"
    assert "gate pass" in r.get_json()["why"].lower(), r.get_json()
    # Challan must still be issued
    assert challan_row(chid)["status"] == "issued"


@test("a challan already referenced by a gate pass cannot be edited "
      "(cancel step is blocked, so no new draft is created)")
def t_gp_blocks_edit():
    c = setup()
    b = packed_box(c, [22, 23])
    inv = make_invoice(qty=2, invoice_no="INV-GPEDIT")
    chid = make_issued_challan(c, [b], inv)
    add_gatepass(c, chid)
    # The edit path would first call /cancel - that must be blocked
    r = c.post("/api/challan/%d/cancel" % chid,
               json=_cancel_body({"reason": "cancelled for edit by operator"}))
    assert r.status_code == 400, "edit-cancel succeeded despite gate pass"
    assert challan_row(chid)["status"] == "issued"


@test("a CANCELLED gate pass no longer shows the challan locked: the list and "
      "the detail panel count live gate passes, as edit and cancel do (audit 9 Oct)")
def t_cancelled_gp_unlocks_list_and_detail():
    c = setup()
    b = packed_box(c, [150, 151])
    inv = make_invoice(qty=2, invoice_no="INV-GPUNLOCK")
    chid = make_issued_challan(c, [b], inv)
    gp_no = add_gatepass(c, chid)

    def shown():
        det = c.get("/api/challan/%d" % chid).get_json()
        row = [r for r in c.get("/api/challans").get_json()["challans"]
               if r["challan_id"] == chid][0]
        return det["challan"]["locked"], det["gp_count"], row["gp_count"]
    assert shown() == (True, 1, 1), shown()
    with store.conn() as (cx, cur):
        cur.execute("UPDATE gatepass SET status='cancelled' WHERE gp_no=%s",
                    (gp_no,))
    assert shown() == (False, 0, 0), shown()
    r = c.post("/api/challan/%d/edit-draft" % chid, json={})
    assert r.status_code == 200, r.get_json()


@test("cancelling an issued challan reverts every serial to packed, not dispatched")
def t_cancel_reverts_serials():
    c = setup()
    idx = [30, 31, 32]
    b = packed_box(c, idx)
    inv = make_invoice(qty=3, invoice_no="INV-CANCEL")
    chid = make_issued_challan(c, [b], inv)
    # Serials are dispatched after create
    for i in idx:
        assert state_of(serial(i)) == "dispatched", \
            "serial %s not dispatched" % serial(i)
    r = c.post("/api/challan/%d/cancel" % chid, json=_cancel_body())
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["ok"]
    # Must revert to packed, never stuck at dispatched
    for i in idx:
        assert state_of(serial(i)) == "packed", \
            "serial %s still dispatched after cancel" % serial(i)


@test("a cancelled challan's boxes reappear in the repack list after cancel")
def t_cancel_frees_boxes():
    c = setup()
    b = packed_box(c, [40, 41])
    inv = make_invoice(qty=2, invoice_no="INV-REPK")
    chid = make_issued_challan(c, [b], inv)
    # Before cancel — box is on a live challan, excluded from repack
    r = c.get("/api/boxes?state=closed&exclude_live_challan=1")
    ids_before = [x["box_id"] for x in r.get_json()]
    assert b not in ids_before, "box still in repack list while challan live"
    # Cancel
    c.post("/api/challan/%d/cancel" % chid, json=_cancel_body())
    # After cancel — box should reappear
    r2 = c.get("/api/boxes?state=closed&exclude_live_challan=1")
    ids_after = [x["box_id"] for x in r2.get_json()]
    assert b in ids_after, "box still absent from repack list after challan cancelled"


@test("a cancelled challan's invoice reappears in the for-challan invoice selector")
def t_cancel_frees_invoice():
    c = setup()
    b = packed_box(c, [50, 51])
    inv = make_invoice(qty=2, invoice_no="INV-FREEINV")
    chid = make_issued_challan(c, [b], inv)
    # Before cancel — invoice should be excluded from for_challan list
    r = c.get("/api/invoices?for_challan=1")
    ids_before = [x["id"] for x in r.get_json()["invoices"]]
    assert inv not in ids_before, "invoice visible in selector while challan live"
    # Cancel
    c.post("/api/challan/%d/cancel" % chid, json=_cancel_body())
    # After cancel — invoice must reappear
    r2 = c.get("/api/invoices?for_challan=1")
    ids_after = [x["id"] for x in r2.get_json()["invoices"]]
    assert inv in ids_after, "invoice still hidden from selector after challan cancelled"


@test("an invoice on a live challan does not appear in the for-challan invoice selector")
def t_live_invoice_hidden():
    c = setup()
    b = packed_box(c, [60, 61])
    inv = make_invoice(qty=2, invoice_no="INV-HIDEME")
    make_issued_challan(c, [b], inv)
    r = c.get("/api/invoices?for_challan=1")
    ids = [x["id"] for x in r.get_json()["invoices"]]
    assert inv not in ids, "invoice on live challan visible in create-challan selector"


@test("a box on a live DRAFT challan is absent from the repack list, not merely locked")
def t_draft_box_absent_from_repack():
    c = setup()
    b = packed_box(c, [70, 71])
    inv = make_invoice(qty=2, invoice_no="INV-DRAFTREPACK")
    # Save as draft (not issued)
    r = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    r2 = c.get("/api/boxes?state=closed&exclude_live_challan=1")
    ids = [x["box_id"] for x in r2.get_json()]
    assert b not in ids, \
        "box on live draft challan still appears in repack list (should be absent)"


@test("a box on a live ISSUED challan is absent from the repack list, not merely locked")
def t_issued_box_absent_from_repack():
    c = setup()
    b = packed_box(c, [80, 81])
    inv = make_invoice(qty=2, invoice_no="INV-ISSUEDREPACK")
    make_issued_challan(c, [b], inv)
    r = c.get("/api/boxes?state=closed&exclude_live_challan=1")
    ids = [x["box_id"] for x in r.get_json()]
    assert b not in ids, \
        "box on issued challan still appears in repack list (should be absent)"


@test("a second gate pass can be created against a challan that already has one "
      "(split load — no 1:1 enforcement)")
def t_split_load_second_gp():
    c = setup()
    b = packed_box(c, [90, 91])
    inv = make_invoice(qty=2, invoice_no="INV-SPLIT")
    chid = make_issued_challan(c, [b], inv)
    gp1 = add_gatepass(c, chid)
    # First gate pass must lock editing via the cancel endpoint
    r_cancel = c.post("/api/challan/%d/cancel" % chid, json=_cancel_body())
    assert r_cancel.status_code == 400, "first gp did not lock the challan"
    assert "gate pass" in r_cancel.get_json()["why"].lower(), r_cancel.get_json()
    # But a SECOND gate pass must be allowed — no 1:1 constraint
    gp2 = add_gatepass(c, chid)
    assert gp2 != gp1, "second gate pass not issued"
    with store.conn() as (cx, cur):
        cnt = db.gp_count_for_challan(cur, chid)
    assert cnt == 2, "expected 2 gate passes, got %d" % cnt



# --------------------------------------------------------------------------
# Edit: reserve without touching, save creates a new (fy, seq) generation
# --------------------------------------------------------------------------

@test("edit-draft writes nothing - the original is unaffected and its "
     "boxes are selectable elsewhere the instant nothing is saved")
def t_edit_draft_touches_nothing():
    c = setup()
    b = packed_box(c, [100, 101])
    inv = make_invoice(qty=2, invoice_no="INV-EDITDRAFT")
    chid = make_issued_challan(c, [b], inv)
    before = dict(challan_row(chid))

    r = c.post("/api/challan/%d/edit-draft" % chid, json={})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["boxes"] == [b], d["boxes"]
    assert d["invoice_id"] == inv

    # nothing changed - not even a timestamp
    after = dict(challan_row(chid))
    assert after == before, "edit-draft wrote something to the original"

    # "navigating away without saving" - simulated by simply never calling
    # edit-save. The box must be selectable on a brand new challan.
    inv2 = make_invoice(qty=2, invoice_no="INV-EDITDRAFT-2")
    r2 = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                      "invoice_id": inv2})
    assert r2.status_code == 400, \
        "an abandoned edit-draft left the box reserved to nobody real"
    assert "already on" in r2.get_json()["why"], r2.get_json()
    # it is still exactly on the ORIGINAL, untouched challan
    assert dict(challan_row(chid))["status"] == "issued"


@test("saving a real change produces suffix MA at the same (fy, seq); the "
     "original is 'superseded', never 'cancelled'")
def t_edit_save_creates_ma():
    c = setup()
    b1 = packed_box(c, [102, 103])
    b2 = packed_box(c, [104, 105])            # same size - swap, not add
    inv = make_invoice(qty=2, invoice_no="INV-EDITMA")
    chid = make_issued_challan(c, [b1], inv)
    orig = dict(challan_row(chid))

    r = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b2], "invoice_id": inv,
                     "vehicle_no": "CG04ZZ9999"})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["suffix"] == "MA", d
    assert d["fy"] == orig["fy"] and d["seq"] == orig["seq"], d
    assert d["status"] == "issued"

    row = dict(challan_row(chid))
    assert row["status"] == "superseded", row["status"]
    assert row["superseded_by"] == d["challan_id"]
    assert row["superseded_at"], "no timestamp recorded"
    assert row["superseded_by_user"], "no actor recorded"

    new_row = dict(challan_row(d["challan_id"]))
    assert new_row["vehicle_no"] == "CG04ZZ9999"
    assert new_row["fy"] == orig["fy"] and new_row["seq"] == orig["seq"]
    assert new_row["suffix"] == "MA"


@test("a pallet an EDIT took off is free again: offered to the next challan, "
      "accepted on it, counted once on Stock & Dispatch, and its journey no "
      "longer says it is on the superseded original (6 Oct)")
def t_edit_frees_the_pallet_it_removed():
    c = setup()
    b1 = packed_box(c, [102, 103])
    b2 = packed_box(c, [104, 105])
    inv = make_invoice(qty=2, invoice_no="INV-EDIT-FREE")
    chid = make_issued_challan(c, [b1], inv)
    r = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b2], "invoice_id": inv, "vehicle_no": "CG04ZZ1111"})
    assert r.status_code == 200 and r.get_json()["suffix"] == "MA", r.get_json()

    j = c.get("/api/trace/serial/" + serial(102)).get_json()
    step = [x for x in j["journey"] if x["stage"] == "Challan"][0]
    assert not step["done"] and "superseded" in step["detail"][0], step

    inv2 = make_invoice(qty=2, invoice_no="INV-EDIT-FREE-2")
    offered = [b["box_id"] for b in c.get("/api/challan/boxes?invoice_id=%d" % inv2).get_json()]
    assert b1 in offered and b2 not in offered, offered
    r2 = c.post("/api/challan", json={"action": "create", "boxes": [b1], "invoice_id": inv2})
    assert r2.status_code == 200, r2.get_json()

    sd = c.get("/api/stock_dispatch").get_json()
    assert (sd["open_ch"]["box_count"], sd["open_ch"]["modules"]) == (2, 4), sd["open_ch"]
    assert sd["fg_ready"]["box_count"] == 0, sd["fg_ready"]


@test("Stock & Dispatch gives the period's dispatches per customer and model - "
      "Management Overview's Dispatch & stock table read a hard-coded 0 and the "
      "stock's KW as 'shipped' (audit A6, 10 Oct)")
def t_stock_dispatch_by_customer_model():
    c = setup()
    b1 = packed_box(c, [120, 121])
    b2 = packed_box(c, [122, 123])
    b3 = packed_box(c, [124, 125, 126])                    # stays in stock
    make_issued_challan(c, [b1, b2], make_invoice(qty=4, invoice_no="INV-DISPBY"))
    day = __import__("icon_clock").shift_day().isoformat()
    sd = c.get("/api/stock_dispatch?from=%s&to=%s" % (day, day)).get_json()
    by = [(r["model"], r["modules"], round(r["kw"], 3)) for r in sd["disp_by"]]
    assert by == [(MODEL, 4, round(4 * WATT / 1000.0, 3))], sd["disp_by"]
    assert "AGNI" in sd["disp_by"][0]["customer_name"].upper(), sd["disp_by"]
    assert sum(r["modules"] for r in sd["disp_by"]) == sd["disp_today"]["modules"]
    assert [(r["modules"], r["box_count"]) for r in sd["table_fg"]] == [(3, 1)], sd["table_fg"]
    other = c.get("/api/stock_dispatch?from=2020-01-01&to=2020-01-02").get_json()
    assert other["disp_by"] == [], "a period with no dispatch lists none"


@test("the Challan list's Status dropdown offers the statuses on file under the "
      "search - Superseded included, which it never offered (6 Oct)")
def t_challan_list_status_facet():
    c = setup()
    b1 = packed_box(c, [102, 103])
    b2 = packed_box(c, [104, 105])
    inv = make_invoice(qty=2, invoice_no="INV-FACET")
    chid = make_issued_challan(c, [b1], inv)
    c.post("/api/challan/%d/edit-save" % chid,
           json={"boxes": [b2], "invoice_id": inv, "vehicle_no": "CG04ZZ2222"})
    d = c.get("/api/challans").get_json()
    assert d["facets"]["status"] == ["issued", "superseded"], d["facets"]
    one = c.get("/api/challans?status=issued").get_json()
    assert len(one["challans"]) == 1 and one["facets"]["status"] == ["issued", "superseded"], one
    none = c.get("/api/challans?q=NOBODY-AT-ALL").get_json()
    assert none["challans"] == [] and none["facets"]["status"] == [], none["facets"]


@test("printing a superseded challan by its BARE number (no suffix) is "
     "refused, not silently served as the stale original")
def t_edit_print_refuses_superseded_bare_number():
    # _challan_bundle's "no suffix given" match is `suffix IS NULL`, which
    # is exactly the ORIGINAL row once it has been superseded - a caller
    # with the old number (no suffix) must not silently get back the
    # document Edit corrected away from.
    c = setup()
    b1 = packed_box(c, [130, 131])
    b2 = packed_box(c, [132, 133])
    inv = make_invoice(qty=2, invoice_no="INV-PRINTSTALE")
    chid = make_issued_challan(c, [b1], inv)
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT fy, seq FROM challan WHERE challan_id=%s",
                        (chid,))
    fy, seq = row["fy"], row["seq"]

    r = c.post("/api/challan/%d/edit-save" % chid,
              json={"boxes": [b2], "invoice_id": inv})
    assert r.status_code == 200, r.get_json()

    pr = c.get("/challan/%d/%d/print" % (fy, seq))
    assert pr.status_code == 400, \
        "the superseded original printed under its bare number"
    assert "superseded" in pr.get_data(as_text=True).lower(), \
        pr.get_data(as_text=True)
    assert "MA" in pr.get_data(as_text=True), \
        "the refusal did not name the replacement"

    ex = c.get("/challan/%d/%d/excel" % (fy, seq))
    assert ex.status_code == 400, "the superseded original exported anyway"

    # explicitly asking for the live one, by its own suffix, is not turned
    # away for being superseded - test_loading.py covers the separate
    # loading-verification gate that still applies to it
    pr2 = c.get("/challan/%d/%d/print?suffix=MA" % (fy, seq))
    assert "superseded" not in pr2.get_data(as_text=True).lower(), \
        pr2.get_data(as_text=True)


@test("a second edit on MA produces MB; the original two generations back "
     "cannot be edited at all")
def t_edit_second_generation_mb():
    c = setup()
    b = packed_box(c, [105, 106])
    inv = make_invoice(qty=2, invoice_no="INV-EDITMB")
    chid = make_issued_challan(c, [b], inv)

    r1 = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b], "invoice_id": inv,
                     "vehicle_no": "CG04MA0001"})
    ma_id = r1.get_json()["challan_id"]
    assert r1.get_json()["suffix"] == "MA"

    r2 = c.post("/api/challan/%d/edit-save" % ma_id,
               json={"boxes": [b], "invoice_id": inv,
                     "vehicle_no": "CG04MB0002"})
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()["suffix"] == "MB", r2.get_json()
    mb_id = r2.get_json()["challan_id"]

    assert dict(challan_row(chid))["status"] == "superseded"
    assert dict(challan_row(ma_id))["status"] == "superseded"
    assert dict(challan_row(mb_id))["status"] == "issued"

    # the original, two generations back, cannot be edited - not even a draft
    r3 = c.post("/api/challan/%d/edit-draft" % chid, json={})
    assert r3.status_code == 400, "a two-generations-back challan was editable"
    assert "superseded" in r3.get_json()["why"].lower(), r3.get_json()
    # nor can the intermediate MA generation
    r4 = c.post("/api/challan/%d/edit-draft" % ma_id, json={})
    assert r4.status_code == 400, "the intermediate generation was editable"


@test("the live verification rail on a SECOND edit excludes the WHOLE "
     "lineage, not just the challan being edited - the original's "
     "challan_serial rows are still there under its own, different id")
def t_checks_excludes_whole_lineage_on_second_edit():
    c = setup()
    b = packed_box(c, [119, 120])
    inv = make_invoice(qty=2, invoice_no="INV-CHECKSLINEAGE")
    chid = make_issued_challan(c, [b], inv)

    r1 = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b], "invoice_id": inv,
                     "vehicle_no": "CG04MA0003"})
    ma_id = r1.get_json()["challan_id"]

    # what the client sends while a SECOND edit (of ma_id) is open: only
    # ma_id itself, exactly what chEditingId holds - the rail has to widen
    # this to the lineage on its own, the same way edit-save already does
    r = c.post("/api/challan/checks",
               json={"boxes": [b], "invoice_id": inv,
                     "exclude_challan_id": ma_id})
    assert r.status_code == 200, r.get_json()
    chk = r.get_json()
    codes = [i["code"] for box in chk["boxes"] for i in box["issues"]]
    assert "E-DUPSERIAL" not in codes, \
        "the rail warned about the box's own prior generation: " + str(chk)
    assert chk["ok"], chk

    # confirms the rail was not just permissive by accident: the SAME
    # save the client is building towards actually succeeds
    r2 = c.post("/api/challan/%d/edit-save" % ma_id,
               json={"boxes": [b], "invoice_id": inv,
                     "vehicle_no": "CG04MB0004"})
    assert r2.status_code == 200, r2.get_json()


@test("the invoice cannot be changed through an edit, submitted or not")
def t_edit_invoice_locked():
    c = setup()
    b = packed_box(c, [107, 108])
    inv1 = make_invoice(qty=2, invoice_no="INV-LOCK1")
    inv2 = make_invoice(qty=2, invoice_no="INV-LOCK2")
    chid = make_issued_challan(c, [b], inv1)

    r = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b], "invoice_id": inv2})
    assert r.status_code == 400
    assert "invoice" in r.get_json()["why"].lower(), r.get_json()
    assert dict(challan_row(chid))["status"] == "issued", \
        "the original was superseded despite the invoice-change refusal"

    # omitting invoice_id entirely does not let it drift either - the
    # server decides the value, never the client
    with store.conn() as (cx, cur):
        cur.execute("UPDATE invoice SET declared_qty=2 WHERE invoice_id=%s",
                    (inv2,))
    # (with a real change: a save in which nothing changed writes no new row,
    # so it would not show where the server took the invoice from)
    r2 = c.post("/api/challan/%d/edit-save" % chid,
                json={"boxes": [b], "driver_name": "Suresh"})
    assert r2.status_code == 200, r2.get_json()
    assert dict(challan_row(r2.get_json()["challan_id"]))["invoice_id"] == inv1


@test("vehicle, driver, transporter, LR number and the box selection can "
     "all be changed through an edit")
def t_edit_everything_else_changeable():
    c = setup()
    b1 = packed_box(c, [109, 110])
    b2 = packed_box(c, [111, 112])            # same size - swap, not add
    inv = make_invoice(qty=2, invoice_no="INV-EDITALL")
    chid = make_issued_challan(c, [b1], inv)

    r = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b2], "invoice_id": inv,
                     "vehicle_no": "CG04NEW001", "transporter": "New Transport Co",
                     "lr_no": "LR-9999", "driver_name": "Ramesh",
                     "driver_mobile": "9998887776"})
    assert r.status_code == 200, r.get_json()
    new_row = dict(challan_row(r.get_json()["challan_id"]))
    assert new_row["vehicle_no"] == "CG04NEW001"
    assert new_row["transporter"] == "New Transport Co"
    assert new_row["lr_no"] == "LR-9999"
    assert new_row["driver_name"] == "Ramesh"
    assert new_row["driver_mobile"] == "9998887776"
    # the box selection really did change: b1's modules go back to packed,
    # b2's are now dispatched under the new challan
    assert state_of(serial(109)) == "packed", \
        "a box dropped from the edit was not released"
    assert state_of(serial(111)) == "dispatched"
    with store.conn() as (cx, cur):
        serials2 = {r2["serial"] for r2 in store.rows(
            cur, "SELECT serial FROM challan_serial WHERE challan_id=%s",
            (r.get_json()["challan_id"],))}
    assert serial(111) in serials2 and serial(109) not in serials2


@test("a challan already locked by a gate pass cannot be edited, exactly "
     "as it already cannot be cancelled")
def t_edit_locked_by_gatepass():
    c = setup()
    b = packed_box(c, [112, 113])
    inv = make_invoice(qty=2, invoice_no="INV-EDITGP")
    chid = make_issued_challan(c, [b], inv)
    add_gatepass(c, chid)

    r1 = c.post("/api/challan/%d/edit-draft" % chid, json={})
    assert r1.status_code == 400
    assert "locked" in r1.get_json()["why"].lower(), r1.get_json()

    r2 = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b], "invoice_id": inv})
    assert r2.status_code == 400
    assert "locked" in r2.get_json()["why"].lower(), r2.get_json()
    assert dict(challan_row(chid))["status"] == "issued"


@test("editing a challan whose boxes have real box_no values resolves "
     "them to the correct box_id server-side, and save succeeds")
def t_edit_resolves_box_no_to_box_id():
    # This is the exact case that broke before: challan_box has no
    # box_serial column at all (box_no + challan_box_id are the real
    # ones), so reading d.boxes[i].box_serial was always undefined and
    # every pre-filled tick was "BAD box id". edit-draft must resolve the
    # PRINTED LABEL back to a real box_id itself.
    c = setup()
    b = packed_box(c, [114, 115, 116])
    inv = make_invoice(qty=3, invoice_no="INV-BOXNO")
    chid = make_issued_challan(c, [b], inv)

    with store.conn() as (cx, cur):
        cb = store.one(cur, "SELECT box_no, challan_box_id FROM challan_box "
                            "WHERE challan_id=%s", (chid,))
    assert cb["box_no"], "fixture assumption broke: no box_no recorded"
    assert not hasattr(cb, "box_serial"), \
        "challan_box unexpectedly has a box_serial column"

    r = c.post("/api/challan/%d/edit-draft" % chid, json={})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["boxes"] == [b], \
        "box_no %r did not resolve to the real box_id %r: got %r" % \
        (cb["box_no"], b, d["boxes"])

    # (the pre-filled ticks are accepted as they came; a driver change makes it
    # a real save - an untouched one writes nothing, tested below)
    r2 = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": d["boxes"], "invoice_id": inv,
                     "driver_mobile": "9000000001"})
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()["qty"] == 3 and r2.get_json()["changed"] is True


@test("editing a draft or a cancelled challan is refused, not just a "
     "superseded one")
def t_edit_refused_for_non_issued():
    c = setup()
    b = packed_box(c, [117, 118])
    inv = make_invoice(qty=2, invoice_no="INV-EDITDRAFTSTATE")
    r0 = c.post("/api/challan", json={"action": "draft", "boxes": [b],
                                      "invoice_id": inv})
    draft_id = r0.get_json()["challan_id"]
    r1 = c.post("/api/challan/%d/edit-draft" % draft_id, json={})
    assert r1.status_code == 400
    assert "issued" in r1.get_json()["why"].lower(), r1.get_json()

    c.post("/api/challan/%d/discard" % draft_id, json={})
    r2 = c.post("/api/challan/%d/edit-draft" % draft_id, json={})
    assert r2.status_code == 400


@test("edit-save itself refuses on a non-issued challan, not just edit-draft")
def t_edit_save_refuses_non_issued():
    c = setup()
    b = packed_box(c, [119, 120])
    inv = make_invoice(qty=2, invoice_no="INV-EDITSAVESTATE")
    chid = make_issued_challan(c, [b], inv)

    r1 = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b], "invoice_id": inv,
                     "vehicle_no": "CG04FIRST01"})
    assert r1.status_code == 200, r1.get_json()
    ma_id = r1.get_json()["challan_id"]
    assert ma_id != chid, "the first edit wrote no new version"

    # chid is now 'superseded' - saving against it again must be refused,
    # by edit-save itself, independent of whatever edit-draft would say
    r2 = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b], "invoice_id": inv,
                     "vehicle_no": "SHOULD-NOT-LAND"})
    assert r2.status_code == 400, \
        "edit-save wrote a second edit against an already-superseded row"
    assert "issued" in r2.get_json()["why"].lower(), r2.get_json()
    # and nothing was written: no third generation, MA is still the live one
    assert dict(challan_row(chid))["superseded_by"] == ma_id
    assert dict(challan_row(ma_id))["status"] == "issued"
    assert dict(challan_row(ma_id))["vehicle_no"] != "SHOULD-NOT-LAND"


# --------------------------------------------------------------------------
# An edit in which nothing changed is not an edit
# --------------------------------------------------------------------------

def edit_payload(c, chid, **over):
    """What the Edit screen posts for a form nobody touched: every value
    edit-draft hands it, in the shapes chPayload() sends them (an empty field is
    '', the consignee is one text of name and address). `over` is what the
    person changed."""
    d = c.post("/api/challan/%d/edit-draft" % chid, json={}).get_json()
    assert d["ok"], d
    body = {"boxes": d["boxes"], "invoice_id": d["invoice_id"],
            "challan_date": d["challan_date"],
            "buyer_name": d["buyer_name"] or "",
            "buyer_gstin": d["buyer_gstin"] or "",
            "consignee_same_as_buyer": d["consignee_same_as_buyer"],
            "consignee_name": d["consignee_name"] or "",
            "consignee_address": d["consignee_address"] or "",
            "vehicle_no": d["vehicle_no"] or "",
            "transporter": d["transporter"] or "", "lr_no": d["lr_no"] or "",
            "driver_name": d["driver_name"] or "",
            "driver_mobile": d["driver_mobile"] or ""}
    body.update(over)
    return body


def all_challans():
    with store.conn() as (cx, cur):
        return [dict(r) for r in store.rows(
            cur, "SELECT challan_id, suffix, status, superseded_by FROM "
                 "challan ORDER BY challan_id")]


def audit_count(action):
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT COUNT(*) AS n FROM dispatch_audit WHERE "
                              "action=%s", (action,))["n"]


@test("saving an edit in which nothing changed writes nothing: no new version, "
      "the original stays issued, no suffix is used up, nothing is audited - "
      "and the answer says so instead of pretending to have saved")
def t_edit_unchanged_writes_nothing():
    c = setup()
    b1 = packed_box(c, [140, 141])
    b2 = packed_box(c, [142, 143])
    inv = make_invoice(qty=4, invoice_no="INV-NOCHANGE")
    r = c.post("/api/challan", json={
        "action": "create", "boxes": [b1, b2], "invoice_id": inv,
        "buyer_name": AGNI_NAME, "buyer_gstin": AGNI_GSTIN,
        "consignee_same_as_buyer": True, "consignee_name": "",
        "consignee_address": "", "vehicle_no": "CG04AB1234",
        "transporter": "Sharma Transport", "lr_no": "LR-778",
        "driver_name": "Ramesh", "driver_mobile": "9876543210"})
    assert r.status_code == 200, r.get_json()
    chid, no = r.get_json()["challan_id"], r.get_json()["no"]
    before, edits = all_challans(), audit_count("challan.edit")

    r = c.post("/api/challan/%d/edit-save" % chid, json=edit_payload(c, chid))
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["ok"] is True and j["changed"] is False, j
    assert j["challan_id"] == chid and j["no"] == no and j["suffix"] is None, j
    assert "nothing was changed" in j["note"].lower(), j
    assert all_challans() == before, "an unchanged save wrote a challan row"
    assert dict(challan_row(chid))["status"] == "issued"
    assert audit_count("challan.edit") == edits, \
        "an unchanged save was audited as an edit"
    assert state_of(serial(140)) == "dispatched" == state_of(serial(143))

    # no suffix was used up: the next REAL edit is still MA
    r2 = c.post("/api/challan/%d/edit-save" % chid,
                json=edit_payload(c, chid, driver_name="Suresh"))
    assert r2.get_json()["changed"] is True and \
        r2.get_json()["suffix"] == "MA", r2.get_json()
    assert audit_count("challan.edit") == edits + 1


@test("a challan made from nothing but pallets and an invoice is also unchanged "
      "when the screen posts it back - the buyer the screen shows is the "
      "invoice's, which is what was stored")
def t_edit_unchanged_when_buyer_came_from_invoice():
    c = setup()
    b = packed_box(c, [146, 147])
    inv = make_invoice(qty=2, invoice_no="INV-NOCHANGE2")
    chid = make_issued_challan(c, [b], inv)
    body = {"boxes": [b], "invoice_id": inv, "buyer_name": AGNI_NAME,
            "buyer_gstin": AGNI_GSTIN, "consignee_same_as_buyer": True,
            "consignee_name": "", "consignee_address": "",
            "challan_date": challan_row(chid)["challan_date"],
            "vehicle_no": "", "transporter": "", "lr_no": "",
            "driver_name": "", "driver_mobile": ""}
    for post in (body, {"boxes": [b]}, {"boxes": [b], "invoice_id": inv}):
        r = c.post("/api/challan/%d/edit-save" % chid, json=post)
        assert r.status_code == 200 and r.get_json()["changed"] is False, \
            (post, r.get_json())
    assert len(all_challans()) == 1, all_challans()


@test("every field an edit may change makes a new version - and after each, an "
      "untouched save of the new version is again nothing (what the screen "
      "posts back round-trips exactly)")
def t_edit_each_field_is_a_change():
    c = setup()
    b1 = packed_box(c, [148, 149])
    b2 = packed_box(c, [150, 151])
    b3 = packed_box(c, [152, 153])
    inv = make_invoice(qty=4, invoice_no="INV-EACHFIELD")
    live = make_issued_challan(c, [b1, b2], inv)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    steps = [   # (what the person changed, the column that must then hold it)
        ({"vehicle_no": "CG04CH0001"}, "vehicle_no", "CG04CH0001"),
        ({"transporter": "Other Transport"}, "transporter", "Other Transport"),
        ({"lr_no": "LR-1"}, "lr_no", "LR-1"),
        ({"driver_name": "Mahesh"}, "driver_name", "Mahesh"),
        ({"driver_mobile": "9111111111"}, "driver_mobile", "9111111111"),
        ({"challan_date": yesterday}, "challan_date", yesterday),
        ({"buyer_name": "AGNI GREEN POWER LTD"}, "buyer_name",
         "AGNI GREEN POWER LTD"),
        ({"buyer_gstin": "27AAACX0000A1Z5"}, "buyer_gstin", "27AAACX0000A1Z5"),
        ({"consignee_same_as_buyer": False, "consignee_name": "Site Store",
          "consignee_address": "Plot 4\nRaipur"}, "consignee_name", "Site Store"),
        ({"consignee_address": "Plot 9\nRaipur"}, "consignee_address",
         "Plot 9\nRaipur"),
        ({"boxes": [b2, b1]}, None, None),      # the same pallets, another order
        ({"boxes": [b2, b3]}, None, None),      # a different pallet
    ]
    for over, col, want in steps:
        r = c.post("/api/challan/%d/edit-save" % live,
                   json=edit_payload(c, live, **over))
        assert r.status_code == 200, (over, r.get_json())
        j = r.get_json()
        assert j["changed"] is True and j["challan_id"] != live, (over, j)
        assert dict(challan_row(live))["status"] == "superseded", over
        live = j["challan_id"]
        if col:
            assert dict(challan_row(live))[col] == want, (over, dict(challan_row(live)))
        if "boxes" in over:
            assert edit_payload(c, live)["boxes"] == over["boxes"], over
        again = c.post("/api/challan/%d/edit-save" % live,
                       json=edit_payload(c, live))
        assert again.get_json()["changed"] is False, \
            ("did not round-trip after", over, again.get_json())
        assert dict(challan_row(live))["status"] == "issued", over
    assert dict(challan_row(live))["suffix"] == "ML", dict(challan_row(live))


@test("an edit keeps the challan's own date unless the date was changed - left "
      "out of the post it is the challan's, not today's; today posted over an "
      "older date IS a change")
def t_edit_keeps_challan_date():
    c = setup()
    b1 = packed_box(c, [154, 155])
    b2 = packed_box(c, [156, 157])
    inv = make_invoice(qty=2, invoice_no="INV-KEEPDATE")
    old = datetime.date.today() - datetime.timedelta(days=3)
    r = c.post("/api/challan", json={"action": "create", "boxes": [b1],
                                     "invoice_id": inv,
                                     "challan_date": old.isoformat()})
    assert r.status_code == 200, r.get_json()
    chid = r.get_json()["challan_id"]

    # a real change that says nothing about the date
    r = c.post("/api/challan/%d/edit-save" % chid,
               json={"boxes": [b2], "invoice_id": inv})
    j = r.get_json()
    assert r.status_code == 200 and j["changed"] is True, j
    assert dict(challan_row(j["challan_id"]))["challan_date"] == old.isoformat()
    assert old.strftime("%d.%m.%Y") in j["no"], \
        "the corrected challan's number does not carry its own date: " + j["no"]

    # the person changing the date to today is a change of the date
    today = datetime.date.today().isoformat()
    r2 = c.post("/api/challan/%d/edit-save" % j["challan_id"],
                json=edit_payload(c, j["challan_id"], challan_date=today))
    assert r2.get_json()["changed"] is True, r2.get_json()
    assert dict(challan_row(r2.get_json()["challan_id"]))["challan_date"] == today


@test("edit-draft hands the screen the challan's OWN date, buyer, consignee and "
      "transport - never today's date and the invoice's buyer - so what the "
      "screen posts back untouched is exactly what is stored")
def t_edit_draft_returns_own_values():
    c = setup()
    b = packed_box(c, [158, 159])
    inv = make_invoice(qty=2, invoice_no="INV-OWNVALUES")
    old = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    r = c.post("/api/challan", json={
        "action": "create", "boxes": [b], "invoice_id": inv,
        "challan_date": old, "buyer_name": "Typed Buyer Pvt Ltd",
        "buyer_gstin": "22AAAAA0000A1Z5", "consignee_same_as_buyer": False,
        "consignee_name": "Site Store", "consignee_address": "Plot 4\nRaipur",
        "vehicle_no": "CG04XY9999", "transporter": "Tee", "lr_no": "LR-5",
        "driver_name": "Dee", "driver_mobile": "9000000009"})
    assert r.status_code == 200, r.get_json()
    chid = r.get_json()["challan_id"]

    d = c.post("/api/challan/%d/edit-draft" % chid, json={}).get_json()
    assert d["challan_date"] == old, d
    assert d["buyer_name"] == "Typed Buyer Pvt Ltd", d
    assert d["buyer_gstin"] == "22AAAAA0000A1Z5", d
    assert d["consignee_same_as_buyer"] is False, d
    assert d["consignee_name"] == "Site Store", d
    assert d["consignee_address"] == "Plot 4\nRaipur", d
    assert (d["vehicle_no"], d["transporter"], d["lr_no"], d["driver_name"],
            d["driver_mobile"]) == ("CG04XY9999", "Tee", "LR-5", "Dee",
                                    "9000000009"), d

    j = c.post("/api/challan/%d/edit-save" % chid,
               json=edit_payload(c, chid)).get_json()
    assert j["changed"] is False, j
    assert len(all_challans()) == 1, all_challans()

    # and a challan whose consignee is the buyer says so
    b2 = packed_box(c, [160, 161])
    inv2 = make_invoice(qty=2, invoice_no="INV-OWNVALUES2")
    other = make_issued_challan(c, [b2], inv2)
    d2 = c.post("/api/challan/%d/edit-draft" % other, json={}).get_json()
    assert d2["consignee_same_as_buyer"] is True and not d2["consignee_name"], d2


# --------------------------------------------------------------------------
# Cancelling an ISSUED challan is Admin / Super Admin only (DECISIONS.md
# section 3). Two routes reach it - /cancel and the issued branch of /discard,
# which the challan screen's Cancel button uses - and both run the one shared
# helper, so every rule below is checked on BOTH.
# --------------------------------------------------------------------------

def _dispatch_client():
    """A second client signed in as a Dispatch Operator - Challan write, not
    an Admin. (Its flags come from default_perms_for_role.)"""
    c2 = APP.app.test_client()
    AUTH.test_login(c2, role="Dispatch Operator", login_id="disp.cancel")
    return c2


def _both_routes(c, chid, body):
    """The same request to /cancel and to /discard -> [(route, response)]"""
    return [("cancel", c.post("/api/challan/%d/cancel" % chid, json=dict(body))),
            ("discard", c.post("/api/challan/%d/discard" % chid, json=dict(body)))]


@test("a Dispatch Operator cannot cancel an issued challan - 403 on BOTH routes, "
      "even with a reason and a valid code - and the challan is untouched")
def t_cancel_operator_refused():
    c = setup()
    b = packed_box(c, [300, 301])
    inv = make_invoice(qty=2, invoice_no="INV-OPCAN")
    chid = make_issued_challan(c, [b], inv)
    op = _dispatch_client()
    for route, r in _both_routes(op, chid, _cancel_body({"reason": "customer asked"})):
        assert r.status_code == 403, (route, r.status_code, r.get_json())
        # refused for the ROLE - not merely because an operator has no
        # authenticator code, which would refuse it too
        assert "authenticator" not in r.get_json()["why"].lower(), (route, r.get_json())
    assert challan_row(chid)["status"] == "issued"
    assert state_of_serial(serial(300)) == "dispatched", "the refused cancel moved a serial"


def state_of_serial(s):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, s) or {}).get("state")


@test("an Admin must give a reason, on both routes: none, or blanks, is 400 - "
      "never a default string - and a refused attempt does not burn the code")
def t_cancel_reason_mandatory():
    c = setup()
    b = packed_box(c, [302, 303])
    inv = make_invoice(qty=2, invoice_no="INV-NOREASON")
    chid = make_issued_challan(c, [b], inv)
    for body in ({}, {"reason": ""}, {"reason": "   "}):
        for route, r in _both_routes(c, chid, dict(body, totp_code=AUTH.totp_code(_TOTP_SECRET))):
            assert r.status_code == 400 and "reason" in r.get_json()["why"].lower(),                 (route, body, r.status_code, r.get_json())
    row = challan_row(chid)
    assert row["status"] == "issued" and not row["cancelled_reason"], dict(row)
    # the code was not spent by those refusals: the same code now cancels it
    code = AUTH.totp_code(_TOTP_SECRET)
    r = c.post("/api/challan/%d/discard" % chid,
               json={"reason": "wrong vehicle", "totp_code": code})
    assert r.status_code == 200, r.get_json()


@test("an Admin cannot cancel a challan a gate pass references - on BOTH routes "
      "(one challan each: the authenticator code is spent by the first attempt)")
def t_cancel_gatepass_both_routes():
    c = setup()
    for n, route in enumerate(("cancel", "discard")):
        b = packed_box(c, [304 + 20 * n, 305 + 20 * n])
        inv = make_invoice(qty=2, invoice_no="INV-GPBOTH%d" % n)
        chid = make_issued_challan(c, [b], inv)
        add_gatepass(c, chid)
        r = c.post("/api/challan/%d/%s" % (chid, route), json=_cancel_body({"reason": "x"}))
        assert r.status_code == 400 and "gate pass" in r.get_json()["why"].lower(),             (route, r.status_code, r.get_json())
        assert challan_row(chid)["status"] == "issued"
        # let the next attempt use a new code window: a spent code is refused
        import icon_auth
        with store.conn() as (cx, cur):
            cur.execute("UPDATE app_user SET totp_last_step = 0")


@test("an Admin's cancel through the Cancel button's route (/discard) does the "
      "whole job: serials back to packed, the pallet and the invoice selectable "
      "again, the audit row names the real actor and the reason")
def t_cancel_via_discard_does_everything():
    c = setup()
    b = packed_box(c, [306, 307])
    inv = make_invoice(qty=2, invoice_no="INV-VIADISC")
    chid = make_issued_challan(c, [b], inv)
    assert state_of_serial(serial(306)) == "dispatched"
    r = c.post("/api/challan/%d/discard" % chid,
               json=_cancel_body({"reason": "wrong consignee"}))
    assert r.status_code == 200, r.get_json()
    row = challan_row(chid)
    assert row["status"] == "cancelled" and row["cancelled_reason"] == "wrong consignee", dict(row)
    assert row["cancelled_by"] == "Test Super Admin" and row["cancelled_at"], dict(row)
    assert state_of_serial(serial(306)) == "packed" and state_of_serial(serial(307)) == "packed"
    boxes = [x["box_id"] for x in c.get("/api/boxes?state=closed&exclude_live_challan=1").get_json()]
    assert b in boxes, "the pallet is not selectable again"
    invs = [x["id"] for x in c.get("/api/invoices?for_challan=1").get_json()["invoices"]]
    assert inv in invs, "the invoice is not selectable again"
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT actor, detail FROM dispatch_audit WHERE action='challan.cancel' "
                           "AND entity_id=%s", (str(chid),))
    assert a and a["actor"] == "Test Super Admin" and "wrong consignee" in a["detail"], a


@test("a Dispatch Operator can still EDIT an issued challan and DISCARD a draft - "
      "only cancelling an issued one is Admin-only")
def t_operator_keeps_edit_and_draft_discard():
    c = setup()
    b1 = packed_box(c, [308, 309])
    b2 = packed_box(c, [310, 311])
    inv = make_invoice(qty=2, invoice_no="INV-OPEDIT")
    chid = make_issued_challan(c, [b1], inv)
    op = _dispatch_client()
    r = op.post("/api/challan/%d/edit-draft" % chid, json={})
    assert r.status_code == 200, r.get_json()
    r = op.post("/api/challan/%d/edit-save" % chid,
                json={"boxes": [b2], "invoice_id": inv, "vehicle_no": "CG04AB1234"})
    assert r.status_code == 200 and r.get_json()["suffix"] == "MA", r.get_json()
    b3 = packed_box(c, [312, 313])
    inv2 = make_invoice(qty=2, invoice_no="INV-OPDRAFT")
    d = op.post("/api/challan", json={"action": "draft", "boxes": [b3], "invoice_id": inv2})
    assert d.status_code == 200, d.get_json()
    r = op.post("/api/challan/%d/discard" % d.get_json()["challan_id"], json={})
    assert r.status_code == 200, r.get_json()


@test("a cancelled challan's number is never reused")
def t_cancelled_number_not_reused():
    c = setup()
    b1 = packed_box(c, [314, 315])
    inv1 = make_invoice(qty=2, invoice_no="INV-REUSE1")
    first = make_issued_challan(c, [b1], inv1)
    seq1 = challan_row(first)["seq"]
    r = c.post("/api/challan/%d/discard" % first, json=_cancel_body({"reason": "redo"}))
    assert r.status_code == 200, r.get_json()
    inv2 = make_invoice(qty=2, invoice_no="INV-REUSE2")
    second = make_issued_challan(c, [b1], inv2)
    assert challan_row(second)["seq"] != seq1 and challan_row(second)["seq"] > seq1, \
        (seq1, challan_row(second)["seq"])


def _assign_rows(box_id):
    with store.conn() as (cx, cur):
        return store.rows(cur, "SELECT * FROM dispatch_audit WHERE "
                               "action='box.customer_assigned' AND entity_id=%s",
                          (str(box_id),))


@test("Icon Stock delivered to a customer: the module's Customer assignment "
      "history gets a row with who it was, who it is, the reason and who did it")
def t_assignment_history_row():
    c = setup()
    b = packed_box(c, [0, 1], customer="ICON STOCK")
    inv = make_invoice(qty=2, invoice_no="ICON/26-27/911")
    r = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                     "invoice_id": inv}).get_json()
    assert r["ok"], r
    rows = c.get("/api/trace/serial/" + serial(0)).get_json()["assignment"]
    assert len(rows) == 2, rows
    assert rows[0]["reason"] == "Original allocation", rows[0]
    new = rows[1]
    assert new["customer"] == AGNI_NAME or "AGNI" in new["customer"].upper(), new
    assert "Icon Stock" in new["reason"], new
    assert r["no"] in new["reason"] and "ICON/26-27/911" in new["reason"], \
        "the reason must name the challan and the invoice: %r" % new["reason"]
    assert new["by"] and new["by"] != "—", new
    assert len(_assign_rows(b)) == 1


@test("a pallet that already has a customer writes no assignment row, and a "
      "second challan step (submit) writes none either")
def t_assignment_history_only_on_change():
    c = setup()
    b = packed_box(c, [0, 1], customer=BOROSIL_CODE)
    with store.conn() as (cx, cur):
        db.assign_customer_on_challan(cur, b, "C0001", "tester")
    assert not _assign_rows(b), "an unchanged owner was logged as a change"
    g = packed_box(c, [10, 11], customer=None)
    inv = make_invoice(qty=2, invoice_no="INV-HIST2")
    r = c.post("/api/challan", json={"action": "draft", "boxes": [g],
                                     "invoice_id": inv}).get_json()
    assert r["ok"], r
    assert len(_assign_rows(g)) == 1
    r2 = c.post("/api/challan/%d/submit" % r["challan_id"], json={}).get_json()
    assert r2["ok"], r2
    assert len(_assign_rows(g)) == 1, "submit logged the same change again"


@test("a module allocated to the buyer, in a pallet that carried no customer, "
      "shows no 'Was Icon Stock' row once delivered to that buyer - and one "
      "allocated to someone else says whom it was (audit A6, 10 Oct)")
def t_assignment_history_names_the_real_owner():
    c = setup()
    b = packed_box(c, [20, 21], customer=None)
    o = packed_box(c, [22, 23], customer=None)
    with store.conn() as (cx, cur):
        cur.execute("UPDATE serial SET customer='C0001' WHERE serial IN (%s, %s)",
                    (serial(20), serial(21)))
        cur.execute("UPDATE serial SET customer=%s WHERE serial IN (%s, %s)",
                    (BOROSIL_CODE, serial(22), serial(23)))
    inv = make_invoice(qty=4, invoice_no="INV-OWNER")
    r = c.post("/api/challan", json={"action": "create", "boxes": [b, o],
                                     "invoice_id": inv}).get_json()
    assert r["ok"], r
    assert len(_assign_rows(b)) == 1, "the pallet's own change is still recorded"
    rows = c.get("/api/trace/serial/" + serial(20)).get_json()["assignment"]
    assert [x["reason"] for x in rows] == ["Original allocation"], rows
    rows = c.get("/api/trace/serial/" + serial(22)).get_json()["assignment"]
    assert len(rows) == 2 and rows[1]["reason"].startswith("Was Borosil"), rows
    assert "AGNI" in rows[1]["customer"].upper(), rows


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
