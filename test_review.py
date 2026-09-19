"""
ICON TRACE - tests for the merged Needs Review feed and duplicate-scan
detection.

    python test_review.py

THE RULES THIS FILE DEFENDS

  1. A retest of an already-packed (or dispatched) serial that AGREES with
     the record already on file is confirmed correct, not a conflict - it
     creates no review item. Flagging an agreement anyway trains people to
     stop reading flags.

  2. A retest that DISAGREES creates exactly one review item, holding both
     records' evidence for side-by-side display. Software shows the
     evidence; it never picks a side.

  3. Resolving a duplicate-scan item needs a Production Shift Incharge or
     above - not a bare Operator - because they carry the consequence of
     the choice. Checked server-side, not by hiding a button.

  4. "Keep the rescanned one" calls Repack's real removal path - the same
     one a manual repack removal uses - so the box ends up short by one
     exactly the way a manual removal leaves it. The original record is
     marked cancelled (superseded), never deleted or mutated beyond that,
     and stays visible in the module's own history.

  5. A conflict discovered after the serial has already been dispatched can
     only be acknowledged, and only by Admin. Building a replacement-serial
     workflow is explicitly out of scope for this pass - confirmed genuinely
     absent, not merely unused.

  6. Every resolution, of every type, requires a non-empty reason or is
     refused. No exceptions.

Each test names the rule it defends, so a failure says which decision broke.
"""

import csv, os, shutil, sys, tempfile, traceback, datetime

TMP = tempfile.mkdtemp(prefix="icontrace_review_")
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


WATT = 625
MODEL = "ISEN625-G12R"
SS = os.path.join(TMP, "ss.csv")
EL_OK = os.path.join(TMP, "el", "OK")
os.makedirs(EL_OK, exist_ok=True)


def serial(i):
    return "ICON625R129071%04d" % i


def ss_row(sid, at, pmax):
    return [at, sid, pmax, "12.1", "48.9", "11.8", "52.5", "96.1", "0.41",
            "0.4", "210.0", "23.1", "25", "25", "1000"]


