"""
ICON TRACE - EL Analysis on the running page (Chromium).

    python test_el_analysis_ui.py

What a person sees: EL Analysis in the menu after EL Stations; one station's
tiles, its NG-by-reason bars with the NG-rate line, the donut, the Pareto, reason
by shift and by machine, Line A and Line B; every one of them opens its modules,
and a module its journey; all three stations side by side with the modules'
journeys across them; a reason filter; the Excel; and no screen for a role that
does not have it.
"""

import datetime, os, sys, traceback

import ui_harness as H                     # first: it picks the throwaway database
import store                                                 # noqa: E402
import db                                                    # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_clock as clock                                   # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


CFG = {"el_root": "", "el_a_root": r"X:\final_a", "el_b_root": r"X:\final_b",
       "pre_el_a_root": "", "pre_el_b_root": r"X:\pre_b1", "pre_el2_a_root": "",
       "pre_el2_b_root": r"X:\pre_b2", "post_el_a_root": "", "post_el_b_root": r"X:\post_b"}
_n = [0]


def S(n):
    return "ICON625R12A18%05d" % n


def ago(minutes):
    return (clock.now() - datetime.timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def cap(station, serial, verdict, at, unit=1, line="B", mode=None):
    _n[0] += 1
    with store.conn() as (cx, cur):
        cur.execute("INSERT INTO el_capture (station, unit, line, serial, recapture, verdict, path, "
                    "file_time, seen_at, mode) VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s)",
                    (station, unit, line, serial, verdict, r"X:\%s\%d.jpg" % (station, _n[0]), at,
                     clock.stamp(), mode))


def world():
    """Pre-EL: two passed, one Grid Burning reworked (then Final EL NG for the same
    reason), one Cell Crack still NG; Final EL: an escape (passed Pre-EL, NG at
    Final EL) and a Line A module never at Pre-EL; Post EL in continuous mode."""
    store.wipe()
    AUTH.ensure_auth_schema()
    with store.conn() as (cx, cur):
        db.set_config(cur, CFG)
    cap("pre_el", S(1), "OK", ago(300))
    cap("pre_el", S(2), "OK", ago(290), unit=2)
    cap("pre_el", S(3), "Grid Burning", ago(280))
    cap("pre_el", S(3), "OK", ago(240), unit=2)
    cap("pre_el", S(4), "Cell Crack", ago(270))
    cap("post_el", S(1), "OK", ago(200), mode="continuous")
    cap("final_el", S(3), "Grid Buring", ago(100))
    cap("final_el", S(1), "DARK BUSBAR", ago(90))
    cap("final_el", S(5), "Patches", ago(80), line="A")
    cap("final_el", S(2), "OK", ago(70))


def rows_of(pg, sel):
    return pg.evaluate("""(s) => Array.from(document.querySelectorAll(s))
        .map(tr => Array.from(tr.cells).map(c => c.textContent.trim()))""", sel)


def open_analysis(b, role="Production Incharge"):
    pg = H.open_page(b, None, role=role)
    pg.evaluate("try { localStorage.removeItem('icon.elan') } catch (e) {}")
    order = pg.evaluate("""() => Array.from(document.querySelectorAll('#sidenav .nav-i'))
        .filter(b => b.offsetParent !== null).map(b => b.getAttribute('data-v'))""")
    assert "elan" in order and order.index("elan") == order.index("elst") + 1, order
    pg.click('#sidenav [data-v="elan"]')
    pg.wait_for_selector("#v-elan.on .ela-tiles", timeout=15000)
    return pg


@test("one station: its tiles, NG by reason with the NG-rate line, the donut, the Pareto, "
      "reason by shift and machine, Line A and B - drawn by the page, no library")
def t_single():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        on = pg.eval_on_selector_all("#v-elan .ela-seg button.on", "bs => bs.map(b => b.textContent)")
        assert on == ["Pre-EL", "7 days"], on
        k = pg.eval_on_selector_all("#v-elan .ela-tiles .kpi", """ks => ks.map(k =>
            [k.querySelector('label').textContent, k.querySelector('.v').textContent])""")
        got = dict(k)
        assert got["Inspected"] == "5" and got["NG rate"] == "40%", got
        assert got["First-pass yield"] == "50%" and got["Top reason"] in ("Cell Crack", "Grid Burning"), got
        assert pg.locator('#v-elan [data-chart="stack"] rect.seg').count() == 2
        assert pg.locator('#v-elan [data-chart="stack"] path.rate').count() == 1
        assert pg.locator('#v-elan [data-chart="donut"] circle.seg').count() == 2
        assert pg.locator('#v-elan [data-chart="pareto"] tbody tr').count() == 2
        assert pg.locator('#v-elan [data-chart="shift"] table').count() == 1
        machines = pg.eval_on_selector_all('#v-elan [data-chart="machine"] thead th',
                                           "ts => ts.map(t => t.textContent)")
        assert machines == ["Reason", "primary · Line B", "secondary · Line B"], machines
        lines = pg.text_content('#v-elan [data-chart="lines"]')
        assert "No Pre-EL folder is set for Line A" in lines and "not on the LAN yet" in lines, lines
        assert pg.errors == [], pg.errors


@test("every figure opens its modules - a Pareto row, a bar, a heat cell - and a module "
      "opens its journey in Search & Trace")
def t_drill():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        pg.click('#v-elan [data-chart="pareto"] tbody tr[data-k="DF-CELLCRACK"]')
        pg.wait_for_function("document.getElementById('elaDrillCount').textContent === '1 modules'",
                             timeout=10000)
        assert "Cell Crack" in pg.text_content("#elaDrillTitle")
        assert rows_of(pg, "#elaDrillTable tbody tr")[0][0] == S(4)
        pg.click('#v-elan [data-chart="shift"] td.cell[data-kind="all"]')
        pg.wait_for_function("document.getElementById('elaDrillTitle').textContent.indexOf('Inspected') >= 0",
                             timeout=10000)
        pg.click('#v-elan [data-chart="stack"] rect.seg >> nth=0')
        pg.wait_for_function("document.getElementById('elaDrillTitle').textContent.indexOf('NG ·') >= 0",
                             timeout=10000)
        pg.click("#elaDrillTable tbody tr button.lnk >> nth=0")
        pg.wait_for_selector("#searchOut .crumb", timeout=10000)
        assert pg.errors == [], pg.errors


@test("all three stations side by side - their own figures, never added - with the modules' "
      "journeys across them, each figure opening its modules")
def t_compare():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        pg.click('#elaStation button[data-st=""]')
        pg.wait_for_selector("#v-elan .ela-st", timeout=10000)
        assert pg.locator("#v-elan .ela-st").count() == 3
        assert pg.locator('#v-elan [data-chart="rates"] path').count() >= 2
        heads = pg.eval_on_selector_all("#v-elan .ela-st h3 button", "bs => bs.map(b => b.textContent)")
        assert heads == ["Pre-EL ›", "Post EL ›", "Final EL ›"], heads
        post = pg.text_content('#v-elan .ela-st[data-st="post_el"]')
        assert "passed by the machine (continuous)" in post, post
        body = pg.text_content("#elaBody")
        assert "No total column" in body
        pg.click('#v-elan td.cell[data-flow="final_ng"][data-sub="pre_pass"] >> nth=0')
        pg.wait_for_function("document.getElementById('elaDrillTitle').textContent.indexOf('passed Pre-EL first time') >= 0",
                             timeout=10000)
        assert [r[0] for r in rows_of(pg, "#elaDrillTable tbody tr")] == [S(1)]
        pg.click('#v-elan td.cell[data-flow="pre_ng"][data-sub="final_same"] >> nth=0')
        pg.wait_for_function("document.getElementById('elaDrillTitle').textContent.indexOf('same reason') >= 0",
                             timeout=10000)
        assert [r[0] for r in rows_of(pg, "#elaDrillTable tbody tr")] == [S(3)]
        pg.click('#v-elan .ela-st h3 button >> text="Final EL ›"')
        pg.wait_for_function("document.querySelector('#elaStation button.on').textContent === 'Final EL'",
                             timeout=10000)
        assert pg.errors == [], pg.errors


@test("a reason picked narrows the NG side only; the window buttons change the bars; the "
      "Excel downloads")
def t_filters_export():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        pg.select_option("#elaReason", "DF-GRIDBURNING")
        pg.wait_for_function("""Array.from(document.querySelectorAll('#v-elan .ela-tiles .kpi label'))
            .some(l => l.textContent === 'NG rate · this reason')""", timeout=10000)
        k = dict(pg.eval_on_selector_all("#v-elan .ela-tiles .kpi", """ks => ks.map(k =>
            [k.querySelector('label').textContent, k.querySelector('.v').textContent])"""))
        assert k["Inspected"] == "5" and k["NG rate · this reason"] == "20%", k
        pg.click('#elaWindow button[data-w="8h"]')
        pg.wait_for_function("document.getElementById('elaStatus').textContent.indexOf('Last 8 hours') === 0",
                             timeout=10000)
        assert pg.locator('#v-elan [data-chart="volume"] text.xa').count() >= 8
        with pg.expect_download(timeout=20000) as dl:
            pg.click("#v-elan .pg-act button >> text='Export to Excel'")
        assert dl.value.suggested_filename.startswith("icontrace_el_analysis_"), dl.value.suggested_filename
        assert pg.errors == [], pg.errors


@test("a role without EL Analysis has no such screen")
def t_quality():
    world()
    with H.browser() as b:
        q = H.open_page(b, None, role="Quality")
        assert not q.locator('#sidenav [data-v="elan"]').is_visible(), "Quality sees EL Analysis"
        assert q.errors == [], q.errors


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
