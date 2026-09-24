"""
ICON TRACE - Round 27, section 2: the six inline _require_role checks,
still refusing a wrong role after the outer gate moved onto per-screen
write flags.

    python test_inner_role_checks.py

Each actor here has write on the endpoint's screen - asserted, not
assumed - so the outer gate lets it in, and only the inner check can be
what refuses it. The refusal asserted is the inner check's own wording,
never the outer gate's "Not permitted for your role.".

    1  api_review_resolve, quality_grade      _QUALITY_ROLES
    2  _resolve_duplicate_scan, not dispatched _INCHARGE_ROLES
    3  _resolve_duplicate_scan, dispatched     "Admin"
    4  _resolve_provisional_mismatch          _QUALITY_ROLES
    5  /admin/challan-import, action=load      _R_MASTER
    6  /settings, POST                         _R_MASTER
"""

import csv, datetime, os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_inner_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_auth                                             # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


_GATE_403 = "Not permitted for your role."


def gate_refused(r):
    return r.status_code == 403 and \
        (r.get_json(silent=True) or {}).get("why") == _GATE_403


def set_perm(login_id, screen, view, write):
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, "cli", login_id,
                                   {screen: {"view": view, "write": write}})


def write_flag(login_id, screen):
    with store.conn() as (cx, cur):
        return icon_auth.get_screen_perms(cur, login_id)[screen]["write"]


def fresh():
    store.wipe()
    AUTH.ensure_auth_schema()


WATT, MODEL = 625, "ISEN625-G12R"
SS = os.path.join(TMP, "ss.csv")
EL_OK = os.path.join(TMP, "el", "OK")
os.makedirs(EL_OK, exist_ok=True)


def serial(i):
    return "ICON625R129071%04d" % i


def ss_row(sid, at, pmax):
    return [at, sid, pmax, "12.1", "48.9", "11.8", "52.5", "96.1", "0.41",
            "0.4", "210.0", "23.1", "25", "25", "1000"]


def add_rescan_row(i, at, pmax):
    with open(SS, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    rows.append(ss_row(serial(i), at, pmax))
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def setup(n=4):
    fresh()
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(
            [ss_row(serial(i), "2026-09-09 10:%02d:00" % i, "630.5")
             for i in range(n)])
    for i in range(n):
        open(os.path.join(EL_OK, serial(i) + ".jpg"), "w").close()
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
    c = APP.app.test_client()
    AUTH.test_login(c)
    return c


def pass_and_pack(c, i):
    AUTH.test_login(c)
    r = c.post("/api/fqc", json={"serial": serial(i), "outcome": "pass"})
    assert r.status_code == 200, r.get_json()
    b = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                      "capacity": 1}).get_json()
    assert c.post("/api/box/%d/scan" % b["box_id"],
                  json={"serial": serial(i)}).status_code == 200
    assert c.post("/api/box/%d/close" % b["box_id"], json={}).status_code == 200
    return b["box_id"]


def dispatch_one(c, i):
    bid = pass_and_pack(c, i)
    with store.conn() as (cx, cur):
        inv = db.insert_invoice(cur, {
            "buyer_name": "Agni Solar", "buyer_gstin": "22AAAAA0000A1Z5",
            "declared_qty": 1, "declared_model": MODEL, "ewb_no": "111122223333",
            "ewb_valid_upto": (datetime.date.today() +
                               datetime.timedelta(days=10)).isoformat(),
            "invoice_no": "INV-SCRGATE-%d" % i, "irn": None,
            "consignee_same_as_buyer": 1}, "t.pdf", "feed%d" % i,
            {"fields": {}, "compare_only": {}, "qr": {}}, False, {}, "tester")
    r = c.post("/api/challan", json={"action": "draft", "boxes": [bid],
                                     "invoice_id": inv})
    assert r.status_code == 200, r.get_json()
    r = c.post("/api/challan/%d/submit" % r.get_json()["challan_id"], json={})
    assert r.status_code == 200, r.get_json()


def duplicate_scan(c, i):
    add_rescan_row(i, "2026-09-09 12:00:00", "600.0")
    AUTH.test_login(c, role="FQC Operator")
    d = c.post("/api/fqc", json={"serial": serial(i), "outcome": "reject"}).get_json()
    assert d.get("duplicate_scan") and d.get("agree") is False, d
    return d["review_id"]


def review_status(rid):
    with store.conn() as (cx, cur):
        return db.review_item_get(cur, rid)["status"]


def as_role_with_review_write(c, role):
    """A real session in `role`, with its write flag on Needs Review
    asserted True - the outer gate is open to it, so only the inner check
    can be what refuses it."""
    me = AUTH.test_login(c, role=role)["login_id"]
    set_perm(me, "review", True, True)
    assert write_flag(me, "review") is True
    return me


def inner_refused(r, why_start):
    body = r.get_json(silent=True) or {}
    assert r.status_code == 403, (r.status_code, body)
    assert body.get("why", "").startswith(why_start), body
    assert body.get("why") != _GATE_403, "refused by the outer gate, not the inner check"
    print("      403 %s" % body["why"])


