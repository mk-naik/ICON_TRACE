"""
ICON TRACE - the Cancel button on an issued challan, in a real browser.

    python test_challan_cancel_ui.py

Cancelling an ISSUED challan is Admin / Super Admin only (DECISIONS.md
section 3). The server is the real gate - test_challan.py proves it - and the
button is only a convenience, so:

  1. a Dispatch Operator opening an issued challan is NOT offered Cancel (Edit
     and Verify loading are still there);
  2. an Admin is offered it; it asks for a reason and an authenticator code,
     sends both, and the challan is cancelled with serials back to packed.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def seed():
    """One issued challan holding one dispatched serial, no gate pass."""
    store.wipe()
    with store.conn() as (cx, cur):
        cid = store.insert(cur, "challan", {"fy": 2026, "seq": 701, "challan_date": "2026-10-01",
            "qty": 1, "status": "issued", "created_by": "t", "buyer_name": "Borosil Renewables Limited"})
        store.insert(cur, "serial", {"serial": "ICON625R1293010001", "build_instance": 1,
            "model": "ISEN625-G12R", "wattage": 625, "customer": "STOCK", "dcr": "NDCR",
            "format_version": 2, "date_produced": "2026-10-01", "shift": 1, "sequence": 1,
            "state": "dispatched", "grade": "A"})
        store.insert(cur, "challan_serial", {"challan_id": cid, "serial": "ICON625R1293010001",
            "build_instance": 1, "format_version": 2, "date_produced": "2026-10-01",
            "shift": 1, "sequence": 1, "wattage": 625})
    return cid


def open_detail(pg, cid):
    pg.evaluate("go('challan-list')")
    pg.wait_for_timeout(800)
    pg.evaluate("clOpenDetail(%d)" % cid)
    pg.wait_for_selector("#clDetailCard button", timeout=8000)
    pg.wait_for_timeout(300)


def buttons(pg):
    return pg.eval_on_selector_all("#clDetailCard button", "els => els.map(e => e.textContent.trim())")


@test("a Dispatch Operator is not offered Cancel on an issued challan (Edit is "
      "still there); an Admin is")
def t_button_visibility():
    cid = seed()
    with H.browser() as b:
        pg = H.open_page(b, role="Dispatch Operator", login_id="disp.ui")
        open_detail(pg, cid)
        got = buttons(pg)
        assert "Edit" in got and "Cancel" not in got, got
        assert not pg.errors, pg.errors
        pg2 = H.open_page(b, role="Admin", login_id="admin.ui")
        open_detail(pg2, cid)
        got = buttons(pg2)
        assert "Edit" in got and "Cancel" in got, got


@test("an Admin's Cancel asks for a reason and an authenticator code, and the "
      "challan is cancelled with its serials back to packed")
def t_admin_cancel_works():
    cid = seed()
    with H.browser() as b:
        AUTH.make_user(role="Super Admin", login_id="sa.ui")
        secret = AUTH.provision_totp("sa.ui")
        pg = H.open_page(b, role="Super Admin", login_id="sa.ui")
        pg.evaluate("""(answers) => { window.__prompts = []; window.__answers = answers;
            window.prompt = (m) => { window.__prompts.push(String(m)); return window.__answers.shift(); }; }""",
                    ["wrong consignee", AUTH.totp_code(secret)])
        open_detail(pg, cid)
        pg.click("#clDetailCard button:has-text('Cancel')")
        pg.wait_for_timeout(1500)
        prompts = pg.evaluate("() => window.__prompts")
        assert len(prompts) == 2 and "Reason" in prompts[0] and "authenticator" in prompts[1].lower(), prompts
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        ch = store.one(cur, "SELECT status, cancelled_reason FROM challan WHERE challan_id=%s", (cid,))
        s = store.one(cur, "SELECT state FROM serial WHERE serial='ICON625R1293010001'")
    assert ch["status"] == "cancelled" and ch["cancelled_reason"] == "wrong consignee", dict(ch)
    assert s["state"] == "packed", dict(s)


@test("the Cancel button reports what the server answered: a wrong code is "
      "refused with its reason and the panel stays; a cancel says cancelled and "
      "refreshes the list - it used to say 'Failed: Unexpected token' for both "
      "(audit 9 Oct)")
def t_cancel_reports_the_answer():
    cid = seed()
    with H.browser() as b:
        AUTH.make_user(role="Super Admin", login_id="sa.ui2")
        secret = AUTH.provision_totp("sa.ui2")
        pg = H.open_page(b, role="Super Admin", login_id="sa.ui2")
        pg.evaluate("""() => { window.__t = []; var o = window.toast;
            window.toast = (m) => { window.__t.push(String(m)); return o(m); }; }""")
        hook = """(answers) => { window.__answers = answers;
            window.prompt = () => window.__answers.shift(); }"""
        pg.evaluate(hook, ["wrong consignee", "000000"])
        open_detail(pg, cid)
        pg.click("#clDetailCard button:has-text('Cancel')")
        pg.wait_for_timeout(1500)
        said = pg.evaluate("() => window.__t")
        assert any("not cancelled" in m and "not accepted" in m for m in said), said
        assert pg.is_visible("#clDetailCard"), "the panel closed on a refusal"
        with store.conn() as (cx, cur):
            assert store.one(cur, "SELECT status FROM challan WHERE challan_id=%s",
                             (cid,))["status"] == "issued"
        pg.evaluate("() => { window.__t = []; }")
        pg.evaluate(hook, ["wrong consignee", AUTH.totp_code(secret)])
        pg.click("#clDetailCard button:has-text('Cancel')")
        pg.wait_for_timeout(1500)
        said = pg.evaluate("() => window.__t")
        assert any("cancelled" in m and "Failed" not in m for m in said), said
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT status FROM challan WHERE challan_id=%s",
                         (cid,))["status"] == "cancelled"


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
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
    sys.exit(1 if failed else 0)
