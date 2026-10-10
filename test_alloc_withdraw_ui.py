"""
ICON TRACE - Planning's Withdraw button on Recent Allocations, in a real browser.

    python test_alloc_withdraw_ui.py

Withdrawing a batch is a cancel (Round 34): Admin / Super Admin only, a
mandatory reason, the authenticator step-up (DECISIONS.md section 1). The
button used to send a bare DELETE - no reason, no code - so the server refused
every press with "Enter your authenticator code to cancel." and no batch could
be withdrawn from Planning; it was also offered to a Production Incharge, whom
the server refuses outright. So:

  1. a Production Incharge is offered Edit on an editable batch, not Withdraw;
  2. a Super Admin's Withdraw asks for a reason and an authenticator code,
     sends both, and the batch is withdrawn - its serials released, the
     reason on the audit row;
  3. the server refuses a withdrawal with no reason, before the code is spent.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import json, sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_models as models                                 # noqa: E402

APP = H.APP
_results = []
ITEM = [i["item_code"] for i in models.ITEMS
        if i["model"] == "ISEN625-G12R" and i["cell_type"] == "NDCR"][0]
SERIALS = ["ICON625R12A0910%03d" % q for q in range(1, 6)]


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def seed():
    """One indent, one five-serial batch nobody has produced yet."""
    store.wipe()
    c = APP.app.test_client()
    AUTH.test_login(c)
    assert c.post("/api/indent", json={"indent_no": "OCT-09/2026", "indent_date": "2026-10-09",
        "customer": "ICON Stock", "items": [{"item_code": ITEM, "qty": 20}]}).get_json()["ok"]
    with store.conn() as (cx, cur):
        lid = store.one(cur, "SELECT indent_line_id FROM indent_line")["indent_line_id"]
    r = c.post("/api/allocation", json={"indent_line_id": lid, "qty": 5,
                                        "serials": SERIALS, "materials": []}).get_json()
    assert r["ok"], r
    return c, r["alloc_id"]


def batch_buttons(pg):
    pg.evaluate("go('plan')")
    pg.wait_for_selector("#allocCard tbody tr td", timeout=10000)
    pg.wait_for_timeout(500)
    return pg.eval_on_selector_all("#allocCard tbody tr:first-child button",
                                   "els => els.map(e => e.textContent.trim())")


@test("a Production Incharge is offered Edit on an editable batch, not Withdraw "
      "(the server refuses that role); a Super Admin is offered both")
def t_button_visibility():
    seed()
    with H.browser() as b:
        pg = H.open_page(b, role="Production Incharge", login_id="inc.ui")
        got = batch_buttons(pg)
        assert "Edit" in got and "Withdraw" not in got, got
        assert not pg.errors, pg.errors
        pg2 = H.open_page(b, role="Super Admin", login_id="sa.view")
        got = batch_buttons(pg2)
        assert "Edit" in got and "Withdraw" in got, got


@test("a Super Admin's Withdraw asks for a reason and an authenticator code, "
      "sends both, and the batch is withdrawn with the reason recorded")
def t_withdraw_works():
    c, aid = seed()
    with H.browser() as b:
        AUTH.make_user(role="Super Admin", login_id="sa.ui")
        secret = AUTH.provision_totp("sa.ui")
        pg = H.open_page(b, role="Super Admin", login_id="sa.ui")
        pg.evaluate("""(answers) => { window.__prompts = []; window.__answers = answers;
            window.prompt = (m) => { window.__prompts.push(String(m)); return window.__answers.shift(); }; }""",
                    ["wrong indent item", AUTH.totp_code(secret)])
        batch_buttons(pg)
        pg.click("#allocCard tbody tr:first-child button:has-text('Withdraw')")
        pg.wait_for_timeout(1500)
        prompts = pg.evaluate("() => window.__prompts")
        assert len(prompts) == 2 and "Reason" in prompts[0] and \
            "authenticator" in prompts[1].lower(), prompts
        assert not pg.errors, pg.errors
    with store.conn() as (cx, cur):
        a = store.one(cur, "SELECT COUNT(*) AS n FROM allocation WHERE alloc_id=%s", (aid,))
        s = store.one(cur, "SELECT COUNT(*) AS n FROM serial")
        log = store.one(cur, "SELECT * FROM dispatch_audit WHERE action='planning.cancel'")
    assert a["n"] == 0 and s["n"] == 0, (a["n"], s["n"])
    assert log and json.loads(log["detail"])["reason"] == "wrong indent item", dict(log or {})


@test("the server refuses a withdrawal with no reason - before the code is spent")
def t_reason_required():
    c, aid = seed()
    info = AUTH.test_login(c, role="Admin", login_id="adm.api")
    secret = AUTH.provision_totp(info["login_id"])
    code = AUTH.totp_code(secret)
    for body in ({"totp_code": code}, {"reason": "  ", "totp_code": code}):
        r = c.delete("/api/allocation/%d" % aid, json=body)
        assert r.status_code == 400 and "reason is required" in r.get_json()["why"], r.get_json()
    # the same code still works: the blank reason did not spend it
    r = c.delete("/api/allocation/%d" % aid, json={"reason": "duplicate batch", "totp_code": code})
    assert r.status_code == 200, r.get_json()


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
