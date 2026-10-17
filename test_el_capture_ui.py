"""
ICON TRACE - the Pre-EL and Post EL folders and steps, on the running page
(Chromium).

    python test_el_capture_ui.py

What a person sees: Admin > Stations & sources has a Pre-EL and a Post EL
folder on each line, each with its reachability tag; a save that makes one
folder two stations is refused on the screen with the server's reason; a good
save is kept and the sources table lists it. In Search & Trace a module shows
a Pre-EL and a Post EL step when it was captured there and none when it was
not, and the longer chain still scrolls inside its card.
"""

import datetime, os, shutil, sys, tempfile, traceback

import ui_harness as H                     # first: it picks the throwaway database
import store                                                 # noqa: E402
import db                                                    # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_clock as clock                                   # noqa: E402
import icon_el_capture as elcap                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


SHARES = tempfile.mkdtemp(prefix="icontrace_elcap_ui_")
FQC_EL = os.path.join(SHARES, "fqc_el")
PRE_B = os.path.join(SHARES, "pre_b")


def world(**cfg):
    store.wipe()
    AUTH.ensure_auth_schema()
    for d in (FQC_EL, PRE_B):
        os.makedirs(d, exist_ok=True)
    conf = {"el_root": "", "el_a_root": "", "el_b_root": FQC_EL,
            "pre_el_a_root": "", "pre_el_b_root": "",
            "post_el_a_root": "", "post_el_b_root": ""}
    conf.update(cfg)
    with store.conn() as (cx, cur):
        db.set_config(cur, conf)


def stations(b):
    pg = H.open_page(b, "admin", wait_ms=1500)
    pg.click('#adTabs button[onclick*="\'stations\'"]')
    pg.wait_for_selector("#v-settings #s_b_pre_el", timeout=15000)
    return pg


def card(pg, line):
    return pg.locator('#v-settings .card:has(h3:text-is("Line %s"))' % line)


@test("each line's card has a Pre-EL primary, a Pre-EL secondary and a Post EL folder, "
      "with their tags and hints")
def t_fields_shown():
    world()
    with H.browser() as b:
        pg = stations(b)
        for ln in ("A", "B"):
            c = card(pg, ln)
            for fid in ("#s_%s_pre_el" % ln.lower(), "#s_%s_pre_el2" % ln.lower(),
                        "#s_%s_post_el" % ln.lower()):
                assert c.locator(fid).is_visible(), (ln, fid)
            # textContent, not innerText: labels and tags are upper-cased by CSS
            text = " ".join(c.text_content().split())
            assert "Pre-EL primary image root folder" in text, text
            assert "Pre-EL secondary image root folder" in text, text
            assert "Post EL (after lamination) image root folder" in text, text
            tags = c.locator(".card-h .tag").all_text_contents()
            assert "Pre-EL primary —" in tags and "Pre-EL secondary —" in tags and \
                "Post EL —" in tags, tags
            # the folders are saved from their own card, not only from Plant's below
            assert c.locator('.card-f button[onclick="setSave()"]').count() == 1, ln
            assert "Read by the server every minute, not by FQC" in text, text
        assert pg.errors == [], pg.errors


@test("using the FQC EL folder as Pre-EL is refused on the screen with the "
      "server's reason, and nothing is stored; a good folder saves and shows OK")
def t_refused_then_saved():
    world()
    with H.browser() as b:
        pg = stations(b)
        pg.fill("#s_b_pre_el", FQC_EL.upper() + "\\")
        pg.click('#v-settings button[onclick="setSave()"]')
        pg.wait_for_function("document.getElementById('s_msg').textContent.length > 0",
                             timeout=10000)
        msg = pg.inner_text("#s_msg")
        assert msg.startswith("Not saved - ") and "FQC EL folder of Line B" in msg, msg
        with store.conn() as (cx, cur):
            assert db.get_config(cur)["pre_el_b_root"] == ""

        pg.fill("#s_b_pre_el", PRE_B)
        pg.click('#v-settings button[onclick="setSave()"]')
        # the card is drawn again from the server once the save is kept
        pg.wait_for_function(
            "Array.from(document.querySelectorAll('#v-settings .card-h .tag'))"
            ".some(function (t) { return t.textContent === 'Pre-EL primary OK'; })", timeout=15000)
        assert pg.input_value("#s_b_pre_el") == PRE_B
        assert "Pre-EL primary OK" in card(pg, "B").locator(".card-h .tag").all_text_contents()
        assert "Pre-EL primary —" in card(pg, "A").locator(".card-h .tag").all_text_contents()
        with store.conn() as (cx, cur):
            assert db.get_config(cur)["pre_el_b_root"] == PRE_B
        pg.wait_for_selector("#sourceRows tr:has-text('PRE-EL1-B')", timeout=10000)
        row = " ".join(pg.text_content("#sourceRows tr:has-text('PRE-EL1-B')").split())
        assert PRE_B in row and "OK" in row and "every minute" in row, row
        assert pg.errors == [], pg.errors


