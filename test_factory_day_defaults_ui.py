"""
ICON TRACE - the day each counting screen opens on, before and after midnight.

    python test_factory_day_defaults_ui.py       (needs Playwright + Chromium)

The factory day runs 06:00 to 06:00 (DECISIONS 8): at 01:00 on the 9th it is
still C shift of the 8th, and every screen that COUNTS opens on the 8th. The
FQC and Production Dashboards opened on the 9th instead - a day nothing counts
towards until 06:00 - so for the second half of C shift both read empty, while
their own Reset went back to the 8th. (Found 9 Oct 2026 when the suite ran
after midnight: test_dashboards_e2e's Production Dashboard had no View buttons.)
A document's own date - the challan's - is the calendar day.

The browser's clock is pinned with Playwright's clock, so this holds whatever
time the suite runs at.
"""

import datetime, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_factoryday_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import store                                                 # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import ui_harness as H                                       # noqa: E402

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NIGHT = datetime.datetime(2026, 10, 9, 1, 0, tzinfo=IST)     # C shift of the 8th
MORNING = datetime.datetime(2026, 10, 9, 11, 0, tzinfo=IST)  # A shift of the 9th

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def open_at(b, when):
    """A signed-in page whose clock reads `when` from its first script on."""
    ctx = b.new_context(viewport={"width": 1500, "height": 950})
    ctx.clock.set_fixed_time(when)
    sid = AUTH.make_session_id(role="Super Admin")
    ctx.add_cookies([{"name": "icon_sid", "value": sid,
                      "domain": "127.0.0.1", "path": "/"}])
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.asked = []
    pg.on("request", lambda r: pg.asked.append(r.url))
    pg.goto(H.base_url() + "/")
    pg.wait_for_selector("#app.on", timeout=15000)
    pg.wait_for_timeout(800)
    return pg


def dates_on(pg, view):
    pg.evaluate("go(%r)" % view)
    pg.wait_for_timeout(900)
    return pg.evaluate("""() => Array.prototype.map.call(
        document.querySelectorAll('.view.on input[type=date]'),
        function (e) { return e.offsetParent !== null ? e.value : null; })
        .filter(function (v) { return v !== null; })""")


COUNTING = ("dash", "proddash", "mgmt", "packdash", "disp")


@test("at 01:00 every counting screen opens on yesterday's factory day, and the "
      "dashboards ask the server for that day")
def t_night():
    store.wipe()
    with H.browser() as b:
        pg = open_at(b, NIGHT)
        for view in COUNTING:
            got = [v for v in dates_on(pg, view) if v]
            assert got and all(v == "2026-10-08" for v in got), (view, got)
        asked = [u for u in pg.asked if "/api/prod/dashboard" in u or "/api/fqc/dashboard?" in u]
        assert asked, "neither dashboard asked the server anything"
        wrong = [u for u in asked if "2026-10-09" in u]
        assert not wrong, wrong
        assert not pg.errors, pg.errors


@test("at 01:00 a challan's own date is still the calendar day")
def t_night_document_date():
    store.wipe()
    with H.browser() as b:
        pg = open_at(b, NIGHT)
        got = dates_on(pg, "challan")
        assert "2026-10-09" in got and "2026-10-08" not in got, got


@test("at 11:00 the factory day and the calendar day are the same day")
def t_morning():
    store.wipe()
    with H.browser() as b:
        pg = open_at(b, MORNING)
        for view in COUNTING + ("challan",):
            got = [v for v in dates_on(pg, view) if v]
            assert got and all(v == "2026-10-09" for v in got), (view, got)
        assert not pg.errors, pg.errors


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
        H.cleanup()
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
