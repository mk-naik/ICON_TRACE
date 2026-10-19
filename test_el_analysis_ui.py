"""
ICON TRACE - EL Analysis on the running page (Chromium).

    python test_el_analysis_ui.py

What a person sees: EL Analysis in the menu after EL Stations; one station's
tiles (the NG rate on first images, NG again after rework), its first-image NG
by reason (point at a reason: it alone), the donut, the volume with the NG rate
and its Laney limits, the Pareto by modules, reason by shift and by machine,
Line A and Line B; every one of them opens its modules, and a module its
journey; all three stations side by side with the modules' journeys across them
and FQC's decision by the EL reason it read; a reason filter; the Excel; the
window an incharge and anyone else lands on; a reason's colour that does not
change; and no screen for a role that does not have it.
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


def cap(station, serial, verdict, at, unit=1, line="B", mode=None, cur=None):
    _n[0] += 1
    row = (station, unit, line, serial, verdict, r"X:\%s\%d.jpg" % (station, _n[0]), at,
           clock.stamp(), mode)
    sql = ("INSERT INTO el_capture (station, unit, line, serial, recapture, verdict, path, "
           "file_time, seen_at, mode) VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s)")
    if cur is not None:
        cur.execute(sql, row)
        return
    with store.conn() as (cx, c2):
        c2.execute(sql, row)


def base():
    store.wipe()
    AUTH.ensure_auth_schema()
    with store.conn() as (cx, cur):
        db.set_config(cur, CFG)


def world():
    """Pre-EL: two passed, one Grid Burning reworked (then Final EL NG for the same
    reason), one Cell Crack still NG; Final EL: an escape (passed Pre-EL, NG at
    Final EL) and a Line A module never at Pre-EL; Post EL in continuous mode."""
    base()
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


def tiles(pg):
    return dict(pg.eval_on_selector_all("#v-elan .ela-tiles .kpi", """ks => ks.map(k =>
        [k.querySelector('label').textContent, k.querySelector('.v').textContent])"""))


def open_analysis(b, role="Production Incharge", window="7d", kept=None):
    pg = H.open_page(b, None, role=role)
    if kept:
        # the screens are put in place when the page starts: a choice kept on this
        # PC is read then, so it is set and the page started again
        pg.evaluate("(k) => localStorage.setItem('icon.elan', k)", kept)
        pg.reload()
        pg.wait_for_load_state("networkidle")
        pg.wait_for_selector("#app.on", timeout=15000)
        pg.wait_for_timeout(700)
    order = pg.evaluate("""() => Array.from(document.querySelectorAll('#sidenav .nav-i'))
        .filter(b => b.offsetParent !== null).map(b => b.getAttribute('data-v'))""")
    assert "elan" in order and order.index("elan") == order.index("elst") + 1, order
    pg.click('#sidenav [data-v="elan"]')
    pg.wait_for_selector("#v-elan.on #elaStatus", timeout=15000)
    pg.wait_for_function("document.getElementById('elaStatus').textContent.indexOf('read ') > 0",
                         timeout=15000)
    if window and pg.eval_on_selector("#elaWindow button.on", "b => b.getAttribute('data-w')") != window:
        pg.click('#elaWindow button[data-w="%s"]' % window)
        pg.wait_for_function("document.querySelector('#elaWindow button.on').getAttribute('data-w') === %r && "
                             "document.getElementById('elaStatus').textContent.indexOf('read ') > 0" % window,
                             timeout=15000)
    return pg


@test("one station: its tiles - the NG rate on first images, NG again after rework - its "
      "first-image NG by reason, the donut, the volume with the NG rate, the Pareto, reason by "
      "shift and machine, Line A and B - drawn by the page, no library")
def t_single():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        on = pg.eval_on_selector_all("#v-elan .ela-seg button.on", "bs => bs.map(b => b.textContent)")
        assert on == ["Pre-EL", "7 days"], on
        got = tiles(pg)
        # five images, four of them first images; two of those NG
        assert got["Inspected"] == "5" and got["NG rate · first image"] == "50%", got
        assert got["NG again after rework"] == "0%", got
        assert got["Top reason"] == "Cell Crack", got
        assert pg.locator('#v-elan [data-chart="stack"] rect.seg').count() == 2
        assert pg.locator('#v-elan [data-chart="stack"] path.rate').count() == 0, \
            "the NG rate is drawn once, on the volume chart"
        # a handful of images a bar: the NG rate is drawn as hollow points, off the line -
        # 1 NG of 2 images is no trend
        assert pg.locator('#v-elan [data-chart="volume"] path.rate').count() == 0
        assert pg.locator('#v-elan [data-chart="volume"] circle.dot.thin').count() >= 1
        assert pg.locator('#v-elan [data-chart="donut"] circle.seg').count() == 2
        assert pg.locator('#v-elan [data-chart="pareto"] tbody tr').count() == 2
        assert pg.locator('#v-elan [data-chart="shift"] table').count() == 1
        machines = pg.eval_on_selector_all('#v-elan [data-chart="machine"] thead th',
                                           "ts => ts.map(t => t.textContent)")
        assert machines == ["Reason", "primary · Line B", "secondary · Line B"], machines
        mrows = {r[0]: r[1:] for r in rows_of(pg, '#v-elan [data-chart="machine"] tbody tr')}
        # on first images: the primary 2 NG of 3, the secondary none of 1 - and the
        # module back from rework beside, on the secondary
        assert mrows["First images"] == ["3", "1"] and mrows["NG rate"] == ["66.7%", "0%"], mrows
        assert mrows["Back from rework · NG again"] == ["0", "1 · 0%"], mrows
        lines = pg.text_content('#v-elan [data-chart="lines"]')
        assert "No Pre-EL folder is set for Line A" in lines and "not on the LAN yet" in lines, lines
        assert pg.errors == [], pg.errors


@test("every figure opens its modules - a Pareto row, a heat cell, a bar - and a module "
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
        pg.click('#v-elan [data-chart="shift"] td.cell[data-kind="first"]')
        pg.wait_for_function("document.getElementById('elaDrillTitle').textContent.indexOf('First images') >= 0",
                             timeout=10000)
        pg.click('#v-elan [data-chart="stack"] rect.seg >> nth=0')
        pg.wait_for_function("document.getElementById('elaDrillTitle').textContent.indexOf('NG at their first image') >= 0",
                             timeout=10000)
        pg.click("#elaDrillTable tbody tr button.lnk >> nth=0")
        pg.wait_for_selector("#searchOut .crumb", timeout=10000)
        assert pg.errors == [], pg.errors


def pane_top(pg, sel):
    """How far an element's top is below the top of the scrolling pane, in px."""
    return pg.evaluate("""(s) => Math.round(document.querySelector(s).getBoundingClientRect().top -
        document.querySelector('.main').getBoundingClientRect().top)""", sel)