@test("inner 1 (quality_grade, _QUALITY_ROLES): Production Incharge has "
     "write on Needs Review and is still refused a quality decision")
def t_inner_quality_grade():
    c = setup()
    AUTH.test_login(c)
    assert c.post("/api/fqc", json={"serial": serial(0), "outcome": "reject",
                  "reason": "OV-QUALITY — quality engineer instruction"}
                  ).status_code == 200
    as_role_with_review_write(c, "Production Incharge")
    r = c.post("/api/review/resolve", json={"type": "quality_grade",
               "id": serial(0), "grade": "GY", "reason": "trying anyway"})
    inner_refused(r, "Only Quality can resolve a quality decision.")
    as_role_with_review_write(c, "Quality")
    r = c.post("/api/review/resolve", json={"type": "quality_grade",
               "id": serial(0), "grade": "GY", "reason": "graded by Quality"})
    assert r.status_code == 200, r.get_json()


@test("inner 2 (duplicate scan, _INCHARGE_ROLES): Quality and FQC Operator "
     "have write on Needs Review and are still refused a duplicate scan")
def t_inner_incharge_duplicate():
    c = setup()
    pass_and_pack(c, 1)
    rid = duplicate_scan(c, 1)
    body = {"type": "duplicate_scan", "id": rid, "resolution": "keep_original",
            "reason": "trying anyway"}
    for role in ("Quality", "FQC Operator"):
        as_role_with_review_write(c, role)
        inner_refused(c.post("/api/review/resolve", json=body),
                      "Only a Production Shift Incharge or above")
    assert review_status(rid) == "open"
    as_role_with_review_write(c, "Production Incharge")
    assert c.post("/api/review/resolve", json=body).status_code == 200


@test("inner 3 (dispatched duplicate scan, Admin alone): Production "
     "Incharge has write on Needs Review and is still refused")
def t_inner_dispatched_duplicate():
    c = setup()
    dispatch_one(c, 0)
    rid = duplicate_scan(c, 0)
    body = {"type": "duplicate_scan", "id": rid, "resolution": "keep_original",
            "reason": "trying anyway"}
    as_role_with_review_write(c, "Production Incharge")
    inner_refused(c.post("/api/review/resolve", json=body),
                  "Only Admin can resolve a conflict on a serial that has "
                  "already been dispatched.")
    assert review_status(rid) == "open"


@test("inner 4 (provisional mismatch, _QUALITY_ROLES): Production Incharge "
     "and FQC Operator have write on Needs Review and are still refused")
def t_inner_provisional_mismatch():
    c = setup()
    AUTH.test_login(c)
    assert c.post("/api/fqc", json={"serial": serial(2), "outcome": "pass"}
                  ).status_code == 200
    with store.conn() as (cx, cur):
        f = store.one(cur, "SELECT fqc_id FROM fqc_record WHERE serial=%s",
                      (serial(2),))
        rid = db.create_review_item(cur, "provisional_mismatch", serial(2),
                                    fqc_id=f["fqc_id"], new_fqc_id=f["fqc_id"],
                                    created_by="system")
    body = {"type": "provisional_mismatch", "id": rid,
            "resolution": "keep_decision", "reason": "trying anyway"}
    for role in ("Production Incharge", "FQC Operator"):
        as_role_with_review_write(c, role)
        inner_refused(c.post("/api/review/resolve", json=body),
                      "Only Quality can resolve a provisional decision")
    assert review_status(rid) == "open"


@test("inner 5 and 6 (challan-import LOAD and the /settings form, "
     "_R_MASTER): an Admin passes the outer gate and is still refused")
def t_inner_master_checks():
    fresh()
    c = APP.app.test_client()
    AUTH.test_login(c, role="Admin")
    r = c.post("/admin/challan-import", data={"action": "load"})
    assert r.status_code == 403, r.status_code
    assert b"Only a Super Admin can load an" in r.data
    print("      403 /admin/challan-import load")
    r = c.post("/settings", data={"grade_b_min": "271"})
    assert r.status_code == 403, r.status_code
    assert b"Only a Super Admin can change" in r.data
    print("      403 /settings POST")


@test("a RIGHT role with its screen write withdrawn is refused at the door - "
     "the inner role check is additional to the screen gate, never instead")
def t_right_role_without_flag():
    c = setup()
    AUTH.test_login(c)
    assert c.post("/api/fqc", json={"serial": serial(0), "outcome": "reject",
                  "reason": "OV-QUALITY — quality engineer instruction"}
                  ).status_code == 200
    me = AUTH.test_login(c, role="Quality")["login_id"]
    set_perm(me, "review", True, False)
    r = c.post("/api/review/resolve", json={"type": "quality_grade",
               "id": serial(0), "grade": "GY", "reason": "graded by Quality"})
    assert gate_refused(r), (r.status_code, r.get_json())


# --------------------------------------------------------------------------

if __name__ == "__main__":
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    for name, fn in _results:
        try:
            fn()
            print("  PASS  %-*s" % (width, name))
            passed += 1
        except Exception as e:
            print("  FAIL  %-*s  %s" % (width, name, e))
            traceback.print_exc()
            failed += 1
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
