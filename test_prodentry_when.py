"""
ICON TRACE - Production Entry records the shift that RAN, on the screen.

    python test_prodentry_when.py

Reported by Mukesh, 26-09-2026: the shift report is written after the shift
ends - which is the next shift, and for C shift the next calendar day - so
the form forced a wrong date and shift.

It forced it twice over. The two fields were DISABLED and re-stamped with the
current date and shift every 30 seconds, and the server ignored whatever was
sent and stamped clock.now() into prod_date/shift as well. Nobody could file
C shift of the 25th under its own name.

Now: the fields are editable, they open on the shift that just ended, and
what the operator states is what is stored - checked end to end here,
through the real form.
"""

import datetime, os, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_pewhen_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


MODEL, WATT = "ISEN590-G12R", 590
DATE_SEL = '#peManual input[type="date"]'
SHIFT_SEL = '#peManual .grid.g3 select'


def seed(qty=6):
    store.wipe()
    AUTH.ensure_auth_schema()
    serials = []
    with store.conn() as (cx, cur):
        for i in range(qty):
            s = "ICON590G120212%04d" % (1000 + i)
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": MODEL,
                "wattage": WATT, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": 1000 + i, "state": "planned"})
            serials.append(s)
    return serials


def open_form(b):
    pg = H.open_page(b, "prodentry", wait_ms=1500, role="Super Admin",
                     login_id="sa1")
    pg.locator("#v-prodentry button", has_text="New production entry").first.click()
    pg.wait_for_timeout(900)
    return pg


def last_entry():
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT * FROM production_entry "
                              "ORDER BY entry_id DESC LIMIT 1")


@test("the date and shift are editable, not locked and re-stamped - the "
     "operator can say which shift this was")
def t_fields_are_editable():
    seed()
    with H.browser() as b:
        pg = open_form(b)
        assert pg.eval_on_selector(DATE_SEL, "e => e.disabled") is False, \
            "the production date is still locked"
        assert pg.eval_on_selector(SHIFT_SEL, "e => e.disabled") is False, \
            "the shift is still locked"
        # a future day cannot be picked
        assert pg.eval_on_selector(DATE_SEL, "e => e.getAttribute('max')") == \
            clock.today().isoformat()
        pg.close()


@test("a fresh form opens on the shift that just ENDED - not on today's "
     "current shift, and never on v4's hardcoded 2026-08-21 / shift B")
def t_defaults_to_the_shift_that_ended():
    seed()
    with H.browser() as b:
        pg = open_form(b)
        got = (pg.eval_on_selector(DATE_SEL, "e => e.value"),
               pg.eval_on_selector(SHIFT_SEL, "e => e.value"))
        want = pg.evaluate("window.istLastEndedShift()")
        assert got == (want["date"], want["shift"]), (got, want)
        assert got[0] != "2026-08-21", "v4's demo date survived"
        # the shift that just ended is never the one running now
        assert got[1] != pg.evaluate("window.istShift()"), got
        hint = pg.inner_text("#peStampHint")
        assert "ran in" in hint and "just ended" in hint, hint
        print("      opens on %s of %s (now: shift %s)" %
              (got[1], got[0], pg.evaluate("window.istShift()")))
        pg.close()


@test("the whole reported case, through the form: C shift of yesterday, "
     "filed today, is stored as C shift of yesterday")
def t_files_yesterdays_c_shift():
    serials = seed()
    yesterday = (clock.today() - datetime.timedelta(days=1)).isoformat()
    with H.browser() as b:
        pg = open_form(b)
        pg.eval_on_selector(DATE_SEL, "(e, v) => { e.value = v; }", yesterday)
        pg.select_option(SHIFT_SEL, "C")
        pg.select_option(SHIFT_SEL + " >> nth=1", index=1)      # shift incharge
        pg.fill("#peFrom", serials[0])
        pg.fill("#peTo", serials[3])
        pg.wait_for_timeout(600)
        pg.locator("#v-prodentry button", has_text="Record production").first.click()
        pg.wait_for_timeout(2500)

        row = last_entry()
        assert row, "nothing was recorded: %s" % pg.inner_text("#peStatus")
        assert row["prod_date"] == yesterday, dict(row)
        assert row["shift"] == "C", dict(row)
        # and when it was typed is kept separately
        assert row["created_at"][:10] == clock.today().isoformat(), dict(row)
        assert pg.errors == [], pg.errors
        print("      stored prod_date=%s shift=%s, typed %s"
              % (row["prod_date"], row["shift"], row["created_at"]))
        pg.close()


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
                traceback.print_exc()
                failed += 1
    finally:
        H.cleanup()
    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