@test("a click lands on its list (19 Oct 2026, Mukesh: it landed on 'Line A and Line B'): the "
      "Modules card is brought to the top of the pane once its rows are in; Back to the chart "
      "and Close return to the card that was clicked")
def t_drill_lands():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        for sel in ('#v-elan [data-chart="donut"] li[data-k="DF-CELLCRACK"]',
                    '#v-elan [data-chart="pareto"] tbody tr[data-k="DF-GRIDBURNING"]',
                    '#v-elan [data-chart="shift"] td.cell[data-kind="first"] >> nth=0'):
            pg.evaluate("document.querySelector('.main').scrollTop = 0")
            pg.click(sel)
            pg.wait_for_function("document.getElementById('elaDrillCount').textContent.indexOf('modules') > 0",
                                 timeout=10000)
            pg.wait_for_timeout(900)                         # a smooth scroll, and the rows in
            top = pane_top(pg, "#elaDrill")
            assert 0 <= top <= 12, "%s: the list's card is %dpx down the pane" % (sel, top)
        assert pg.text_content("#elaDrillTitle").startswith("Modules — First images")
        pg.click("#elaDrillBack")
        pg.wait_for_timeout(900)
        shift = '#v-elan .card:has([data-chart="shift"])'
        assert abs(pane_top(pg, shift)) <= 12, "Back: the shift card is %dpx down" % pane_top(pg, shift)
        pg.click('#v-elan [data-chart="pareto"] tbody tr[data-k="DF-CELLCRACK"]')
        pg.wait_for_function("document.getElementById('elaDrillCount').textContent === '1 modules'", timeout=10000)
        pg.click("#elaDrill button:has-text('Close')")
        pg.wait_for_timeout(400)
        assert pg.locator("#elaDrill").is_hidden()
        # back at the Pareto - at the top, or as near as a page this short can scroll
        pareto = '#v-elan .card:has([data-chart="pareto"])'
        top = pane_top(pg, pareto)
        at_end = pg.evaluate("(() => { const m = document.querySelector('.main'); "
                             "return m.scrollTop + m.clientHeight >= m.scrollHeight - 2; })()")
        assert abs(top) <= 12 or (at_end and 0 <= top < 400), "Close: the Pareto is %dpx down" % top
        assert pg.errors == [], pg.errors


