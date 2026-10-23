"""
ICON TRACE - v4's words about things this system does not have are gone.

    python test_demo_leftovers_ui.py      (needs Playwright + Chromium)

v4 was a design prototype, and some of its explanatory text describes the
prototype rather than ICON TRACE: features that were never built, figures
that were nobody's data. Found by the overnight audit (24 Oct 2026), which
searched every screen for v4's sample values and text.

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


@test("Management Overview's Needs a decision card says what it does - not v4's "
      "aging alert, challan approvals and 'one real box waited 67 days'")
def t_mgmt_footer():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = H.open_page(b, "mgmt", wait_ms=2000)
        foot = pg.evaluate("() => document.getElementById('mgBlocked').closest('.card')"
                           ".querySelector('.card-f').innerText")
        for gone in ("67 days", "aging alert", "challan approval"):
            assert gone not in foot, foot
        assert "Open goes to the screen where it is decided" in foot, foot
        assert pg.errors == [], pg.errors


@test("Admin > Stations & sources counts each station's real accounts - not v4's "
      "sample staff - lists a station an account names that the list lacks, and "
      "no longer claims a station_config table the server reads")
def t_station_accounts():
    store.wipe(); AUTH.ensure_auth_schema()
    for login, role, station in (("op.a1", "FQC Operator", "FQC-01"),
                                 ("op.a2", "FQC Operator", "FQC-01"),
                                 ("op.p2", "Packing Operator", "PACK-02"),
                                 ("op.x", "FQC Operator", "FQC-03")):
        AUTH.make_user(role, login_id=login, station=station)
    with H.browser() as b:
        pg = H.open_page(b, "admin", wait_ms=1500)
        pg.click('#adTabs button[onclick*="\'stations\'"]')
        pg.wait_for_function("() => !/…/.test(document.getElementById('stationRows').innerText)",
                             timeout=8000)
        rows = pg.eval_on_selector_all("#stationRows tr", "rs => rs.map(r => "
                                       "[r.cells[0].innerText.trim(), r.cells[r.cells.length - 2].innerText.trim()])")
        got = dict(rows)
        assert got.get("FQC-01") == "2" and got.get("PACK-02") == "1", rows
        assert got.get("FQC-02") == "0" and got.get("FQC-03") == "1", rows
        note = pg.inner_text("#ad-stations > .note")
        assert "when the server starts" not in note and "nothing reads it" in note, note
        assert pg.errors == [], pg.errors


@test("a first visit is not told its session timed out; the station chip does not "
      "name a station_config table")
def t_first_visit_and_chip():
    store.wipe(); AUTH.ensure_auth_schema()
    with H.browser() as b:
        pg = b.new_page()
        pg.goto(H.base_url() + "/")
        pg.wait_for_selector("#liLoginId", timeout=15000)
        pg.wait_for_timeout(2500)
        msg = pg.inner_text("#liMsg") if pg.query_selector("#liMsg") else ""
        assert "timed out" not in msg, msg
        pg.close()
        pg = H.open_page(b, None, role="Packing Operator", login_id="pk.chip")
        title = pg.evaluate("document.getElementById('tbStation').title")
        assert "station_config" not in title and "written on your account" in title, title
        assert pg.errors == [], pg.errors


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