@test("the sources table's header names all six columns its rows have, and the "
      "folder placeholders read as real paths, one backslash where Windows has one")
def t_table_header_and_placeholders():
    world(pre_el_b_root=PRE_B)
    with H.browser() as b:
        pg = stations(b)
        pg.wait_for_selector("#sourceRows tr:has-text('PRE-EL1-B')", timeout=10000)
        head = pg.locator("table:has(#sourceRows) thead th").all_text_contents()
        assert head == ["Source", "Type", "Path", "Line", "State", "Columns / rule"], head
        cells = pg.locator("#sourceRows tr").first.locator("td").count()
        assert cells == len(head), (cells, head)
        ph = {f: pg.get_attribute(f, "placeholder")
              for f in ("#s_a_ss", "#s_a_el", "#s_b_pre_el", "#s_b_pre_el2", "#s_b_post_el")}
        assert ph == {"#s_a_ss": r"\\SS-A\share\results.csv", "#s_a_el": r"\\EL-A\output",
                      "#s_b_pre_el": r"\\PRE-EL-B\el", "#s_b_pre_el2": r"\\PRE-EL2-B\el",
                      "#s_b_post_el": r"\\POST-EL-B\el"}, ph
        assert pg.errors == [], pg.errors


BOTH = "ICON625R12A1522911"            # captured at Pre-EL (re-shot) and Post EL
NEITHER = "ICON625R12A1522912"         # captured at neither
PRE_A = os.path.join(SHARES, "pre_a")
PRE_A2 = os.path.join(SHARES, "pre_a2")     # Line A's secondary Pre-EL machine
POST_B = os.path.join(SHARES, "post_b")


def put(root, rel, name, at):
    d = os.path.join(root, *rel.split("/"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    open(p, "wb").close()
    t = datetime.datetime.fromisoformat(at).replace(tzinfo=clock.IST).timestamp()
    os.utime(p, (t, t))


def seed_journey():
    """BOTH: NG at Line A's primary Pre-EL, back from rework through the
    SECONDARY (the way the line runs), then Post EL OK."""
    for d in (PRE_A, PRE_A2, POST_B):
        shutil.rmtree(d, ignore_errors=True)
    world(pre_el_a_root=PRE_A, pre_el2_a_root=PRE_A2, post_el_b_root=POST_B)
    with store.conn() as (cx, cur):
        for i, s in enumerate((BOTH, NEITHER)):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": 625, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-10-15", "shift": 1,
                "sequence": i + 1, "state": "planned"})
    put(PRE_A, "2026-10-15/早班/Ribbon short", BOTH + ".jpg", "2026-10-15T13:07:34")
    put(PRE_A2, "2026-10-15/早班/OK", BOTH + ".jpg", "2026-10-15T13:10:14")
    put(POST_B, "2026-10-15/中班/OK", BOTH + ".jpg", "2026-10-15T16:42:05")
    with store.conn() as (cx, cur):
        assert elcap.run(db.get_config(cur), cur) == {"pre_el": 2, "post_el": 1}


def open_module(pg, serial):
    pg.fill("#qBox", serial)
    pg.click("#v-search .sp button")
    pg.wait_for_selector("#searchOut .crumb:has-text('%s')" % serial, timeout=10000)
    return pg.evaluate("""() => Array.from(document.querySelectorAll(
        '#searchOut .chain .node')).map(n => ({
          stage: n.querySelector('label').textContent,
          value: n.querySelector('.nv').textContent,
          detail: Array.from(n.querySelector('.nd').childNodes)
                    .filter(c => c.nodeType === 3).map(c => c.textContent),
          tag: n.querySelector('.ns .tag').textContent,
          tone: n.querySelector('.ns .tag').className}))""")