def write_ss(rows):
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def add_rescan_row(i, at, pmax):
    """A later reading for the same serial - ev.gather() takes the latest
    valid row, so this is what a physical rescan looks like on paper."""
    with open(SS, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    rows.append(ss_row(serial(i), at, pmax))
    write_ss(rows)


def setup(n=8):
    store.wipe()
    rows = []
    for i in range(n):
        s = serial(i)
        open(os.path.join(EL_OK, s + ".jpg"), "w").close()
        rows.append(ss_row(s, "2026-09-09 10:%02d:00" % i, "630.5"))
    write_ss(rows)
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS, "el_root": os.path.dirname(EL_OK),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_a_root": "", "el_b_root": ""})
        for i in range(n):
            store.insert(cur, "serial", {
                "serial": serial(i), "build_instance": 1, "model": MODEL,
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned"})
    return APP.app.test_client()


def hdrs(role, name=None):
    h = {"X-User-Role": role}
    if name:
        h["X-User-Name"] = name
    return h


def serial_row(s):
    with store.conn() as (cx, cur):
        return dict(db.find_serial(cur, s) or {})


def box_row(bid):
    with store.conn() as (cx, cur):
        return dict(store.box_row(cur, bid))


def contents(bid):
    with store.conn() as (cx, cur):
        return sorted(store.box_serials(cur, bid))


def lineage(bid):
    with store.conn() as (cx, cur):
        return sorted(r["child_box_id"] for r in store.rows(
            cur, "SELECT child_box_id FROM box_lineage WHERE parent_box_id=%s",
            (bid,)))


def fqc_row_by_id(fqc_id):
    with store.conn() as (cx, cur):
        return dict(store.one(cur, "SELECT * FROM fqc_record WHERE fqc_id=%s",
                              (fqc_id,)))


def live_fqc_row(s):
    with store.conn() as (cx, cur):
        return dict(store.one(cur, "SELECT * FROM fqc_record WHERE serial=%s "
                                   "AND superseded_by IS NULL", (s,)))


def review_item(review_id):
    with store.conn() as (cx, cur):
        return db.review_item_get(cur, review_id)


def pass_and_pack(c, i, capacity=1):
    """One module, passed and closed alone into its own box."""
    s = serial(i)
    r = c.post("/api/fqc", json={"serial": s, "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    b = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                      "capacity": capacity}).get_json()
    r = c.post("/api/box/%d/scan" % b["box_id"], json={"serial": s})
    assert r.status_code == 200, r.get_json()
    r = c.post("/api/box/%d/close" % b["box_id"], json={})
    assert r.status_code == 200, r.get_json()
    return b["box_id"]


def make_invoice(qty, model=MODEL):
    data = {"buyer_name": "Agni Solar", "buyer_gstin": "22AAAAA0000A1Z5",
            "declared_qty": qty, "declared_model": model,
            "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                              datetime.timedelta(days=10)).isoformat(),
            "invoice_no": "INV-REVIEW-%d" % qty, "irn": None,
            "consignee_same_as_buyer": 1}
    with store.conn() as (cx, cur):
        return db.insert_invoice(cur, data, "test.pdf", "deadbeef" + str(qty),
                                 {"fields": {}, "compare_only": {}, "qr": {}},
                                 False, {}, "tester")


def dispatch_one(c, i):
    """Pack serial i alone, then dispatch its box - state becomes
    'dispatched' the same way a real challan does it."""
    bid = pass_and_pack(c, i, capacity=1)
    inv = make_invoice(1)
    r = c.post("/api/challan", json={"action": "draft", "boxes": [bid],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    chid = r.get_json()["challan_id"]
    r = c.post("/api/challan/%d/submit" % chid, json={})
    assert r.status_code == 200, r.get_json()
    assert serial_row(serial(i))["state"] == "dispatched"
    return bid


# --------------------------------------------------------------------------
# 1 & 2 - detection: agree is silent, disagree raises one item
# --------------------------------------------------------------------------

@test("a retest that agrees with the original creates no review item")
def t_agree_no_item():
    c = setup()
    pass_and_pack(c, 0)
    add_rescan_row(0, "2026-09-09 12:00:00", "628.0")   # still >= 625: a pass
    r = c.post("/api/fqc", json={"serial": serial(0), "outcome": "pass"},
               headers=hdrs("FQC Operator"))
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d.get("duplicate_scan") is True and d.get("agree") is True, d
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                          "serial=%s", (serial(0),))["n"]
    assert n == 0, "an agreement was flagged anyway"
    assert serial_row(serial(0))["state"] == "packed", "state moved on a mere confirmation"
    assert serial_row(serial(0))["grade"] == "A"


@test("a retest that disagrees creates one review item, holding both records' evidence")
def t_disagree_creates_item():
    c = setup()
    pass_and_pack(c, 1)
    add_rescan_row(1, "2026-09-09 12:00:00", "600.0")   # below wattage: reject
    r = c.post("/api/fqc", json={"serial": serial(1), "outcome": "reject"},
               headers=hdrs("FQC Operator"))
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d.get("duplicate_scan") is True and d.get("agree") is False, d
    review_id = d["review_id"]

    feed = c.get("/api/review", headers=hdrs("Production Incharge")).get_json()
    item = next(x for x in feed if x["type"] == "duplicate_scan" and x["id"] == review_id)
    assert item["evidence"]["original"]["outcome"] == "pass", item
    assert item["evidence"]["rescan"]["outcome"] == "reject", item
    assert item["evidence"]["original"]["pmax"] == 630.5, item
    assert item["evidence"]["rescan"]["pmax"] == 600.0, item
    # nothing acted on yet - the module is exactly where packing left it
    assert serial_row(serial(1))["state"] == "packed"
    assert serial_row(serial(1))["grade"] == "A"


# --------------------------------------------------------------------------
# 3 - only a Shift Incharge or above resolves it
# --------------------------------------------------------------------------

@test("a Production Operator (not Shift Incharge) cannot resolve a "
     "duplicate-scan item - checked server-side")
def t_bare_operator_cannot_resolve():
    c = setup()
    pass_and_pack(c, 2)
    add_rescan_row(2, "2026-09-09 12:00:00", "600.0")
    d = c.post("/api/fqc", json={"serial": serial(2), "outcome": "reject"},
               headers=hdrs("FQC Operator")).get_json()
    review_id = d["review_id"]

    # FQC Operator is the role that actually raised this - v4 has no role
    # literally named "Production Operator", so the bare-operator stand-in
    # here is the same role the scan itself came from, which is exactly
    # the case a hidden button would have gotten away with.
    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id,
                    "resolution": "keep_original", "reason": "trying anyway"},
              headers=hdrs("FQC Operator"))
    assert r.status_code == 403, r.get_json()
    assert review_item(review_id)["status"] == "open", "resolved by an Operator anyway"

    # Packing Operator - also a bare operator - is refused the same way.
    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id,
                    "resolution": "keep_original", "reason": "trying anyway"},
              headers=hdrs("Packing Operator"))
    assert r.status_code == 403, r.get_json()

    # Production Incharge (the Shift Incharge role) succeeds.
    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id,
                    "resolution": "keep_original",
                    "reason": "the rescan probe looked loose"},
              headers=hdrs("Production Incharge"))
    assert r.status_code == 200, r.get_json()
    assert review_item(review_id)["status"] == "resolved"