@test("any card copies as a picture to paste into a WhatsApp chat (19 Oct 2026): where the browser "
      "allows it the PNG is on the clipboard at once - the window and filters printed on it, its own "
      "button left off - Save as file gives the same; each picture is recorded; on an address the "
      "browser does not trust, the dialog says to right-click and Copy image")
def t_copy_picture():
    world()
    with H.browser() as b:
        pg = open_analysis(b, role="Admin")
        pg.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=H.base_url())
        assert pg.locator("#elaBody .card [data-snap]").count() >= 6
        card = pg.locator("#elaBody .card", has=pg.locator(".card-h h3", has_text="Pareto")).first
        width = card.evaluate("c => Math.ceil(c.getBoundingClientRect().width)")
        card.locator("[data-snap]").click()
        pg.wait_for_function("document.getElementById('snapSaid') && "
                             "document.getElementById('snapSaid').textContent.indexOf('Copied') === 0",
                             timeout=15000)
        assert pg.text_content("#mdlTitle") == "Picture · EL Analysis · Pre-EL · Pareto · every reason"
        clip = pg.evaluate("""async () => { const it = (await navigator.clipboard.read())[0];
            const b = await it.getType('image/png'); return [it.types, b.size]; }""")
        assert clip[0] == ["image/png"] and clip[1] > 5000, clip
        size = pg.evaluate("""() => { const i = document.getElementById('snapImg');
            return [i.naturalWidth, i.naturalHeight]; }""")
        assert size[0] == 2 * (width + 36), (size, width)       # twice the card, with its margin
        with pg.expect_download() as dl:
            pg.click("#snapSave")
        assert dl.value.suggested_filename.startswith("icontrace_el_pre_el_pareto_every_reason_"), \
            dl.value.suggested_filename
        assert dl.value.suggested_filename.endswith(".png")
        pg.evaluate("closeModal()")
        pg.click("#v-elan .pg-act button:has-text('Copy summary')")
        pg.wait_for_function("document.getElementById('mdl').classList.contains('on') && "
                             "document.getElementById('mdlTitle').textContent === "
                             "'Picture · EL Analysis · Pre-EL · Summary' && "
                             "document.getElementById('snapSaid').textContent.indexOf('Copied') === 0",
                             timeout=15000)
        logs = pg.evaluate("fetch('/api/admin/audit?kind=docs').then(r => r.json())")
        pics = [x["entity_id"] for x in logs["rows"] if x["action"] == "export.image"]
        assert pics == ["el_pre_el_summary", "el_pre_el_pareto_every_reason"], pics
        assert pg.errors == [], pg.errors
        # a plain http address on the plant's LAN: the browser will not let the page copy
        q = H.open_page(b, None, role="Admin")
        q.add_init_script("Object.defineProperty(window, 'isSecureContext', { get: () => false });")
        q.reload()
        q.wait_for_selector("#app.on", timeout=15000)
        q.wait_for_timeout(700)
        q.click('#sidenav [data-v="elan"]')
        q.wait_for_function("document.getElementById('elaStatus').textContent.indexOf('read ') > 0",
                            timeout=15000)
        q.locator("#elaBody .card [data-snap]").first.click()
        q.wait_for_function("document.getElementById('snapImg') && document.getElementById('snapImg').complete "
                            "&& document.getElementById('snapImg').naturalWidth > 0", timeout=15000)
        assert q.text_content("#snapSaid") == "Right-click the picture, then Copy image"
        assert q.locator("#snapCopy").count() == 0 and "Copy image" in q.text_content("#snapHow")
        assert q.errors == [], q.errors