@test("Search & Trace: a module NG at Pre-EL, reworked and passed shows Pre-EL NG, "
      "Rework, Pre-EL Pass and Post EL after Produced; one captured at neither "
      "shows no such step - no empty step either way - and the chain still scrolls")
def t_journey_on_screen():
    seed_journey()
    with H.browser() as b:
        pg = H.open_page(b, "search")
        nodes = open_module(pg, BOTH)
        stages = [n["stage"] for n in nodes]
        assert stages == ["Allocated", "Produced", "Pre-EL", "Rework", "Pre-EL", "Post EL",
                          "FQC", "Packed", "Challan", "Gate pass"], stages
        ng, rw, ok, post = nodes[2:6]
        assert ng["value"] == "NG" and "t-rev" in ng["tone"], ng
        assert ng["detail"] == ["Ribbon short", "Line A · primary"], ng
        assert ng["tag"] == "15-10-2026 13:07 · shift A", ng
        assert rw["value"] == "Rework" and rw["tag"] == "3 min", rw
        assert rw["detail"] == ["after Ribbon short", "back at Pre-EL 15-10-2026 13:10"], rw
        assert ok["value"] == "Pass" and "t-pass" in ok["tone"], ok
        assert ok["detail"] == ["Line A · secondary"], ok
        assert post["value"] == "Pass" and post["detail"] == ["Line B"], post
        for n in (ng, rw, ok, post):
            assert n["value"].strip() and n["value"] != "—", n

        # ten nodes are wider than the card: the chain scrolls inside it, the
        # page itself does not
        chain = "#searchOut .chain"
        geo = pg.evaluate("""(sel) => { const c = document.querySelector(sel);
            return {sw: c.scrollWidth, cw: c.clientWidth,
                    ox: getComputedStyle(c).overflowX,
                    page: document.documentElement.scrollWidth - innerWidth}; }""", chain)
        assert geo["ox"] == "auto" and geo["sw"] > geo["cw"], geo
        assert geo["page"] <= 0, "the page scrolls sideways: %s" % geo
        pg.evaluate("(sel) => { const c = document.querySelector(sel); "
                    "c.scrollLeft = c.scrollWidth; }", chain)
        seen = pg.evaluate("""(sel) => { const c = document.querySelector(sel);
            const last = c.lastElementChild.getBoundingClientRect(),
                  box = c.getBoundingClientRect();
            return {left: c.scrollLeft, in: last.right <= box.right + 1 &&
                    last.left >= box.left - 1}; }""", chain)
        assert seen["left"] > 0 and seen["in"], seen

        nodes = open_module(pg, NEITHER)
        stages = [n["stage"] for n in nodes]
        assert stages == ["Allocated", "Produced", "FQC", "Packed", "Challan",
                          "Gate pass"], stages
        assert pg.errors == [], pg.errors


IN_REWORK = "ICON625R12A1522913"
REJECTED = "ICON625R12A1522914"


def seed_screen():
    """BOTH (reworked, then Post EL OK), one still in rework, one rejected at Post
    EL - all first imaged on 15-10-2026."""
    seed_journey()
    with store.conn() as (cx, cur):
        for i, s in enumerate((IN_REWORK, REJECTED)):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": "ISEN625-G12R",
                "wattage": 625, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-10-15", "shift": 1,
                "sequence": 10 + i, "state": "planned"})
    put(PRE_A, "2026-10-15/晚班/Cell Crack", IN_REWORK + ".jpg", "2026-10-15T22:02:25")
    put(POST_B, "2026-10-15/中班/Cell Crack", REJECTED + ".jpg", "2026-10-15T15:00:00")
    with store.conn() as (cx, cur):
        # REJECTED's NG at Post EL is Quality's to decide: a Needs Review item too
        assert elcap.run(db.get_config(cur), cur) == {"pre_el": 1, "post_el": 1,
                                                      "post_el_ng": 1}


@test("EL Stations on the page: after Production Entry for a Production Incharge, its "
      "KPIs and one row a module; a Result pick narrows it; a serial opens its journey; "
      "Quality has no such screen")