# --------------------------------------------------------------------------
# 4 - "keep rescanned" is Repack, not a second removal path
# --------------------------------------------------------------------------

@test("'keep the rescanned one' calls Repack's real removal path, matching "
     "a manual repack removal")
def t_keep_rescanned_uses_repack():
    c = setup()
    # Box X: the one resolved through the duplicate-scan popup.
    for i in (3, 4):
        assert c.post("/api/fqc", json={"serial": serial(i),
                     "outcome": "pass"}).status_code == 200
    bx = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                       "capacity": 2}).get_json()["box_id"]
    for i in (3, 4):
        assert c.post("/api/box/%d/scan" % bx,
                     json={"serial": serial(i)}).status_code == 200
    assert c.post("/api/box/%d/close" % bx, json={}).status_code == 200

    # Box Y: the identical shape, removed BY HAND through the ordinary
    # Repack endpoint - the baseline "what a manual removal produces".
    for i in (5, 6):
        assert c.post("/api/fqc", json={"serial": serial(i),
                     "outcome": "pass"}).status_code == 200
    by = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                       "capacity": 2}).get_json()["box_id"]
    for i in (5, 6):
        assert c.post("/api/box/%d/scan" % by,
                     json={"serial": serial(i)}).status_code == 200
    assert c.post("/api/box/%d/close" % by, json={}).status_code == 200
    manual = c.post("/api/box/%d/repack" % by,
                    json={"reason": "manual baseline removal",
                          "release": [serial(5)]}).get_json()
    assert manual.get("ok") is not False, manual

    # Now raise and resolve a duplicate-scan conflict on box X the same way.
    add_rescan_row(3, "2026-09-09 12:00:00", "600.0")
    d = c.post("/api/fqc", json={"serial": serial(3), "outcome": "reject"},
               headers=hdrs("FQC Operator")).get_json()
    review_id = d["review_id"]
    out = c.post("/api/review/resolve",
                json={"type": "duplicate_scan", "id": review_id,
                      "resolution": "keep_rescanned",
                      "reason": "rescan is correct, original was a bad read"},
                headers=hdrs("Production Incharge", "Rajesh Kumar")).get_json()
    assert out.get("ok"), out

    kids_x, kids_y = lineage(bx), lineage(by)
    assert len(kids_x) == 1, kids_x
    assert len(kids_y) == 1, kids_y
    child_x, child_y = box_row(kids_x[0]), box_row(kids_y[0])

    # the box's resulting state matches what the manual removal produced
    assert child_x["qty"] == child_y["qty"] == 1, (child_x, child_y)
    assert child_x["capacity"] == child_y["capacity"], (child_x, child_y)
    assert child_x["grade"] == child_y["grade"] == "A"
    assert child_x["model"] == child_y["model"] == MODEL
    assert child_x["state"] == child_y["state"] == "closed"
    assert contents(kids_x[0]) == [serial(4)]
    assert contents(kids_y[0]) == [serial(6)]
    assert box_row(bx)["state"] == "retired"
    assert box_row(by)["state"] == "retired"

    # and the module itself now carries the rescan's decision
    assert serial_row(serial(3))["state"] == "rejected"
    assert serial_row(serial(3))["grade"] is None
    assert serial_row(serial(5))["state"] == "graded", \
        "the manually-released module should be back in graded stock"