@test("point at a reason in the stacked bars: the others fade and it is drawn alone from the "
      "axis; away from the chart, all of them again")
def t_isolate():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        chart = '#v-elan [data-chart="stack"]'
        pg.hover(chart + ' .ela-legend span[data-k="DF-GRIDBURNING"]')
        pg.wait_for_function("document.querySelector('%s').classList.contains('iso')" % chart, timeout=5000)
        shown = pg.eval_on_selector_all(chart + " g.solo", """gs => gs.map(g =>
            [g.getAttribute('data-k'), getComputedStyle(g).display !== 'none'])""")
        assert dict(shown) == {"DF-CELLCRACK": False, "DF-GRIDBURNING": True}, shown
        faded = pg.eval_on_selector(chart + ' rect.seg[data-k="DF-CELLCRACK"]',
                                    "r => Number(getComputedStyle(r).opacity)")
        assert faded < 0.5, faded
        dim = pg.eval_on_selector_all(chart + " .ela-legend span.dim", "ss => ss.map(s => s.getAttribute('data-k'))")
        assert dim == ["DF-CELLCRACK"], dim
        pg.hover("#v-elan .pg h2")
        pg.wait_for_function("!document.querySelector('%s').classList.contains('iso')" % chart, timeout=5000)
        assert pg.locator(chart + " g.solo.on").count() == 0
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
        assert pg.locator('#v-elan [data-chart="rates"] circle.dot').count() >= 2
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
      "From-to boxes show only for From-to; the Excel downloads")
def t_filters_export():
    world()
    with H.browser() as b:
        pg = open_analysis(b)
        visible = lambda: pg.eval_on_selector("#elaRange", "e => getComputedStyle(e).display !== 'none'")
        assert visible() is False, "the From-to boxes show on a window that is not From-to"
        pg.select_option("#elaReason", "DF-GRIDBURNING")
        pg.wait_for_function("""Array.from(document.querySelectorAll('#v-elan .ela-tiles .kpi label'))
            .some(l => l.textContent === 'NG rate · this reason')""", timeout=10000)
        k = tiles(pg)
        assert k["Inspected"] == "5" and k["NG rate · this reason"] == "25%", k
        pg.click('#elaWindow button[data-w="range"]')
        assert visible() is True
        pg.click('#elaWindow button[data-w="8h"]')
        pg.wait_for_function("document.getElementById('elaStatus').textContent.indexOf('Last 8 hours') === 0",
                             timeout=10000)
        assert visible() is False
        assert pg.locator('#v-elan [data-chart="volume"] text.xa').count() >= 8
        with pg.expect_download(timeout=20000) as dl:
            pg.click("#v-elan .pg-act button >> text='Export to Excel'")
        assert dl.value.suggested_filename.startswith("icontrace_el_analysis_"), dl.value.suggested_filename
        assert pg.errors == [], pg.errors


@test("the window it opens on: a shift incharge on the shift running now, anyone else on the "
      "last 7 days - and a window picked before, on that PC, wins")