def t_screen_on_page():
    seed_screen()

    def rows(pg):
        return pg.evaluate("""() => Array.from(document.querySelectorAll('#elRows tr'))
            .filter(tr => !tr.hasAttribute('data-empty') && tr.style.display !== 'none')
            .map(tr => Array.from(tr.cells).map(c => c.textContent.trim()))""")

    with H.browser() as b:
        pg = H.open_page(b, None, role="Production Incharge")
        order = pg.evaluate("""() => Array.from(document.querySelectorAll('#sidenav .nav-i'))
            .filter(b => b.offsetParent !== null).map(b => b.getAttribute('data-v'))""")
        assert "elst" in order and order.index("elst") == order.index("prodentry") + 1, order
        pg.click('#sidenav [data-v="elst"]')
        pg.wait_for_selector("#v-elst.on #elRows", timeout=10000)
        pg.fill("#elFrom", "2026-10-15")
        pg.fill("#elTo", "2026-10-15")
        pg.wait_for_function("document.getElementById('elRows').textContent.indexOf('%s') >= 0"
                             % IN_REWORK, timeout=10000)
        pg.wait_for_timeout(300)
        k = {i: pg.text_content("#elK%d" % i) for i in range(1, 7)}
        assert k == {1: "2", 2: "0", 3: "2", 4: "2", 5: "1", 6: "1"}, k
        assert pg.text_content("#elK6d") == "1 awaiting Quality’s decision", \
            pg.text_content("#elK6d")
        assert "1 passed after rework · 1 still in rework" in pg.text_content("#elK3d")
        got = {r[0]: r for r in rows(pg)}
        assert set(got) == {BOTH, IN_REWORK, REJECTED}, got
        assert got[BOTH][2] == "Pass after rework" and got[BOTH][3] == "Ribbon short", got[BOTH]
        assert got[BOTH][5].endswith("(2 images) · primary + secondary"), got[BOTH]
        assert got[BOTH][4] == "1" and got[BOTH][6] == "Pass" and got[BOTH][9] == "A, B", got[BOTH]
        assert got[REJECTED][2] == "—" and got[REJECTED][6] == "NG awaiting Quality", \
            got[REJECTED]

        pg.select_option("#elResult", "Pre-EL: In rework")
        pg.wait_for_function("document.querySelectorAll('#elRows tr').length === 1 && "
                             "document.getElementById('elRows').textContent.indexOf('%s') >= 0"
                             % IN_REWORK, timeout=10000)
        opts = pg.eval_on_selector_all("#elResult option", "os => os.map(o => o.value)")
        assert opts == ["", "Pre-EL: Pass after rework", "Pre-EL: In rework", "Post EL: Pass",
                        "Post EL: NG"], opts

        pg.click("#elRows button.lnk")
        pg.wait_for_selector("#searchOut .crumb:has-text('%s')" % IN_REWORK, timeout=10000)
        stages = pg.eval_on_selector_all("#searchOut .chain .node label",
                                         "ls => ls.map(l => l.textContent)")
        assert stages[:4] == ["Allocated", "Produced", "Pre-EL", "Rework"], stages
        assert pg.errors == [], pg.errors

        q = H.open_page(b, None, role="Quality")
        assert not q.locator('#sidenav [data-v="elst"]').is_visible(), "Quality sees EL Stations"
        assert q.errors == [], q.errors


GHOST = "ICON625R12A1522915"           # imaged at Pre-EL, not in the master


@test("a Super Admin has EL Stations in the menu; its link for a module NOT in the master "
      "opens Search & Trace, which says so - and shows what the EL stations recorded, "
      "the steps and the images, instead of nothing")