# --------------------------------------------------------------------------
# the cancelled original: preserved, visible in the journey
# --------------------------------------------------------------------------

@test("the cancelled original is never deleted or overwritten, and both "
     "records appear correctly in the module journey")
def t_original_preserved_in_journey():
    c = setup()
    pass_and_pack(c, 7)
    before = live_fqc_row(serial(7))

    add_rescan_row(7, "2026-09-09 12:00:00", "600.0")
    d = c.post("/api/fqc", json={"serial": serial(7), "outcome": "reject"},
               headers=hdrs("FQC Operator")).get_json()
    review_id = d["review_id"]
    out = c.post("/api/review/resolve",
                json={"type": "duplicate_scan", "id": review_id,
                      "resolution": "keep_rescanned",
                      "reason": "rescan is correct"},
              headers=hdrs("Production Incharge")).get_json()
    assert out.get("ok"), out

    after = fqc_row_by_id(before["fqc_id"])
    for k in before:
        if k in ("superseded_by", "superseded_at"):
            continue
        assert after[k] == before[k], \
            "column %r changed on the cancelled original: %r -> %r" % (
                k, before[k], after[k])
    assert after["superseded_by"] is not None, "the original was never marked cancelled"
    assert after["superseded_at"] is not None

    with store.conn() as (cx, cur):
        hist = [dict(r) for r in store.rows(
            cur, "SELECT * FROM fqc_record WHERE serial=%s ORDER BY at",
            (serial(7),))]
    assert len(hist) == 2, "the original vanished instead of being kept"
    assert hist[0]["fqc_id"] == before["fqc_id"] and hist[0]["outcome"] == "pass"
    assert hist[1]["outcome"] == "reject"

    j = c.get("/api/trace/serial/" + serial(7)).get_json()
    fqc_stage = [s for s in j["journey"] if s["stage"] == "FQC"][0]
    assert fqc_stage["value"] == "Reject", \
        "the journey still shows the cancelled record, not the live one: %r" % fqc_stage


# --------------------------------------------------------------------------
# 5 - already dispatched: Admin-only, acknowledge-only
# --------------------------------------------------------------------------

@test("a dispatched-item conflict cannot be resolved by anyone but Admin, "
     "and has no path to a replacement serial")