def t_landing():
    world()
    with H.browser() as b:
        pg = open_analysis(b, role="Production Incharge", window=None)
        assert pg.eval_on_selector("#elaWindow button.on", "b => b.textContent") == "This shift"
        pg = open_analysis(b, role="Admin", window=None)
        assert pg.eval_on_selector("#elaWindow button.on", "b => b.textContent") == "7 days"
        pg = open_analysis(b, role="Production Incharge", window=None,
                           kept='{"station": "final_el", "window": "yesterday"}')
        on = pg.eval_on_selector_all("#v-elan .ela-seg button.on", "bs => bs.map(b => b.textContent)")
        assert on == ["Final EL", "Yesterday"], on
        assert pg.errors == [], pg.errors


@test("a reason's colour does not change - not with the window, not with the station - and "
      "Other is grey")
def t_colours():
    base()
    with store.conn() as (cx, cur):
        for k, v in enumerate(("Grid Burning", "Cell Crack", "Other", "Other", "OK", "OK")):
            cap("pre_el", S(100 + k), v, ago(30 + k), cur=cur)
        for k, v in enumerate(("Low Eff", "Grid Burning", "Patches", "OK")):
            cap("final_el", S(200 + k), v, ago(20 + k), cur=cur)
    with H.browser() as b:
        pg = open_analysis(b)
        swatch = """(k) => { const r = document.querySelector('#v-elan [data-chart="pareto"] tr[data-k="' + k + '"] i.sw');
                             return r ? getComputedStyle(r).backgroundColor : null; }"""
        week = {k: pg.evaluate(swatch, k) for k in ("DF-GRIDBURNING", "DF-CELLCRACK", "DF-OTHER")}
        assert week == {"DF-GRIDBURNING": "rgb(45, 111, 210)", "DF-CELLCRACK": "rgb(42, 138, 102)",
                        "DF-OTHER": "rgb(142, 155, 170)"}, week
        pg.click('#elaWindow button[data-w="1h"]')
        pg.wait_for_function("document.getElementById('elaStatus').textContent.indexOf('Last 1 hour') === 0",
                             timeout=10000)
        hour = {k: pg.evaluate(swatch, k) for k in week}
        assert hour == week, (hour, week)
        pg.click('#elaStation button[data-st="final_el"]')
        pg.wait_for_function("document.querySelector('#elaStation button.on').textContent === 'Final EL' && "
                             "document.getElementById('elaStatus').textContent.indexOf('read ') > 0", timeout=10000)
        assert pg.evaluate(swatch, "DF-GRIDBURNING") == week["DF-GRIDBURNING"]
        assert pg.evaluate(swatch, "DF-LOWEFF") == "rgb(224, 138, 30)"
        assert pg.errors == [], pg.errors


@test("the NG-rate trend carries its control limits (Laney p'): the centre, the 2 and 3 sigma "
      "lines, a bar beyond 3 sigma marked and said so")
def t_limits():
    base()
    now = clock.now()
    start = now - datetime.timedelta(hours=8 * 9 + 4)
    with store.conn() as (cx, cur):
        for shift in range(9):                       # nine shifts, 30 first images each
            t0 = start + datetime.timedelta(hours=8 * shift)
            bad = 15 if shift == 6 else 3            # one shift at half NG
            for k in range(30):
                at = (t0 + datetime.timedelta(minutes=10 * k)).replace(microsecond=0).isoformat()
                cap("pre_el", "ICON625R12A19%03d%02d" % (shift, k), "Cell Crack" if k < bad else "OK",
                    at, cur=cur)
    with H.browser() as b:
        pg = open_analysis(b)
        vol = '#v-elan [data-chart="volume"]'
        assert pg.locator(vol + " path.lim3").count() == 1 and pg.locator(vol + " path.lim2").count() == 1
        assert pg.locator(vol + " line.cl").count() == 1
        assert pg.locator(vol + " circle.dot.f3").count() == 1, "the half-NG shift is not marked"
        note = pg.text_content(vol + " .ela-foot")
        assert "Laney p′" in note and "1 bar above the red line" in note, note
        assert pg.errors == [], pg.errors


@test("FQC's decision by the EL reason it read, on Final EL and beside all three: how many "
      "it passed and rejected, each count opening its modules")