def t_not_in_master_on_page():
    seed_screen()
    put(PRE_A, "2026-10-15/晚班/Cell Crack", GHOST + ".jpg", "2026-10-15T22:10:00")
    put(PRE_A, "2026-10-15/晚班/OK", GHOST + ".jpg", "2026-10-15T22:40:00")
    with store.conn() as (cx, cur):
        elcap.run(db.get_config(cur), cur)
    with H.browser() as b:
        pg = H.open_page(b, None)                                  # a Super Admin
        order = pg.evaluate("""() => Array.from(document.querySelectorAll('#sidenav .nav-i'))
            .filter(b => b.offsetParent !== null).map(b => b.getAttribute('data-v'))""")
        assert "elst" in order and order.index("elst") == order.index("prodentry") + 1, order
        pg.click('#sidenav [data-v="elst"]')
        pg.wait_for_selector("#v-elst.on #elRows", timeout=10000)
        pg.fill("#elFrom", "2026-10-15")
        pg.fill("#elTo", "2026-10-15")
        pg.wait_for_function("document.getElementById('elRows').textContent.indexOf('%s') >= 0"
                             % GHOST, timeout=10000)
        pg.click('#elRows button.lnk:has-text("%s")' % GHOST)
        pg.wait_for_selector("#searchOut .card h3:has-text('EL stations')", timeout=10000)
        assert "not in the serial master" in pg.text_content("#searchOut .note")
        stages = pg.eval_on_selector_all("#searchOut .chain .node label",
                                         "ls => ls.map(l => l.textContent)")
        assert stages == ["Pre-EL", "Rework", "Pre-EL"], stages
        log = pg.evaluate("""() => Array.from(document.querySelectorAll('#searchOut .work tbody tr'))
            .map(tr => tr.cells[1].textContent.trim())""")
        assert log == ["Pre-EL · NG", "Pre-EL · Pass"], log
        assert pg.errors == [], pg.errors


def allocate_on(day, serials):
    """An allocation made on `day` (08:00) holding these serials, none produced."""
    with store.conn() as (cx, cur):
        iid = store.insert(cur, "indent", {"indent_no": "EL-UI/1", "indent_date": day,
                                           "customer": "STOCK", "build_type": "make_to_stock",
                                           "created_by": "test"})
        lid = store.insert(cur, "indent_line", {"indent_id": iid, "line_no": 1,
                                                "item_description": "625", "model": "ISEN625-G12R",
                                                "wattage": 625, "qty": 100, "dcr": "DCR"})
        aid = store.insert(cur, "allocation", {
            "indent_line_id": lid, "model": "ISEN625-G12R", "wattage": 625,
            "date_produced": day, "shift": 1, "qty": len(serials), "seq_from": 1,
            "seq_to": len(serials), "created_at": day + "T08:00:00", "created_by": "test"})
        for s in serials:
            cur.execute("UPDATE serial SET alloc_id=%s WHERE serial=%s", (aid, s))


@test("EL in the dashboards' own widgets (17 Oct 2026): the Stage funnel has Pre-EL and "
      "Post EL between Allocated and Produced; both donuts split 'not yet produced' by "
      "where the EL stations have it; Where the plant stands has a Pre-EL and a Post EL "
      "row; Needs a decision the Post EL NG; Line & shift a Pre-EL first-pass column")
