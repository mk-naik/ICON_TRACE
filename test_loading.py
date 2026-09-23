"""
ICON TRACE - tests for Loading Verification.

    python test_loading.py

THE RULE THIS FILE DEFENDS

    A challan's print and Excel documents are not produced until every
    pallet on it has actually been found and confirmed on the vehicle -
    Team 3's own physical check, not the paperwork's own say-so. Submit is
    all-or-nothing: it promotes every pallet together, in one transaction,
    or it refuses and names exactly which ones are still unconfirmed.

    Editing a challan mints fresh challan_box rows (the existing (MA)/(MB)
    mechanism), so a post-edit session starts at 'pending' on every pallet
    with no manual reset step - the old verification does not carry over
    to a document that is not the one being shipped any more.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_loading_")
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


def packed_box(c, idx, watt=WATT, model=MODEL, grade="A"):
    """A closed pallet holding the modules at those indexes."""
    _seed_serials(idx, watt, model)
    for i in idx:
        r = c.post("/api/fqc", json={"serial": serial(i, watt), "outcome": "pass"})
        assert r.status_code == 200, r.get_json()
    b = c.post("/api/box/open", json={"grade": grade, "model": model,
                                      "capacity": len(idx)}).get_json()
    for i in idx:
        r = c.post("/api/box/%d/scan" % b["box_id"],
                   json={"serial": serial(i, watt)})
        assert r.status_code == 200, r.get_json()
    c.post("/api/box/%d/close" % b["box_id"], json={})
    return b["box_id"]


def make_invoice(qty, model=MODEL, invoice_no=None):
    data = {"buyer_name": AGNI_NAME, "buyer_gstin": AGNI_GSTIN,
            "declared_qty": qty, "declared_model": model,
            "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                              datetime.timedelta(days=10)).isoformat(),
            "invoice_no": invoice_no or ("INV-%d" % (id(object()) % 100000)),
            "irn": None, "consignee_same_as_buyer": 1}
    with store.conn() as (cx, cur):
        return db.insert_invoice(cur, data, "test.pdf", "deadbeef",
                                 {"fields": {}, "compare_only": {}, "qr": {}},
                                 False, {}, "tester")


def make_issued_challan(c, box_ids, invoice_id):
    r = c.post("/api/challan", json={"action": "create", "boxes": box_ids,
                                     "invoice_id": invoice_id})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["challan_id"]


def box_no_of(chid, idx=0):
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT box_no FROM challan_box WHERE "
                               "challan_id=%s ORDER BY load_order", (chid,))
    return rows[idx]["box_no"]


def statuses_of(chid):
    with store.conn() as (cx, cur):
        rows = store.rows(cur, "SELECT box_no, loading_status FROM "
                               "challan_box WHERE challan_id=%s "
                               "ORDER BY load_order", (chid,))
    return {r["box_no"]: r["loading_status"] for r in rows}


def gatepasses_for(chid):
    with store.conn() as (cx, cur):
        return [dict(r) for r in store.rows(
            cur, "SELECT * FROM gatepass WHERE challan_id=%s", (chid,))]


# --------------------------------------------------------------------------
# the scan / confirm session
# --------------------------------------------------------------------------

@test("a pallet not on this challan is rejected when scanned in its session")
def t_wrong_pallet_rejected():
    c = setup()
    b1 = packed_box(c, [0, 1])
    b2 = packed_box(c, [2, 3])
    inv1 = make_invoice(qty=2, invoice_no="INV-LOAD1")
    inv2 = make_invoice(qty=2, invoice_no="INV-LOAD2")
    chid1 = make_issued_challan(c, [b1], inv1)
    make_issued_challan(c, [b2], inv2)          # a different, real challan

    # the box on the OTHER challan
    with store.conn() as (cx, cur):
        other_box_no = store.one(cur, "SELECT box_no FROM challan_box "
                                      "WHERE challan_id<>%s LIMIT 1",
                                 (chid1,))["box_no"]
    r = c.post("/api/loading/%d/confirm" % chid1, json={"box_no": other_box_no})
    assert r.status_code == 400, "a pallet from a different challan was accepted"
    assert "not on this challan" in r.get_json()["why"].lower(), r.get_json()


@test("confirming a pallet persists immediately - reopening the session "
     "still shows it saved")
def t_confirm_persists():
    c = setup()
    b = packed_box(c, [10, 11])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-PERSIST")
    chid = make_issued_challan(c, [b], inv)
    box_no = box_no_of(chid)

    r = c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["loading_status"] == "saved"

    # "reopening the session" - a fresh GET, simulating close-and-reopen
    r2 = c.get("/api/loading/%d" % chid)
    row = [b2 for b2 in r2.get_json()["boxes"] if b2["box_no"] == box_no][0]
    assert row["loading_status"] == "saved", row
    assert row["loading_scanned_at"], "no timestamp persisted"
    assert row["loading_scanned_by"], "no actor persisted"


@test("model and grade shown in the session come from the live box, not a "
     "stale copy")
def t_session_shows_live_model_grade():
    c = setup()
    b = packed_box(c, [12, 13], model=MODEL, grade="A")
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-LIVE")
    chid = make_issued_challan(c, [b], inv)
    r = c.get("/api/loading/%d" % chid)
    row = r.get_json()["boxes"][0]
    assert row["model"] == MODEL, row
    assert row["grade"] == "A", row


# --------------------------------------------------------------------------
# submit: all or nothing
# --------------------------------------------------------------------------

@test("submit refuses when any pallet is still pending, and names which one")
def t_submit_refuses_pending():
    c = setup()
    b1 = packed_box(c, [20, 21])
    b2 = packed_box(c, [22, 23])
    inv = make_invoice(qty=4, invoice_no="INV-LOAD-PARTIAL")
    chid = make_issued_challan(c, [b1, b2], inv)
    box1, box2 = box_no_of(chid, 0), box_no_of(chid, 1)

    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box1})
    r = c.post("/api/loading/%d/submit" % chid, json={})
    assert r.status_code == 400
    assert box2 in r.get_json()["why"], r.get_json()
    assert "1 of 2" in r.get_json()["why"], r.get_json()
    # nothing was promoted
    st = statuses_of(chid)
    assert st[box1] == "saved" and st[box2] == "pending", st


@test("submit succeeds and promotes every pallet to loaded in one "
     "transaction - none left at 'saved' after")
def t_submit_promotes_atomically():
    c = setup()
    b1 = packed_box(c, [24, 25])
    b2 = packed_box(c, [26, 27])
    inv = make_invoice(qty=4, invoice_no="INV-LOAD-FULL")
    chid = make_issued_challan(c, [b1, b2], inv)
    box1, box2 = box_no_of(chid, 0), box_no_of(chid, 1)

    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box1})
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box2})
    r = c.post("/api/loading/%d/submit" % chid, json={})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["loaded"] == 2

    st = statuses_of(chid)
    assert all(v == "loaded" for v in st.values()), \
        "not every pallet was promoted: %s" % st
    assert "saved" not in st.values()


# --------------------------------------------------------------------------
# submit auto-generates the module gate pass - it did not exist as a
# record at all before this: api_loading_submit() promoted boxes and
# wrote an audit entry, but no one ever inserted a gatepass row.
# --------------------------------------------------------------------------

@test("submitting a fully-loaded challan creates exactly one gatepass "
     "row, linked to it, with a real drawn gp_no")
def t_submit_creates_gatepass():
    c = setup()
    b = packed_box(c, [70, 71])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-GP1")
    chid = make_issued_challan(c, [b], inv)
    box_no = box_no_of(chid)

    assert gatepasses_for(chid) == [], "a gate pass existed before submission"
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    r = c.post("/api/loading/%d/submit" % chid, json={})
    assert r.status_code == 200, r.get_json()

    gps = gatepasses_for(chid)
    assert len(gps) == 1, gps
    gp = gps[0]
    assert gp["gp_no"], "no gate pass number was drawn"
    assert gp["gp_no"].startswith("ISGP"), \
        "not drawn from the real numbering function: %r" % gp["gp_no"]
    assert gp["kind"] == "NRGP", gp
    assert gp["challan_id"] == chid, gp


@test("submitting an already-submitted challan again does not create a "
     "second gatepass row - safe to call at most once per challan")
def t_resubmit_does_not_duplicate_gatepass():
    c = setup()
    b = packed_box(c, [72, 73])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-GP2")
    chid = make_issued_challan(c, [b], inv)
    box_no = box_no_of(chid)
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    c.post("/api/loading/%d/submit" % chid, json={})
    first = gatepasses_for(chid)
    assert len(first) == 1, first

    r2 = c.post("/api/loading/%d/submit" % chid, json={})
    assert r2.status_code == 200, r2.get_json()
    r3 = c.post("/api/loading/%d/submit" % chid, json={})
    assert r3.status_code == 200, r3.get_json()

    second = gatepasses_for(chid)
    assert len(second) == 1, "resubmitting created another gate pass: %s" % second
    assert second[0]["gp_id"] == first[0]["gp_id"], \
        "the gate pass row's identity changed across a resubmit"


@test("the auto-created gate pass's party, vehicle and quantity come from "
     "the challan's own data - the same fields the old manual "
     "select-a-challan flow used to pull")
def t_gatepass_matches_challan_data():
    c = setup()
    b = packed_box(c, [74, 75])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-GP3")
    r0 = c.post("/api/challan", json={"action": "create", "boxes": [b],
                                      "invoice_id": inv,
                                      "vehicle_no": "CG04GP0001"})
    assert r0.status_code == 200, r0.get_json()
    chid = r0.get_json()["challan_id"]
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT * FROM challan WHERE challan_id=%s", (chid,))
    box_no = box_no_of(chid)
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    c.post("/api/loading/%d/submit" % chid, json={})

    gp = gatepasses_for(chid)[0]
    assert gp["party"] == ch["buyer_name"], (gp, dict(ch))
    assert gp["vehicle_no"] == "CG04GP0001", gp
    assert gp["qty"] == ch["qty"], (gp, dict(ch))
    assert ch["model"] in (gp["description"] or ""), gp


# --------------------------------------------------------------------------
# the print/excel gate
# --------------------------------------------------------------------------

@test("the print route refuses before submission and succeeds after")
def t_print_gated_on_submission():
    c = setup()
    b = packed_box(c, [30, 31])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-PRINT")
    chid = make_issued_challan(c, [b], inv)
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT fy, seq, suffix FROM challan "
                             "WHERE challan_id=%s", (chid,))
    fy, seq = row["fy"], row["seq"]

    r1 = c.get("/challan/%d/%d/print" % (fy, seq))
    assert r1.status_code == 400, "an unverified challan printed anyway"
    assert "loading verification" in r1.get_data(as_text=True).lower()

    r1x = c.get("/challan/%d/%d/excel" % (fy, seq))
    assert r1x.status_code == 400, "an unverified challan exported anyway"

    box_no = box_no_of(chid)
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    c.post("/api/loading/%d/submit" % chid, json={})

    r2 = c.get("/challan/%d/%d/print" % (fy, seq))
    assert r2.status_code == 200, r2.get_data(as_text=True)
    r2x = c.get("/challan/%d/%d/excel" % (fy, seq))
    assert r2x.status_code == 200


# --------------------------------------------------------------------------
# interaction with Edit
# --------------------------------------------------------------------------

@test("editing a challan produces fresh challan_box rows at 'pending' - a "
     "post-edit session starts genuinely clean, no manual reset")
def t_edit_resets_loading_status():
    c = setup()
    b1 = packed_box(c, [40, 41])
    b2 = packed_box(c, [42, 43])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-EDIT")
    chid = make_issued_challan(c, [b1], inv)
    box_no = box_no_of(chid)
    # Confirmed, not submitted: submitting now writes a real gate pass,
    # which locks the challan from being edited at all (the same check
    # every other challan mutation route already enforces) - a genuinely
    # different, and correct, refusal covered separately below. This test
    # is about the reset itself, so it exercises the edit while the
    # challan is still actually editable.
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    assert statuses_of(chid)[box_no] == "saved"

    r = c.post("/api/challan/%d/edit-save" % chid,
              json={"boxes": [b2], "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    new_id = r.get_json()["challan_id"]

    new_status = statuses_of(new_id)
    assert len(new_status) == 1
    assert list(new_status.values())[0] == "pending", \
        "the edited challan's pallet did not start clean: %s" % new_status
    # and the new document is correctly gated again, unrelated to the old
    # session's progress
    with store.conn() as (cx, cur):
        row = store.one(cur, "SELECT fy, seq FROM challan WHERE challan_id=%s",
                        (new_id,))
    r2 = c.get("/challan/%d/%d/print" % (row["fy"], row["seq"]))
    assert r2.status_code == 400, \
        "a freshly edited challan printed without its own verification"


@test("a challan whose loading has been submitted - and so has a real "
     "gate pass now - can no longer be edited at all, locked the same "
     "way any other gate-pass-referenced challan already is")
def t_submitted_challan_locked_from_edit():
    c = setup()
    b = packed_box(c, [76, 77])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-LOCK")
    chid = make_issued_challan(c, [b], inv)
    box_no = box_no_of(chid)
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    c.post("/api/loading/%d/submit" % chid, json={})
    assert len(gatepasses_for(chid)) == 1

    r = c.post("/api/challan/%d/edit-save" % chid,
              json={"boxes": [b], "invoice_id": inv})
    assert r.status_code == 400, \
        "a challan with a real gate pass on it was edited anyway"
    assert "gate pass" in r.get_json()["why"].lower(), r.get_json()


# --------------------------------------------------------------------------
# the landing list
# --------------------------------------------------------------------------

@test("an already fully loaded challan shows correctly on the landing "
     "list, and its session reopens read-only")
def t_landing_shows_loaded_and_readonly_reopen():
    c = setup()
    b = packed_box(c, [50, 51])
    inv = make_invoice(qty=2, invoice_no="INV-LOAD-DONE")
    chid = make_issued_challan(c, [b], inv)
    box_no = box_no_of(chid)
    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no})
    c.post("/api/loading/%d/submit" % chid, json={})

    with store.conn() as (cx, cur):
        d = store.one(cur, "SELECT challan_date FROM challan WHERE "
                          "challan_id=%s", (chid,))["challan_date"]
    r = c.get("/api/loading/challans?from=%s&to=%s" % (d, d))
    row = [x for x in r.get_json()["challans"]
          if x["challan_id"] == chid][0]
    assert row["agg_status"] == "loaded", row
    assert row["n_loaded"] == row["n_total"], row

    # reopening: GET always works and reports the true state (this is the
    # "read-only" choice - the screen shows everything already loaded and
    # submit/confirm on an already-loaded pallet is a harmless no-op, not
    # a new decision, since resubmitting is idempotent)
    r2 = c.get("/api/loading/%d" % chid)
    assert all(b2["loading_status"] == "loaded" for b2 in r2.get_json()["boxes"])
    r3 = c.post("/api/loading/%d/submit" % chid, json={})
    assert r3.status_code == 200, \
        "re-submitting an already-loaded session was not a safe no-op"


@test("the landing list shows pending and in-progress challans correctly, "
     "aggregated per challan")
def t_landing_aggregate_status():
    c = setup()
    b1 = packed_box(c, [52, 53])
    b2 = packed_box(c, [54, 55])
    inv = make_invoice(qty=4, invoice_no="INV-LOAD-AGG")
    chid = make_issued_challan(c, [b1, b2], inv)
    with store.conn() as (cx, cur):
        d = store.one(cur, "SELECT challan_date FROM challan WHERE "
                          "challan_id=%s", (chid,))["challan_date"]

    r = c.get("/api/loading/challans?from=%s&to=%s" % (d, d))
    row = [x for x in r.get_json()["challans"] if x["challan_id"] == chid][0]
    assert row["agg_status"] == "pending", row

    c.post("/api/loading/%d/confirm" % chid, json={"box_no": box_no_of(chid, 0)})
    r2 = c.get("/api/loading/challans?from=%s&to=%s" % (d, d))
    row2 = [x for x in r2.get_json()["challans"] if x["challan_id"] == chid][0]
    assert row2["agg_status"] == "in_progress", row2


@test("the landing list excludes a cancelled challan and a superseded "
     "(edited-away) original")
def t_landing_excludes_cancelled_and_superseded():
    c = setup()
    b1 = packed_box(c, [60, 61])
    b2 = packed_box(c, [62, 63])
    inv1 = make_invoice(qty=2, invoice_no="INV-LOAD-CANCEL")
    inv2 = make_invoice(qty=2, invoice_no="INV-LOAD-SUPER")
    cancelled_id = make_issued_challan(c, [b1], inv1)
    superseded_id = make_issued_challan(c, [b2], inv2)

    c.post("/api/challan/%d/cancel" % cancelled_id,
          json={"reason": "test cancel"})
    edit = c.post("/api/challan/%d/edit-save" % superseded_id,
                  json={"boxes": [b2], "invoice_id": inv2,
                        "vehicle_no": "CG04EDITED1"})
    assert edit.status_code == 200, edit.get_json()

    with store.conn() as (cx, cur):
        d = store.one(cur, "SELECT challan_date FROM challan WHERE "
                          "challan_id=%s", (cancelled_id,))["challan_date"]
    r = c.get("/api/loading/challans?from=%s&to=%s" % (d, d))
    ids = {x["challan_id"] for x in r.get_json()["challans"]}
    assert cancelled_id not in ids, "a cancelled challan appeared on the landing list"
    assert superseded_id not in ids, \
        "a superseded (edited-away) original appeared on the landing list"
    assert edit.get_json()["challan_id"] in ids, \
        "the LIVE replacement was missing from the landing list"


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