def t_fqc():
    base()
    with store.conn() as (cx, cur):
        for k, (outcome, el) in enumerate((("pass", "DARK BUSBAR"), ("pass", "Dark Busbar"),
                                           ("reject", "DARK BUSBAR"), ("pass", "OK"))):
            store.insert(cur, "fqc_record", {"serial": S(300 + k), "outcome": outcome,
                                             "grade": "A" if outcome == "pass" else None,
                                             "mode": "confirmed", "decided_by": "fqc1",
                                             "at": ago(40 + k), "el_verdict": el})
        cap("final_el", S(300), "DARK BUSBAR", ago(60), cur=cur)
    with H.browser() as b:
        pg = open_analysis(b)
        pg.click('#elaStation button[data-st="final_el"]')
        pg.wait_for_function("document.querySelector('#elaStation button.on').textContent === 'Final EL' && "
                             "document.getElementById('elaStatus').textContent.indexOf('read ') > 0", timeout=10000)
        rows = rows_of(pg, "#elaBody table:has(td[data-fqc]) tbody tr")
        assert [r[:4] for r in rows] == [["Dark Busbar", "3", "2", "66.7%"], ["EL clean (OK)", "1", "1", "100%"]], rows
        pg.click('#elaBody td.cell[data-fqc="DF-DARKBUSBAR"][data-outcome="reject"]')
        pg.wait_for_function("document.getElementById('elaDrillCount').textContent === '1 modules'", timeout=10000)
        assert rows_of(pg, "#elaDrillTable tbody tr")[0][:3] == [S(302), "—", "Reject"]
        pg.click('#elaStation button[data-st=""]')
        pg.wait_for_selector("#v-elan .ela-st", timeout=10000)
        assert "FQC’s decision by the EL reason it read" in pg.text_content("#elaBody")
        assert pg.errors == [], pg.errors


@test("the dashboards' Top EL defects card: each station's busiest reasons for a window of "
      "its own, with their rate, its change and trend; a reason opens EL Analysis on it; only "
      "for an account that has EL Analysis")
def t_dashboard_card():
    import icon_auth
    world()
    with H.browser() as b:
        pg = H.open_page(b, "proddash", role="Production Incharge")
        pg.wait_for_selector("#pdElTop .grid.g3", timeout=15000)
        cols = pg.eval_on_selector_all("#pdElTop .grid.g3 > div > div:first-child b",
                                       "bs => bs.map(b => b.textContent)")
        assert cols == ["Pre-EL", "Post EL", "Final EL"], cols
        text = pg.text_content("#pdElTop")
        assert "passed by the machine" in text, text          # Post EL: continuous only
        assert "first images" in text, text
        rows = pg.locator("#pdElTop tr[onclick]")
        assert rows.count() >= 4, rows.count()
        # the card as a picture, its window printed on it
        pg.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=H.base_url())
        pg.click("#pdElTop [data-snap]")
        pg.wait_for_function("document.getElementById('mdl').classList.contains('on') && "
                             "document.getElementById('snapSaid') && "
                             "document.getElementById('snapSaid').textContent.indexOf('Copied') === 0",
                             timeout=15000)
        assert pg.text_content("#mdlTitle").startswith("Picture · Top EL defects · "), pg.text_content("#mdlTitle")
        pg.evaluate("closeModal()")
        pg.click("#pdElTop button >> text='7 days'")
        pg.wait_for_function("document.querySelector('#pdElTop .btn-primary').textContent === '7 days'",
                             timeout=10000)
        pg.click("#pdElTop tr[title='Open EL Analysis on Cell Crack']")
        pg.wait_for_selector("#v-elan.on .ela-tiles", timeout=15000)
        pg.wait_for_function("document.getElementById('elaReason').value === 'DF-CELLCRACK'",
                             timeout=10000)
        assert pg.eval_on_selector("#elaStation button.on", "b => b.textContent") == "Pre-EL"
        assert pg.eval_on_selector("#elaWindow button.on", "b => b.textContent") == "7 days"
        assert pg.errors == [], pg.errors
        # an incharge an Admin has taken EL Analysis from has no such card
        login = AUTH.make_user("Production Incharge")["login_id"]
        boss = AUTH.make_user("Super Admin")["login_id"]
        with store.conn() as (cx, cur):
            icon_auth.set_screen_perms(cur, boss, login, {"elan": {"view": False, "write": False}})
        q = H.open_page(b, "proddash", role="Production Incharge", login_id=login)
        q.wait_for_selector("#pdElCard", timeout=15000)
        q.wait_for_timeout(800)
        assert q.locator("#pdElTop").count() == 0, "a card for an account without EL Analysis"
        assert q.errors == [], q.errors


