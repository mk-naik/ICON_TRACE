"""
ICON TRACE - Round 34: direct cancellation of every document type.

    python test_cancel_documents.py

Admin/Super Admin may cancel every document type directly, with a TOTP step-up
at submit. No request/approve, no hierarchy, no other role - that is a later
feature. This pins the whole matrix for all seven cancel endpoints:

    right role + right code + cancellable   -> 200, status flips, audit written
    wrong role                              -> 403 BEFORE the code is checked
    right role + wrong code                 -> 403, document untouched
    right role + right code + NOT cancellable -> 400 with its specific reason,
                                              document untouched
    a code already used                     -> 403 (the replay guard)

The step-up runs BEFORE the type-specific refusal, on purpose: a wrong code and
a wrong-state document both come back as a refusal a prober cannot tell apart at
the network level - only the reason differs, and only for a caller who already
passed the role gate and the code.

Challan and allocation are the two that already existed; their refusal RULES
(issued-only, all-serials-planned) are unchanged here - only who may call them
(Admin/Super Admin) and the added TOTP step are new.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_cancel_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import db                                                    # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


MODEL = "ISEN630-G12R"
WATT = 630
_n = [1000]


def nxt():
    _n[0] += 1
    return _n[0]


def nserial():
    return "ICON630G120212%04d" % nxt()


# --------------------------------------------------------------------------
# accounts: a Super Admin (with a real TOTP secret) and a non-admin
# --------------------------------------------------------------------------

def accounts():
    store.wipe()
    AUTH.ensure_auth_schema()
    admin = APP.app.test_client()
    info = AUTH.test_login(admin, role="Super Admin", login_id="sa.cancel")
    secret = AUTH.provision_totp(info["login_id"])
    op = APP.app.test_client()
    AUTH.test_login(op, role="Dispatch Operator", login_id="op.cancel")
    return admin, secret, op


def code(secret):
    return AUTH.totp_code(secret)


def cancel(client, spec, **body):
    """POST /cancel for every type except allocation, which is a DELETE on the
    allocation itself (its withdrawal predates this round and keeps its verb)."""
    if spec["method"] == "DELETE":
        return client.delete(spec["url"], json=body)
    return client.post(spec["url"], json=body)


def row_of(spec):
    if spec["table"] is None:
        return None
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT * FROM %s WHERE %s=%%s"
                         % (spec["table"], spec["pk"]), (spec["id"],))


def audit_has(action, entity_id):
    with store.conn() as (cx, cur):
        r = store.one(cur, "SELECT * FROM dispatch_audit WHERE action=%s "
                      "AND entity_id=%s", (action, str(entity_id)))
        return r


# --------------------------------------------------------------------------
# one factory per type: a cancellable doc, or one blocked by a real downstream
# --------------------------------------------------------------------------

def _seed_indent_line_alloc(cur, serial_state):
    iid = store.insert(cur, "indent", {"indent_no": "IND-%d" % nxt(),
        "indent_date": "2026-09-09", "customer": "STOCK", "created_by": "t"})
    lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
        "item_description": "SOLAR PV MODULE", "model": MODEL, "wattage": WATT,
        "qty": 1, "dcr": "DCR"})
    aid = store.insert(cur, "allocation", {"indent_line_id": lid, "model": MODEL,
        "wattage": WATT, "date_produced": "2026-09-09", "shift": 1, "qty": 1,
        "seq_from": 1, "seq_to": 1, "created_by": "t"})
    store.insert(cur, "serial", {"serial": nserial(), "build_instance": 1,
        "model": MODEL, "wattage": WATT, "format_version": 2,
        "date_produced": "2026-09-09", "shift": 1, "sequence": nxt(),
        "alloc_id": aid, "state": serial_state})
    return iid, lid, aid


def mk_indent(blocked=False):
    with store.conn() as (cx, cur):
        iid, _, _ = _seed_indent_line_alloc(cur, "produced" if blocked else "planned")
    return {"url": "/api/indent/%d/cancel" % iid, "method": "POST",
            "table": "indent", "pk": "indent_id", "id": iid,
            "action": "indent.cancel", "reason_sub": "through production"}


def mk_allocation(blocked=False):
    with store.conn() as (cx, cur):
        _, _, aid = _seed_indent_line_alloc(cur, "graded" if blocked else "planned")
    return {"url": "/api/allocation/%d" % aid, "method": "DELETE",
            "table": "allocation", "pk": "alloc_id", "id": aid,
            "action": "planning.cancel", "reason_sub": "through production",
            "deletes": True}


def mk_gatepass(blocked=False):
    with store.conn() as (cx, cur):
        gid = store.insert(cur, "gatepass", {"gp_no": "GP-%d" % nxt(),
            "gp_date": "2026-09-09", "kind": "NRGP", "created_by": "t"})
    return {"url": "/api/gatepass/%d/cancel" % gid, "method": "POST",
            "table": "gatepass", "pk": "gp_id", "id": gid,
            "action": "gatepass.cancel", "reason_sub": None}   # no blocked state


def mk_prodentry(blocked=False):
    with store.conn() as (cx, cur):
        eid = store.insert(cur, "production_entry", {"prod_date": "2026-09-09",
            "shift": "A", "shift_incharge": "RAJESH", "model": MODEL,
            "wattage": WATT, "start_serial": "S1", "end_serial": "S1", "qty": 1,
            "kw_output": 0.63, "created_by": "t"})
        store.insert(cur, "serial", {"serial": nserial(), "build_instance": 1,
            "model": MODEL, "wattage": WATT, "format_version": 2,
            "date_produced": "2026-09-09", "shift": 1, "sequence": nxt(),
            "prod_entry_id": eid, "state": "graded" if blocked else "produced"})
    return {"url": "/api/prodentry/%d/cancel" % eid, "method": "POST",
            "table": "production_entry", "pk": "entry_id", "id": eid,
            "action": "production_entry.cancel", "reason_sub": "FQC or beyond"}


def mk_loss(blocked=False):
    with store.conn() as (cx, cur):
        pid = store.insert(cur, "loss_event", {"event_date": "2026-09-09",
            "shift": "A", "line": "A-Line", "machine": "LAM-1",
            "reason": "LOP-POWER", "kind": "P", "start_time": "10:00",
            "entry_mode": "Live", "created_by": "t"})
        if blocked:
            store.insert(cur, "loss_event", {"event_date": "2026-09-09",
                "shift": "A", "line": "A-Line", "machine": "LAM-1",
                "reason": "LOP-INDUCED", "kind": "I", "linked_event_id": pid,
                "start_time": "10:05", "entry_mode": "Live", "created_by": "t"})
    return {"url": "/api/loss_event/%d/cancel" % pid, "method": "POST",
            "table": "loss_event", "pk": "event_id", "id": pid,
            "action": "loss_event.cancel", "reason_sub": "induced"}


def mk_invoice(blocked=False):
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "invoice", {"invoice_no": "INV-%d" % nxt(),
            "pdf_path": "x.pdf", "pdf_sha256": "deadbeef%d" % nxt(), "created_by": "t"})
        if blocked:
            store.insert(cur, "challan", {"fy": 2026, "seq": nxt(),
                "challan_date": "2026-09-09", "qty": 1, "status": "issued",
                "invoice_id": iid, "created_by": "t"})
    return {"url": "/api/invoice/%d/cancel" % iid, "method": "POST",
            "table": "invoice", "pk": "invoice_id", "id": iid,
            "action": "invoice.cancel", "reason_sub": "reconcile against this invoice"}


def mk_challan(blocked=False):
    with store.conn() as (cx, cur):
        cid = store.insert(cur, "challan", {"fy": 2026, "seq": nxt(),
            "challan_date": "2026-09-09", "qty": 1, "status": "issued", "created_by": "t"})
        if blocked:
            store.insert(cur, "gatepass", {"gp_no": "GP-%d" % nxt(),
                "gp_date": "2026-09-09", "kind": "NRGP", "created_by": "t",
                "challan_id": cid})
    return {"url": "/api/challan/%d/cancel" % cid, "method": "POST",
            "table": "challan", "pk": "challan_id", "id": cid,
            "action": "challan.cancel", "reason_sub": "gate pass"}


TYPES = [("indent", mk_indent), ("gatepass", mk_gatepass),
         ("prodentry", mk_prodentry), ("loss_event", mk_loss),
         ("invoice", mk_invoice), ("challan", mk_challan),
         ("allocation", mk_allocation)]


# --------------------------------------------------------------------------
# the matrix
# --------------------------------------------------------------------------

@test("right role + right code + cancellable state: every one of the 7 succeeds, "
     "status flips (allocation deletes, its own way), audit written with the "
     "real actor and reason")
def t_success():
    for name, mk in TYPES:
        admin, secret, op = accounts()
        spec = mk(blocked=False)
        r = cancel(admin, spec, reason="round-34 %s" % name, totp_code=code(secret))
        assert r.status_code == 200, (name, r.status_code, r.get_json())
        if spec.get("deletes"):
            assert row_of(spec) is None, "%s: row not removed" % name
        else:
            row = row_of(spec)
            assert row["status"] == "cancelled", "%s: status not flipped" % name
            assert row["cancelled_by"] == "Test Super Admin", (name, row["cancelled_by"])
            assert (row["cancelled_reason"] or "").startswith("round-34"), name
        a = audit_has(spec["action"], spec["id"])
        assert a is not None, "%s: no audit row" % name
        assert a["actor"] == "Test Super Admin", (name, a["actor"])
    print("      all 7 cancelled; status flipped / deleted; audit written")


@test("wrong role is refused BEFORE the code is checked - a valid code would "
     "not help, and the reason is the role reason, never the TOTP one")
def t_wrong_role_before_totp():
    for name, mk in TYPES:
        admin, secret, op = accounts()
        spec = mk(blocked=False)
        # a non-admin, sending a PERFECTLY VALID code, is still refused
        r = cancel(op, spec, reason="x", totp_code=code(secret))
        assert r.status_code == 403, (name, r.status_code, r.get_json())
        why = r.get_json()["why"].lower()
        assert "role" in why, "%s: not the role refusal: %r" % (name, why)
        assert "code" not in why, "%s: leaked a TOTP reason to a wrong role" % name
        # untouched
        if not spec.get("deletes"):
            assert row_of(spec)["status"] != "cancelled", name
        else:
            assert row_of(spec) is not None, name
    print("      all 7 refused on role before TOTP, even with a valid code")


@test("right role + wrong code: refused, document untouched, on every type")
def t_wrong_code():
    for name, mk in TYPES:
        admin, secret, op = accounts()
        spec = mk(blocked=False)
        r = cancel(admin, spec, reason="x", totp_code="000000")
        assert r.status_code == 403, (name, r.status_code, r.get_json())
        assert "code" in r.get_json()["why"].lower(), (name, r.get_json())
        if not spec.get("deletes"):
            assert row_of(spec)["status"] != "cancelled", name
        else:
            assert row_of(spec) is not None, "%s: deleted on a wrong code" % name
    print("      all 7 refused on a wrong code; documents untouched")


@test("right role + right code + NOT cancellable: refused with the type's own "
     "specific reason, document untouched (gate pass has no such state)")
def t_blocked_reason():
    for name, mk in TYPES:
        if name == "gatepass":
            continue                       # no downstream state blocks it
        admin, secret, op = accounts()
        spec = mk(blocked=True)
        r = cancel(admin, spec, reason="x", totp_code=code(secret))
        assert r.status_code == 400, (name, r.status_code, r.get_json())
        why = r.get_json()["why"].lower()
        assert spec["reason_sub"].lower() in why, \
            "%s: reason %r not in %r" % (name, spec["reason_sub"], why)
        if not spec.get("deletes"):
            assert row_of(spec)["status"] != "cancelled", name
        else:
            assert row_of(spec) is not None, "%s: deleted despite block" % name
    print("      6 blocked with their specific reason; documents untouched")


@test("gate pass has no downstream state - it cancels even when linked to a "
     "live challan (the intended way to release the challan's lock)")
def t_gatepass_unconditional():
    admin, secret, op = accounts()
    with store.conn() as (cx, cur):
        cid = store.insert(cur, "challan", {"fy": 2026, "seq": nxt(),
            "challan_date": "2026-09-09", "qty": 1, "status": "issued", "created_by": "t"})
        gid = store.insert(cur, "gatepass", {"gp_no": "GP-%d" % nxt(),
            "gp_date": "2026-09-09", "kind": "NRGP", "created_by": "t",
            "challan_id": cid})
    r = admin.post("/api/gatepass/%d/cancel" % gid,
                   json={"reason": "released", "totp_code": code(secret)})
    assert r.status_code == 200, r.get_json()
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT status FROM gatepass WHERE gp_id=%s",
                         (gid,))["status"] == "cancelled"
    print("      a challan-linked gate pass cancelled unconditionally")


@test("the replay guard: a code that cancelled one document is refused on the "
     "next, exactly as a code used to sign in would be")
def t_replay_guard():
    admin, secret, op = accounts()
    s1 = mk_indent(blocked=False)
    s2 = mk_invoice(blocked=False)
    c = code(secret)
    r1 = cancel(admin, s1, reason="first", totp_code=c)
    assert r1.status_code == 200, r1.get_json()
    r2 = cancel(admin, s2, reason="replay", totp_code=c)
    assert r2.status_code == 403, "a replayed code was accepted"
    assert "code" in r2.get_json()["why"].lower()
    assert row_of(s2)["status"] != "cancelled", "replay still cancelled the second"
    print("      a reused code cancelled the first, was refused on the second")


@test("the lookup resolves the number a person actually knows to its internal "
     "id and current state - an indent no, a gate pass no, an invoice no, a "
     "rendered challan no - and a bare id; unknown -> 404, non-admin -> 403")
def t_lookup_resolves_reference():
    admin, secret, op = accounts()
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "IS2I/26/0003",
            "indent_date": "2026-09-09", "customer": "STOCK", "created_by": "t"})
        gid = store.insert(cur, "gatepass", {"gp_no": "IS2-GP-77",
            "gp_date": "2026-09-09", "kind": "NRGP", "created_by": "t"})
        inv = store.insert(cur, "invoice", {"invoice_no": "INV-9001",
            "pdf_path": "x.pdf", "pdf_sha256": "h1", "created_by": "t"})
        cid = store.insert(cur, "challan", {"fy": 2026, "seq": 4242,
            "challan_date": "2026-09-09", "qty": 1, "status": "issued",
            "created_by": "t"})
    # by the human number
    d = admin.get("/api/cancel/lookup?type=indent&ref=IS2I/26/0003").get_json()
    assert d["ok"] and d["id"] == iid and "/api/indent/%d/cancel" % iid == d["cancel_url"], d
    assert admin.get("/api/cancel/lookup?type=gatepass&ref=IS2-GP-77").get_json()["id"] == gid
    assert admin.get("/api/cancel/lookup?type=invoice&ref=INV-9001").get_json()["id"] == inv
    # a rendered challan number (IS-09.09.2026/4242), which has no stored column
    import datetime as _dt
    rendered = db.render_challan_no(_dt.date(2026, 9, 9), 4242, None)
    dc = admin.get("/api/cancel/lookup?type=challan&ref=" + rendered).get_json()
    assert dc["ok"] and dc["id"] == cid, (rendered, dc)
    assert dc["method"] == "POST"
    # a bare numeric id still resolves
    assert admin.get("/api/cancel/lookup?type=indent&ref=%d" % iid).get_json()["id"] == iid
    # allocation resolves by id and reports a DELETE
    with store.conn() as (cx, cur):
        _, _, aid = _seed_indent_line_alloc(cur, "planned")
    da = admin.get("/api/cancel/lookup?type=allocation&ref=%d" % aid).get_json()
    assert da["ok"] and da["method"] == "DELETE" and da["id"] == aid, da
    # unknown -> 404, unknown type -> 400
    assert admin.get("/api/cancel/lookup?type=indent&ref=NOPE").status_code == 404
    assert admin.get("/api/cancel/lookup?type=nonsense&ref=1").status_code == 400
    # non-admin cannot even resolve
    assert op.get("/api/cancel/lookup?type=indent&ref=IS2I/26/0003").status_code == 403
    print("      lookup resolves numbers, rendered challan no, ids; gates by role")


@test("no code at all is refused (400) - the step-up is not optional")
def t_missing_code():
    admin, secret, op = accounts()
    spec = mk_loss(blocked=False)
    r = admin.post(spec["url"], json={"reason": "no code"})
    assert r.status_code == 400, r.get_json()
    assert "authenticator" in r.get_json()["why"].lower()
    assert row_of(spec)["status"] != "cancelled"
    print("      a cancel with no code is refused before anything else")


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
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