def t_dispatched_admin_only_no_replacement():
    c = setup()
    dispatch_one(c, 0)

    add_rescan_row(0, "2026-09-09 12:00:00", "600.0")
    d = c.post("/api/fqc", json={"serial": serial(0), "outcome": "reject"},
               headers=hdrs("FQC Operator")).get_json()
    assert d.get("duplicate_scan") and d.get("agree") is False, d
    review_id = d["review_id"]

    # Production Incharge resolves an ordinary duplicate scan, but not one
    # discovered after dispatch.
    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id,
                    "resolution": "keep_original", "reason": "trying anyway"},
              headers=hdrs("Production Incharge"))
    assert r.status_code == 403, r.get_json()
    assert review_item(review_id)["status"] == "open"

    # Admin with no reason is refused too - mandatory here as everywhere.
    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id},
              headers=hdrs("Admin"))
    assert r.status_code == 400, r.get_json()

    # A request naming a replacement serial and asking to "replace" is
    # still just acknowledged - the field is never read, confirming the
    # workflow is genuinely absent rather than merely not exercised.
    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id,
                    "resolution": "replace",
                    "replacement_serial": "ICON999X0000000001",
                    "reason": "the dispatched module already shipped"},
              headers=hdrs("Admin"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["resolution"] == "acknowledged", \
        "a replacement-serial resolution was honoured"
    with store.conn() as (cx, cur):
        ghost = db.find_serial(cur, "ICON999X0000000001")
    assert ghost is None, "a replacement serial was created out of nothing"
    assert serial_row(serial(0))["state"] == "dispatched", \
        "the dispatched serial's state moved"
    assert review_item(review_id)["status"] == "resolved"
    assert review_item(review_id)["resolution"] == "acknowledged"


# --------------------------------------------------------------------------
# 6 - reason is mandatory everywhere, no exceptions
# --------------------------------------------------------------------------

@test("every resolution of every type records a non-empty reason, or is refused")
def t_reason_mandatory_everywhere():
    c = setup()

    # quality_grade
    # setup() gives every serial a clean, full-power reading, so overruling
    # it to a reject needs the same coded reason a real override would.
    assert c.post("/api/fqc", json={"serial": serial(0), "outcome": "reject",
                 "reason": "OV-QUALITY — quality engineer instruction"}
                 ).status_code == 200
    r = c.post("/api/review/resolve",
              json={"type": "quality_grade", "id": serial(0), "grade": "GY"},
              headers=hdrs("Quality"))
    assert r.status_code == 400, r.get_json()
    assert live_fqc_row(serial(0))["quality_grade"] is None, \
        "graded with no reason recorded"

    r = c.post("/api/review/resolve",
              json={"type": "quality_grade", "id": serial(0), "grade": "GY",
                    "reason": "edge chip, cosmetic only"},
              headers=hdrs("Quality"))
    assert r.status_code == 200, r.get_json()
    row = live_fqc_row(serial(0))
    assert row["quality_grade"] == "GY" and row["quality_note"], row

    # duplicate_scan
    pass_and_pack(c, 1)
    add_rescan_row(1, "2026-09-09 12:00:00", "600.0")
    d = c.post("/api/fqc", json={"serial": serial(1), "outcome": "reject"},
               headers=hdrs("FQC Operator")).get_json()
    review_id = d["review_id"]
    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id,
                    "resolution": "keep_original"},
              headers=hdrs("Production Incharge"))
    assert r.status_code == 400, r.get_json()
    assert review_item(review_id)["status"] == "open"

    r = c.post("/api/review/resolve",
              json={"type": "duplicate_scan", "id": review_id,
                    "resolution": "keep_original",
                    "reason": "the rescan probe looked loose"},
              headers=hdrs("Production Incharge"))
    assert r.status_code == 200, r.get_json()
    item = review_item(review_id)
    assert item["status"] == "resolved" and item["reason"], \
        "resolved with no reason recorded"


# --------------------------------------------------------------------------
# a quality-type item stays visible to Production but not actionable
# --------------------------------------------------------------------------

@test("a quality-type item is visible to Production in the shared feed, "
     "but cannot be resolved by Production")
def t_production_sees_but_cannot_act_on_quality():
    c = setup()
    # setup() gives every serial a clean, full-power reading, so overruling
    # it to a reject needs the same coded reason a real override would.
    assert c.post("/api/fqc", json={"serial": serial(0), "outcome": "reject",
                 "reason": "OV-QUALITY — quality engineer instruction"}
                 ).status_code == 200

    feed = c.get("/api/review", headers=hdrs("Production Incharge")).get_json()
    item = next(x for x in feed if x["type"] == "quality_grade" and
               x["serial"] == serial(0))
    assert item["locked"] is True, "Production should not see the evidence"
    assert item["evidence"] is None

    feed_q = c.get("/api/review", headers=hdrs("Quality")).get_json()
    item_q = next(x for x in feed_q if x["type"] == "quality_grade" and
                 x["serial"] == serial(0))
    assert item_q["locked"] is False
    assert item_q["evidence"] is not None

    r = c.post("/api/review/resolve",
              json={"type": "quality_grade", "id": serial(0), "grade": "GY",
                    "reason": "trying anyway"},
              headers=hdrs("Production Incharge"))
    assert r.status_code == 403, r.get_json()


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

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