@test("what a dropdown offers belongs to the station picked (18 Oct 2026, Mukesh: 'check "
      "other places and filter for same'): at Pre-EL only Pre-EL's reasons, machines and "
      "lines; a reason Pre-EL does not file is cleared on switching to it, and said so; one "
      "both file is kept; all three with Line A says Pre-EL has no folder there")
def t_dropdowns_follow_station():
    world()
    with H.browser() as b:
        pg = open_analysis(b)                       # Pre-EL, 7 days
        opts = lambda sel: pg.eval_on_selector_all(sel + " option", "os => os.map(o => o.value)")
        assert opts("#elaReason") == ["", "DF-CELLCRACK", "DF-GRIDBURNING"], opts("#elaReason")
        assert opts("#elaMachine") == ["", "pre_el|1|B", "pre_el|2|B"], opts("#elaMachine")
        assert opts("#elaLine") == ["", "B"], opts("#elaLine")
        # Final EL: pick Dark Busbar, which Pre-EL never files
        pg.click('#elaStation button[data-st="final_el"]')
        pg.wait_for_function("document.querySelector('#elaStation button.on').textContent === 'Final EL'",
                             timeout=10000)
        pg.wait_for_function("Array.from(document.querySelectorAll('#elaReason option'))"
                             ".some(o => o.value === 'DF-DARKBUSBAR')", timeout=10000)
        pg.select_option("#elaReason", "DF-DARKBUSBAR")
        pg.wait_for_function("""Array.from(document.querySelectorAll('#v-elan .ela-tiles .kpi label'))
            .some(l => l.textContent === 'NG rate · this reason')""", timeout=10000)
        pg.click('#elaStation button[data-st="pre_el"]')
        pg.wait_for_function("document.getElementById('elaStatus').textContent"
                             ".indexOf('The reason picked is not filed at Pre-EL') === 0", timeout=10000)
        assert pg.input_value("#elaReason") == "", "a reason Pre-EL does not file stayed picked"
        # Grid Burning is filed at both: switching keeps it
        pg.select_option("#elaReason", "DF-GRIDBURNING")
        pg.wait_for_function("""Array.from(document.querySelectorAll('#v-elan .ela-tiles .kpi label'))
            .some(l => l.textContent === 'NG rate · this reason')""", timeout=10000)
        pg.click('#elaStation button[data-st="final_el"]')
        pg.wait_for_function("document.querySelector('#elaStation button.on').textContent === 'Final EL' && "
                             "document.getElementById('elaStatus').textContent.indexOf('read ') > 0",
                             timeout=10000)
        assert pg.input_value("#elaReason") == "DF-GRIDBURNING"
        assert "not filed" not in pg.text_content("#elaStatus")
        # all three, Line A: Pre-EL has no folder there and says so
        pg.select_option("#elaReason", "")
        pg.click('#elaStation button[data-st=""]')
        pg.wait_for_selector("#v-elan .ela-st", timeout=10000)
        pg.select_option("#elaLine", "A")
        pg.wait_for_function("document.querySelector('#v-elan .ela-st[data-st=\"pre_el\"]').textContent"
                             ".indexOf('No Pre-EL folder is set for Line A') >= 0", timeout=10000)
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
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            if only and fn.__name__ not in only:
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