def t_dashboard_widgets_on_page():
    seed_screen()
    allocate_on("2026-10-15", [BOTH, IN_REWORK, REJECTED, NEITHER])
    legend = """(id) => Object.fromEntries(Array.from(document.querySelectorAll('#' + id + ' .lg'))
        .map(x => [x.querySelectorAll('span')[0].textContent, x.querySelector('b').textContent]))"""
    with H.browser() as b:
        pg = H.open_page(b, None, role="Production Incharge")
        pg.evaluate("go('proddash')")
        pg.wait_for_timeout(500)
        pg.evaluate("""() => { document.getElementById('pdFrom').value = '2026-10-15';
                        document.getElementById('pdTo').value = '2026-10-15'; renderProd(); }""")
        pg.wait_for_function("""() => Array.from(document.querySelectorAll('#pdFunnel .fstep'))
            .some(s => s.querySelector('.fl').textContent === 'Pre-EL' &&
                       s.querySelector('.fv').textContent === '2')""", timeout=15000)
        funnel = pg.evaluate("""() => Array.from(document.querySelectorAll('#pdFunnel .fstep'))
            .map(s => [s.querySelector('.fl').textContent, s.querySelector('.fv').textContent])""")
        assert [f[0] for f in funnel] == ["Allocated", "Pre-EL", "Post EL", "Produced", "FQC done",
                                          "Passed", "Packed", "Dispatched"], funnel
        assert funnel[1] == ["Pre-EL", "2"] and funnel[2] == ["Post EL", "2"], funnel
        got = pg.evaluate(legend, "pdLegend")
        want = {"Through EL, production not entered yet": "1", "In rework at Pre-EL": "1",
                "NG at Post EL, with Quality": "1", "Not yet produced, not on the line yet": "1"}
        assert all(got.get(k) == v for k, v in want.items()), got
        head = pg.evaluate("""() => Array.from(document.querySelectorAll(
            '#pdLineRows')[0].parentNode.querySelectorAll('thead th')).map(t => t.textContent)""")
        assert head[-1] == "Pre-EL first pass", head
        cells = pg.evaluate("""() => Array.from(document.querySelectorAll('#pdLineRows tr'))
            .map(tr => Array.from(tr.cells).map(c => c.textContent.trim()))""")
        el_cells = sorted((r[0], r[1], r[-1]) for r in cells if len(r) > 7)
        assert el_cells == [("A-Line", "A", "0%0 of 1"), ("A-Line", "C", "0%0 of 1")], cells
        assert all(r[-2] == "—" for r in cells if len(r) > 7), \
            "a shift with no production entry yet is not '0% against plan'"

        pg.evaluate("go('mgmt')")
        pg.wait_for_timeout(500)
        pg.evaluate("""() => { document.getElementById('mgFrom').value = '2026-10-15';
                        document.getElementById('mgTo').value = '2026-10-15'; renderMgmt(); }""")
        # the first render was on today's (empty) dates - wait for the 15th's
        pg.wait_for_function("""() => document.getElementById('mgLegend').textContent
            .indexOf('In rework at Pre-EL') >= 0 &&
            document.getElementById('mgSections').textContent.indexOf('1 still in rework') >= 0""",
                             timeout=15000)
        got = pg.evaluate(legend, "mgLegend")
        assert got.get("In rework at Pre-EL") == "1" and \
            got.get("Allocated, not yet produced, not on the line yet") == "1", got
        sect = {r[0]: r for r in pg.evaluate("""() => Array.from(document.querySelectorAll(
            '#mgSections tr')).map(tr => Array.from(tr.cells).map(c => c.textContent.trim()))""")}
        assert sect["Pre-EL"][1:4] == ["First-pass yield · 1 still in rework", "0.0%", "Watch"], sect
        assert sect["Post EL"][1:4] == ["NG awaiting Quality’s decision", "1", "Watch"], sect
        order = list(sect)
        assert order.index("Pre-EL") == order.index("Production") + 1, order
        blocked = pg.text_content("#mgBlocked")
        if pg.evaluate("can('review')"):
            assert "NG at Post EL, awaiting Quality’s decision" in blocked, blocked
        assert pg.errors == [], pg.errors


@test("the Production Dashboard and the Management Overview show an EL stations card "
      "under their KPI tiles with the period's figures; its button opens EL Stations")
def t_dashboards_on_page():
    seed_screen()
    want = {"pre_el": ["Pre-EL", "2", "0", "1", "1", "—", "0.0%"],
            "post_el": ["Post EL", "2", "1", "—", "—", "1 (1 awaiting Quality)", "50.0%"]}

    def card(pg, view, card_id, frm, to, render):
        pg.evaluate("go(%r)" % view)
        pg.wait_for_timeout(500)
        pg.evaluate("""([a, b, f]) => { document.getElementById(a).value = '2026-10-15';
                        document.getElementById(b).value = '2026-10-15'; window[f](); }""",
                    [frm, to, render])
        pg.wait_for_function("""(id) => { const c = document.getElementById(id);
            const tr = c && c.querySelector('tr[data-el=post_el]');
            return !!tr && tr.cells.length > 1 && tr.cells[1].textContent.trim() === '2'; }""",
                             arg=card_id, timeout=15000)
        got = pg.evaluate("""(id) => Object.fromEntries(Array.from(document.querySelectorAll(
            '#' + id + ' tbody tr')).map(tr => [tr.getAttribute('data-el'),
            Array.from(tr.cells).map(c => c.textContent.trim())]))""", card_id)
        under = pg.evaluate("""(id) => { const p = document.getElementById(id).previousElementSibling;
            return p.classList.contains('grid') && !!p.querySelector('.kpi'); }""", card_id)
        return got, under

    with H.browser() as b:
        pg = H.open_page(b, None, role="Production Incharge")
        got, under = card(pg, "proddash", "pdElCard", "pdFrom", "pdTo", "renderProd")
        assert got == want, got
        assert under, "the card is not right under the KPI tiles"
        got, under = card(pg, "mgmt", "mgElCard", "mgFrom", "mgTo", "renderMgmt")
        assert got == want and under, got
        pg.click("#mgElCard button:has-text('Open EL Stations')")
        pg.wait_for_selector("#v-elst.on", timeout=10000)
        assert pg.errors == [], pg.errors


