"""
ICON TRACE - Planning's "Validate only" asks the server, and writes nothing.

    python test_plan_validate_ui.py      (the last two need Playwright)

It toasted "Validated. N serials ready - nothing written yet." from two
checks of its own (the range's shape, a customer) while Load into master
could still be refused - a serial the master already has, more than the line
has left, a removed material (overnight audit, 24 Oct 2026). It now sends
exactly what Load into master sends, with validate_only, and the server
answers every refusal it would meet without writing a row.

ui_harness is imported FIRST: it fixes the throwaway database path.
"""

import sys, traceback

import ui_harness as H                                       # noqa: E402  (first: sets the DB path)
import test_custom_serials as T                              # noqa: E402  (an ICON indent + a custom one)
import test_custom_serials_ui as U                           # noqa: E402  (pick, open_plan, fill_bom)
import store                                                 # noqa: E402

RANGE = ["ICON625R1292910001", "ICON625R1292910002", "ICON625R1292910003"]
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def counts():
    with store.conn() as (cx, cur):
        return (store.one(cur, "SELECT COUNT(*) AS n FROM allocation")["n"],
                store.one(cur, "SELECT COUNT(*) AS n FROM serial")["n"])


@test("validate_only answers what Load into master would - accepted, or refused "
      "with the reason - and writes nothing either way")
def t_server():
    c, _custom, line = T.world()
    r = T.allocate(c, line, RANGE, validate_only=True)
    assert r.status_code == 200 and r.get_json().get("validated") is True, r.get_json()
    assert counts() == (0, 0), counts()
    assert T.allocate(c, line, RANGE[1:2]).status_code == 200      # a real one
    r = T.allocate(c, line, RANGE, validate_only=True)
    assert r.status_code == 400 and RANGE[1] in r.get_json()["why"], r.get_json()
    assert counts() == (1, 1), counts()
    # an edit asks the same question the same way
    with store.conn() as (cx, cur):
        aid = store.one(cur, "SELECT alloc_id FROM allocation")["alloc_id"]
    r = c.put("/api/allocation/%d/update" % aid, json={
        "indent_line_id": line, "qty": 2, "serials": RANGE[1:3], "materials": [],
        "validate_only": True})
    assert r.status_code == 200 and r.get_json().get("validated") is True, r.get_json()
    with store.conn() as (cx, cur):
        left = [x["serial"] for x in store.rows(cur, "SELECT serial FROM serial", ())]
    assert left == [RANGE[1]], left


def validate(pg):
    pg.fill("#rgFrom", RANGE[0]); pg.dispatch_event("#rgFrom", "input")
    pg.fill("#rgTo", RANGE[-1]); pg.dispatch_event("#rgTo", "input")
    pg.wait_for_timeout(500)
    U.fill_bom(pg)
    pg.click("#v-plan button:has-text('Validate only')")
    pg.wait_for_function("() => /server/i.test(document.getElementById('railStatus').innerText) "
                         "|| /already/i.test(document.getElementById('railStatus').innerText)",
                         timeout=8000)
    return pg.inner_text("#railStatus")


@test("in the browser: Validate only on a good range says the server accepts it "
      "and nothing is written")
def t_browser_ok():
    T.world()
    with H.browser() as b:
        pg = U.open_plan(b)
        U.pick(pg, "OCT-02/2026")
        said = validate(pg)
        assert "server accepts" in said and "3 serial" in said, said
        assert counts() == (0, 0), counts()
        assert not pg.errors, pg.errors


@test("in the browser: Validate only on a range whose serial the master already "
      "has says so - it used to say 'Validated.' - and nothing is written")
def t_browser_refused():
    c, _custom, line = T.world()
    assert T.allocate(c, line, RANGE[1:2]).status_code == 200
    with H.browser() as b:
        pg = U.open_plan(b)
        U.pick(pg, "OCT-02/2026")
        said = validate(pg)
        assert RANGE[1] in said and "server accepts" not in said, said
        assert counts() == (1, 1), counts()
        assert not pg.errors, pg.errors


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            if only and not any(o in fn.__name__ for o in only):
                continue
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
