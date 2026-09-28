"""
ICON TRACE - Round 34: the Admin > Cancel document screen, end to end.

    python test_cancel_screen.py

Drives the real screen in a browser: pick a type, enter the document, a reason
and an authenticator code, cancel it, and see the result - a success line for
each of the seven types, and a refusal shown with the server's exact reason for
a document that cannot be cancelled.

The TOTP replay guard means one code is good for exactly one cancel, so between
cancels the test re-provisions the account's secret and reads a fresh code -
the same effect an authenticator's next 30-second code would have. Screenshots
land in round34_shots/.
"""

import os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_cnscr_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "round34_shots")
os.makedirs(SHOTS, exist_ok=True)

MODEL = "ISEN630-G12R"
WATT = 630
_n = [2000]


def nxt():
    _n[0] += 1
    return _n[0]


def nserial():
    return "ICON630G120212%04d" % nxt()


LOGIN = "sa.screen"


def seed(kind, blocked=False):
    """Insert one document of `kind` and return its id."""
    with store.conn() as (cx, cur):
        if kind in ("indent", "allocation"):
            iid = store.insert(cur, "indent", {"indent_no": "IND-%d" % nxt(),
                "indent_date": "2026-09-09", "customer": "STOCK", "created_by": "t"})
            lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
                "item_description": "SOLAR PV MODULE", "model": MODEL,
                "wattage": WATT, "qty": 1, "dcr": "DCR"})
            aid = store.insert(cur, "allocation", {"indent_line_id": lid,
                "model": MODEL, "wattage": WATT, "date_produced": "2026-09-09",
                "shift": 1, "qty": 1, "seq_from": 1, "seq_to": 1, "created_by": "t"})
            store.insert(cur, "serial", {"serial": nserial(), "build_instance": 1,
                "model": MODEL, "wattage": WATT, "format_version": 2,
                "date_produced": "2026-09-09", "shift": 1, "sequence": nxt(),
                "alloc_id": aid, "state": "planned"})
            return iid if kind == "indent" else aid
        if kind == "gatepass":
            return store.insert(cur, "gatepass", {"gp_no": "GP-%d" % nxt(),
                "gp_date": "2026-09-09", "kind": "NRGP", "created_by": "t"})
        if kind == "prodentry":
            eid = store.insert(cur, "production_entry", {"prod_date": "2026-09-09",
                "shift": "A", "shift_incharge": "RAJESH", "model": MODEL,
                "wattage": WATT, "start_serial": "S1", "end_serial": "S1",
                "qty": 1, "kw_output": 0.63, "created_by": "t"})
            store.insert(cur, "serial", {"serial": nserial(), "build_instance": 1,
                "model": MODEL, "wattage": WATT, "format_version": 2,
                "date_produced": "2026-09-09", "shift": 1, "sequence": nxt(),
                "prod_entry_id": eid, "state": "produced"})
            return eid
        if kind == "loss_event":
            return store.insert(cur, "loss_event", {"event_date": "2026-09-09",
                "shift": "A", "line": "A-Line", "machine": "LAM-1",
                "reason": "LOP-POWER", "kind": "P", "start_time": "10:00",
                "entry_mode": "Live", "created_by": "t"})
        if kind == "invoice":
            iid = store.insert(cur, "invoice", {"invoice_no": "INV-%d" % nxt(),
                "pdf_path": "x.pdf", "pdf_sha256": "hash%d" % nxt(), "created_by": "t"})
            if blocked:
                store.insert(cur, "challan", {"fy": 2026, "seq": nxt(),
                    "challan_date": "2026-09-09", "qty": 1, "status": "issued",
                    "invoice_id": iid, "created_by": "t"})
            return iid
        if kind == "challan":
            return store.insert(cur, "challan", {"fy": 2026, "seq": nxt(),
                "challan_date": "2026-09-09", "qty": 1, "status": "issued",
                "created_by": "t"})