@test("Needs Review: a Post EL NG is under the Quality tab, red, 'Quality only' for an "
      "Incharge; Quality decide - close it with a reason - and it is gone; the journey's "
      "Quality Review step then shows their decision")
def t_post_el_review_on_page():
    seed_screen()

    def review_rows(pg):
        return pg.evaluate("""() => Array.from(document.querySelectorAll('#rvRows tr'))
            .filter(tr => tr.style.display !== 'none' && tr.cells.length > 2)
            .map(tr => ({serial: tr.cells[1].textContent.trim(),
                         flag: tr.cells[2].textContent.trim(),
                         tone: (tr.cells[2].querySelector('.tag') || {}).className || '',
                         stage: tr.cells[3].textContent.trim(),
                         detail: tr.cells[4].textContent.trim(),
                         action: tr.cells[6].textContent.trim()}))""")

    def quality_tab(pg):
        pg.evaluate("go('review')")
        pg.wait_for_function("document.querySelectorAll('#rvRows tr').length > 0", timeout=15000)
        pg.click("#v-review .card-h .seg button:has-text('Quality')")
        pg.wait_for_timeout(400)
        return [r for r in review_rows(pg) if r["serial"] == REJECTED]

    with H.browser() as b:
        pi = H.open_page(b, None, role="Production Incharge")
        got = quality_tab(pi)
        assert len(got) == 1 and got[0]["action"] == "Quality only", got

        pg = H.open_page(b, None, role="Quality")
        got = quality_tab(pg)
        assert len(got) == 1, got
        r = got[0]
        assert r["flag"] == "Post EL NG" and "t-fail" in r["tone"], r
        assert r["stage"] == "Post EL · Line B" and r["detail"].startswith("Cell Crack at Post EL"), r
        assert r["action"] == "Reviewed…", r
        assert "1 NG at Post EL" in pg.text_content("#v-review .kpi:nth-child(2) .d"), \
            pg.text_content("#v-review .kpi:nth-child(2)")
        pg.click("#rvRows tr:has-text('%s') button:has-text('Reviewed')" % REJECTED)
        pg.wait_for_selector("#mdl.on #revWhy", timeout=10000)
        pg.fill("#revWhy", "crack confirmed under the light - scrapped")
        pg.click("#mdl.on .card-f .btn-primary")
        pg.wait_for_function("""(s) => !Array.from(document.querySelectorAll('#rvRows tr'))
            .some(tr => tr.style.display !== 'none' && tr.textContent.indexOf(s) >= 0)""",
                             arg=REJECTED, timeout=15000)
        with store.conn() as (cx, cur):
            row = store.one(cur, "SELECT status, resolution, reason FROM review_item "
                                 "WHERE type='post_el_ng'")
        assert (row["status"], row["resolution"], row["reason"]) == \
            ("resolved", "reviewed", "crack confirmed under the light - scrapped"), dict(row)
        pg.evaluate("go('search')")
        pg.wait_for_selector("#qBox", state="visible", timeout=10000)
        nodes = open_module(pg, REJECTED)
        stages = [n["stage"] for n in nodes]
        assert stages[stages.index("Post EL") + 1] == "Quality Review", stages
        qr = nodes[stages.index("Quality Review")]
        assert qr["value"] == "Reviewed" and \
            qr["detail"][0] == "crack confirmed under the light - scrapped", qr
        assert pg.errors == [] and pi.errors == [], (pg.errors, pi.errors)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")   # a FAIL naming a folder like
    # 早班 must print on a cp1252 console, not crash the run
    passed = failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %s" % name)
                passed += 1
            except Exception as e:
                print("  FAIL  %s  %s" % (name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        H.cleanup()
        shutil.rmtree(SHARES, ignore_errors=True)
    sys.exit(1 if failed else 0)