def fresh_code(pg):
    """A code the replay guard will accept. The guard keys on the TOTP STEP, so
    a second cancel in the same 30-second window is refused however the secret
    is rotated - in real use the admin's authenticator has simply rolled to the
    next 30s code (a higher step). The test simulates that passage by clearing
    totp_last_step, so each cancel presents a never-yet-used code, exactly as a
    real one would across windows."""
    secret = AUTH.provision_totp(LOGIN)
    with store.conn() as (cx, cur):
        cur.execute("UPDATE app_user SET totp_last_step=0 WHERE login_id=%s", (LOGIN,))
    return AUTH.totp_code(secret)


def ui_cancel(pg, type_value, doc_id, reason="admin correction"):
    pg.select_option("#cdType", type_value)
    pg.fill("#cdId", str(doc_id))
    pg.fill("#cdReason", reason)
    pg.fill("#cdTotp", fresh_code(pg))
    pg.click("#cdBtn")


def run():
    store.wipe()
    AUTH.ensure_auth_schema()
    with H.browser() as b:
        ctx = b.new_context(viewport={"width": 1400, "height": 900})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        sid = AUTH.make_session_id(role="Super Admin", login_id=LOGIN)
        ctx.add_cookies([{"name": "icon_sid", "value": sid,
                          "domain": "127.0.0.1", "path": "/"}])
        pg.goto(H.base_url() + "/")
        pg.wait_for_selector("#app.on", timeout=20000)
        pg.evaluate("go('admin')")
        pg.wait_for_timeout(800)
        # open the Cancel document tab (the tab button, not our own Cancel btn)
        pg.click("#v-admin button[onclick*=\"'cancel'\"]")
        pg.wait_for_selector("#cdBtn", timeout=10000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(SHOTS, "01_cancel_screen.png"))

        # one of each type, end to end
        results = []
        for kind in ("indent", "gatepass", "prodentry", "loss_event",
                     "invoice", "challan", "allocation"):
            did = seed(kind)
            ui_cancel(pg, kind, did)
            pg.wait_for_selector("#cdResult .note.n-info", timeout=10000)
            txt = " ".join(pg.inner_text("#cdResult").split())
            results.append((kind, txt[:70]))
            if kind == "invoice":
                pg.screenshot(path=os.path.join(SHOTS, "02_success_invoice.png"))

        # a refusal, shown with the server's exact reason (a blocked invoice)
        blocked = seed("invoice", blocked=True)
        ui_cancel(pg, "invoice", blocked)
        pg.wait_for_selector("#cdResult .note.n-bad", timeout=10000)
        refusal = pg.inner_text("#cdResult")
        pg.screenshot(path=os.path.join(SHOTS, "03_refusal_invoice.png"))

        # a wrong code, shown differently from a wrong-state document
        wrong_id = seed("loss_event")
        pg.select_option("#cdType", "loss_event")
        pg.fill("#cdId", str(wrong_id))
        pg.fill("#cdReason", "x")
        pg.fill("#cdTotp", "000000")
        pg.click("#cdBtn")
        pg.wait_for_selector("#cdResult .note.n-bad", timeout=10000)
        wrongcode = pg.inner_text("#cdResult")
        pg.screenshot(path=os.path.join(SHOTS, "04_wrong_code.png"))

        ctx.close()
        return results, refusal, wrongcode, errs


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    passed = failed = 0
    try:
        results, refusal, wrongcode, errs = run()
        checks = []
        checks.append(("all 7 types cancelled via the screen",
                       len(results) == 7 and all("cancelled" in t.lower() for _, t in results)))
        checks.append(("a blocked invoice refused with its reason on screen",
                       "reconcile against this invoice" in refusal.lower()))
        checks.append(("a wrong code refused, and reads differently from a block",
                       "code" in wrongcode.lower() and "reconcile" not in wrongcode.lower()))
        checks.append(("no page errors", errs == []))
        for name, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + name)
            if ok: passed += 1
            else: failed += 1
        print("\n  types cancelled:")
        for k, t in results:
            print("    %-11s %s" % (k, t))
        print("  refusal shown:   %s" % " ".join(refusal.split())[:90])
        print("  wrong code shown:%s" % " ".join(wrongcode.split())[:90])
        if errs:
            print("  page errors:", errs)
    except Exception as e:
        traceback.print_exc()
        failed += 1
    finally:
        H.cleanup()
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
