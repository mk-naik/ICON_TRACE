"""
ICON TRACE - the packing list's barcode (bars and text), measured in a real browser.

    python test_barcode_text_ui.py        (needs Playwright + Chromium)

"Always centred on the barcode" is a claim about pixels, so it is checked in
pixels: each barcode on the sheet is photographed and the ink of its text is
compared with the ink of its bars. Letter-spacing is the trap - browsers add
it after the last letter too, so plain centred text drifts left by half a
space. Also here: the sheet stays inside the page whatever the setting, the
Settings preview is drawn at the width the sheet really has (bars - module
width, height, quiet zone - and text), and the Settings card saves for a Super
Admin and is locked, with the reason, for an Admin.
"""

import io, os, shutil, sys, traceback

import ui_harness as H                                       # sets the DB path first
import store                                                 # noqa: E402
import db                                                    # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_barcode as bc                                    # noqa: E402
import test_barcode_text as T                                # noqa: E402  (its packed_box)

_results = []
MM = 96 / 25.4
A4_PRINTABLE_PX = round(194 * MM)          # @page A4 with 8 mm margins


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def set_text(**kw):
    """Every barcode setting back to its default, then these: text ones by
    their short name (size=14), bar ones as bar_width / bar_height / bar_quiet."""
    key = lambda k: "bc_" + k if k.startswith("bar_") else "bc_text_" + k
    with store.conn() as (cx, cur):
        db.set_config(cur, dict(bc.SETTING_DEFAULTS, **{key(k): str(v) for k, v in kw.items()}))


def sheet(b, box, width=1400, media="screen", scale=1):
    pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=scale)
    pg.context.add_cookies([{"name": "icon_sid", "value": AUTH.make_session_id(),
                             "domain": "127.0.0.1", "path": "/"}])
    pg.emulate_media(media=media)
    pg.goto(H.base_url() + "/box/%d/sheet" % box)
    pg.wait_for_load_state("networkidle")
    pg.evaluate("document.fonts.ready")
    return pg


def ink_offsets(pg, scale):
    """For each barcode: (text ink centre - bars ink centre) in CSS px."""
    from PIL import Image
    out = []
    for wrap in pg.query_selector_all(".bcw"):
        svg_h = wrap.eval_on_selector("svg", "e => e.getBoundingClientRect().height")
        im = Image.open(io.BytesIO(wrap.screenshot())).convert("L")
        px, cut = im.load(), int(svg_h * scale)

        def centre(y0, y1):
            xs = [x for x in range(im.width) if any(px[x, y] < 128 for y in range(y0, y1))]
            return (min(xs) + max(xs)) / 2.0

        out.append((centre(0, cut) - centre(cut + 2, im.height)) / -scale)
    return out


def box_offsets(pg):
    """For each barcode: centre of the text's advance box - centre of the bars,
    in CSS px. The browser adds letter-spacing after the last letter too, so the
    box it reports is one spacing wider than the visible text; that is taken
    off, as it is in icon_barcode.text_style."""
    return pg.eval_on_selector_all(".bcw", """ws => ws.map(w => {
        const s = w.querySelector('svg').getBoundingClientRect();
        const t = w.querySelector('.bct'), r = t.getBoundingClientRect();
        const sp = parseFloat(getComputedStyle(t).letterSpacing) || 0;
        return r.left + (r.width - sp) / 2 - (s.left + s.width / 2); })""")


@test("the text is centred on the bars of every barcode - Jan-Sep and Oct-Dec "
      "widths alike - at the defaults and with letter spacing: its box within 0.5 px, "
      "and its painted ink within 0.5 px of where the same text sits unspaced")
def t_centred():
    # Two measures, because ink alone cannot tell the page from the typeface.
    # Centring is a property of the text's box (that is what Bartender and
    # Zebra Designer centre). The ink of "ICON...1" in Arial Bold sits 1.2 px
    # left of its box - the "1" has a wide right bearing - on any layout, so
    # the ink is compared with the SAME text and font at no letter spacing,
    # which cancels the bearings and leaves exactly what the setting moved.
    _, box = T.packed_box()
    with H.browser() as b:
        for kw in ({}, {"font": "consolas", "spacing": 4, "bold": 0},
                   {"font": "arial_black", "spacing": 2, "size": 12}):
            set_text(**kw)
            pg = sheet(b, box, scale=3)
            lay, ink = box_offsets(pg), ink_offsets(pg, 3)
            pg.close()
            set_text(**dict(kw, spacing=0))
            pg = sheet(b, box, scale=3)
            own = ink_offsets(pg, 3)
            pg.close()
            assert len(lay) == len(ink) == len(own) == len(T.SERIALS), (lay, ink, own)
            assert all(abs(o) <= 0.5 for o in lay), (kw, ["%.2f" % o for o in lay])
            assert all(abs(i - o) <= 0.5 for i, o in zip(ink, own)), \
                (kw, ["%.2f" % i for i in ink], ["%.2f" % o for o in own])
    set_text()


@test("the sheet stays inside the page - on screen and at A4 print width - at the "
      "defaults and at a large setting the Settings preview accepts")
def t_fits_page():
    _, box = T.packed_box()
    with H.browser() as b:
        for kw in ({}, {"size": 14, "spacing": 1, "font": "consolas"}):
            set_text(**kw)
            for width, media in ((1400, "screen"), (A4_PRINTABLE_PX, "print")):
                pg = sheet(b, box, width=width, media=media)
                r = pg.evaluate("""() => ({
                    over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                    table: document.querySelector('table.uid').getBoundingClientRect().width,
                    sheet: (document.querySelector('.sheet') || document.body).getBoundingClientRect().width})""")
                assert r["over"] <= 0, (kw, media, r)
                assert r["table"] <= r["sheet"] + 1, (kw, media, r)
                pg.close()
    set_text()


@test("an Oct-Dec barcode prints 22 modules (5.59 mm) wider than a Jan-Sep one")
def t_widths_follow_serial():
    _, box = T.packed_box()
    with H.browser() as b:
        pg = sheet(b, box)
        w = pg.eval_on_selector_all("td.bc svg", "els => els.map(e => e.getBoundingClientRect().width)")
        assert abs((w[1] - w[0]) / MM - 22 * 0.254) < 0.05, ["%.2f mm" % (x / MM) for x in w]
        pg.close()


@test("the Settings preview box is the real printed barcode cell, up to its border: "
      "the print area and the padding each side (within 1 mm)")
def t_preview_cell_is_true():
    _, box = T.packed_box()
    A = H.APP
    with H.browser() as b:
        pg = sheet(b, box, width=A4_PRINTABLE_PX, media="print")
        r = pg.evaluate("""() => { const td = document.querySelector('td.bc'), cs = getComputedStyle(td);
            return {pad: parseFloat(cs.paddingLeft), room: td.clientWidth,
                    area: td.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)}; }""")
        assert abs(r["area"] / MM - A.PACKING_LIST_BARCODE_CELL_MM) <= 1.0, \
            "the packing list cell prints %.1f mm; PACKING_LIST_BARCODE_CELL_MM says %d - update it" % (
                r["area"] / MM, A.PACKING_LIST_BARCODE_CELL_MM)
        assert abs(r["pad"] / MM - A.PACKING_LIST_BARCODE_PAD_MM) <= 0.2, \
            "the cell's padding is %.2f mm; PACKING_LIST_BARCODE_PAD_MM says %d" % (
                r["pad"] / MM, A.PACKING_LIST_BARCODE_PAD_MM)
        assert abs(r["room"] / MM - A.PACKING_LIST_BARCODE_ROOM_MM) <= 1.0, r
        pg.close()
        # and the Settings preview box is exactly that room
        card = settings_card(b, "Super Admin")
        w = card.eval_on_selector("#bt_cell", "e => parseFloat(getComputedStyle(e).width)") / MM
        assert abs(w - A.PACKING_LIST_BARCODE_ROOM_MM) < 0.01, w
        card.close()


def settings_card(b, role):
    pg = H.open_page(b, "admin", wait_ms=1500, role=role)
    pg.click('#adTabs button[onclick*="\'stations\'"]')
    pg.wait_for_selector("#bt_font", timeout=8000)
    pg.wait_for_timeout(400)
    return pg


@test("Settings: the preview follows each change, warns before a size that overruns "
      "the cell, and a Super Admin's Save stores it")
def t_settings_super_admin():
    T.packed_box()
    with H.browser() as b:
        pg = settings_card(b, "Super Admin")
        w0 = pg.eval_on_selector("#bt_text", "e => e.getBoundingClientRect().width")
        pg.fill("#bt_size", "14")
        pg.select_option("#bt_font", "consolas")
        assert pg.eval_on_selector("#bt_text", "e => e.getBoundingClientRect().width") > w0
        assert "Consolas" in pg.eval_on_selector("#bt_text", "e => e.style.fontFamily")
        assert pg.text_content("#bt_warn") == ""
        pg.fill("#bt_size", "20"); pg.fill("#bt_spacing", "6")
        assert "Wider than the packing list cell" in pg.text_content("#bt_warn")
        # in range for the server, but it would run off the page: not saved
        pg.click('button[onclick="btSave()"]')
        pg.wait_for_timeout(800)
        assert "Not saved" in pg.text_content("#bt_msg"), pg.text_content("#bt_msg")
        assert T.stored() == bc.SETTING_DEFAULTS, T.stored()
        pg.fill("#bt_size", "14"); pg.fill("#bt_spacing", "0")
        pg.uncheck("#bt_bold")
        pg.click('button[onclick="btSave()"]')
        pg.wait_for_timeout(1200)
        s = T.stored()
        assert s["bc_text_size"] == "14" and s["bc_text_font"] == "consolas" \
            and s["bc_text_bold"] == "0", s
        assert not pg.errors, pg.errors
        pg.close()


def svg_mm(pg, sel):
    """(width, height) in mm of the first element matching sel, as drawn."""
    r = pg.eval_on_selector(sel, "e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
    return r[0] / MM, r[1] / MM


@test("Settings: the bars are controls too - the preview is redrawn at the module width, "
      "height and quiet zone typed, shows its size, warns when it cannot fit the cell, "
      "refuses to save then, and Reset puts the standard values back")
def t_settings_bars_preview():
    T.packed_box()
    modules = bc.code128_modules(H.APP.BC_SAMPLE_SERIAL)          # 211
    with H.browser() as b:
        pg = settings_card(b, "Super Admin")
        w, h = svg_mm(pg, "#bt_wrap svg")
        assert abs(w - (modules + 20) * 0.254) < 0.1 and abs(h - 11) < 0.05, (w, h)
        pg.fill("#bt_barw", "0.3")
        w, h = svg_mm(pg, "#bt_wrap svg")
        assert abs(w - (modules + 20) * 0.3) < 0.1, w
        assert pg.text_content("#bt_barwide").strip() == "%.1f mm" % ((modules + 20) * 0.3)
        assert "3.54 dots at 300 dpi" in pg.text_content("#bt_dots"), pg.text_content("#bt_dots")
        pg.fill("#bt_barh", "15")
        assert abs(svg_mm(pg, "#bt_wrap svg")[1] - 15) < 0.05
        row = float(pg.text_content("#bt_row"))
        assert row > 15 + 3, "the row height ignores the bars: %s" % row
        pg.fill("#bt_quiet", "14")
        w, h = svg_mm(pg, "#bt_wrap svg")
        assert abs(w - (modules + 28) * 0.3) < 0.1, w
        # the bars still start where the quiet zone says: nothing is clipped
        edge = pg.evaluate("""() => { const s = document.querySelector('#bt_wrap svg'), g = s.querySelector('g'),
            sr = s.getBoundingClientRect(), gr = g.getBoundingClientRect();
            return [(gr.left - sr.left) / 3.7795, (sr.right - gr.right) / 3.7795]; }""")
        assert abs(edge[0] - 14 * 0.3) < 0.1 and abs(edge[1] - 14 * 0.3) < 0.1, edge
        assert pg.text_content("#bt_warn") == ""
        # the quiet zones are drawn (shaded), at the width typed, one each end
        q = pg.evaluate("""() => [...document.querySelectorAll('#bt_wrap svg rect[id^=bt_q]')].map(r => {
            const b = r.getBoundingClientRect(), s = document.querySelector('#bt_wrap svg').getBoundingClientRect();
            return [(b.left - s.left) / 3.7795, b.width / 3.7795]; })""")
        q.sort()                                    # left one first, whatever the DOM order
        assert len(q) == 2 and abs(q[0][1] - 14 * 0.3) < 0.1 and abs(q[1][1] - 14 * 0.3) < 0.1, q
        assert abs(q[0][0]) < 0.1 and abs(q[1][0] - (modules + 14) * 0.3) < 0.1, q
        # too wide for the cell: said at once, with the numbers, and Save refuses
        # before asking the server
        pg.fill("#bt_barw", "0.4")
        warn = pg.text_content("#bt_warn")
        assert "Wider than the packing list cell" in warn, warn
        assert "quiet zones (shaded)" in warn and "mm up to its border" in warn, warn
        assert "%.1f mm" % ((modules + 28) * 0.4) in warn, warn
        # a barcode that LOOKS short of the cell can still be too wide: its blank
        # quiet zones count. 0.33 mm x (211 + 2 x 25 modules) = 86 mm
        pg.fill("#bt_barw", "0.33"); pg.fill("#bt_quiet", "25")
        assert "Wider than the packing list cell" in pg.text_content("#bt_warn")
        ink = (modules * 0.33)
        assert ink < H.APP.PACKING_LIST_BARCODE_ROOM_MM - 8, "the bars alone would fit with room to spare"
        pg.fill("#bt_quiet", "14"); pg.fill("#bt_barw", "0.4")
        pg.click('button[onclick="btSave()"]')
        pg.wait_for_timeout(600)
        assert "Not saved" in pg.text_content("#bt_msg"), pg.text_content("#bt_msg")
        assert T.stored() == bc.SETTING_DEFAULTS, T.stored()
        # Reset: the standard values, in the fields, nothing saved
        pg.click('button[onclick="btReset()"]')
        assert pg.input_value("#bt_barw") == "0.254" and pg.input_value("#bt_barh") == "11" \
            and pg.input_value("#bt_quiet") == "10"
        w, h = svg_mm(pg, "#bt_wrap svg")
        assert abs(w - (modules + 20) * 0.254) < 0.1 and abs(h - 11) < 0.05, (w, h)
        assert pg.text_content("#bt_warn") == ""
        assert not pg.errors, pg.errors
        pg.close()


@test("Settings: bars saved from the card are what the packing list prints - the "
      "widest the cell holds included - inside the page, with the text still "
      "centred on them")
def t_settings_bars_saved_and_printed():
    _, box = T.packed_box()
    with H.browser() as b:
        # 0.36 mm x 231 modules = 83.2 mm: more than the 80 mm print area, within
        # the 84 mm up to the border - allowed, and centred so it spills evenly
        for width, height, quiet in (("0.3", "14", "12"), ("0.346", "9", "10"),
                                     ("0.36", "9", "10")):
            set_text()
            pg = settings_card(b, "Super Admin")
            pg.fill("#bt_barw", width); pg.fill("#bt_barh", height); pg.fill("#bt_quiet", quiet)
            assert pg.text_content("#bt_warn") == "", pg.text_content("#bt_warn")
            pg.click('button[onclick="btSave()"]')
            pg.wait_for_timeout(1500)          # the save, then the card reloads itself
            s = T.stored()
            assert (s["bc_bar_width"], s["bc_bar_height"], s["bc_bar_quiet"]) == (width, height, quiet), s
            assert not pg.errors, pg.errors
            pg.close()
            q = int(quiet)
            for pw, media in ((1400, "screen"), (A4_PRINTABLE_PX, "print")):
                sp = sheet(b, box, width=pw, media=media)
                got = sp.eval_on_selector_all(
                    "td.bc svg", "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; })")
                want = [(m + 2 * q) * float(width) for m in (189, 211)]
                assert all(abs(g[0] / MM - w) < 0.1 and abs(g[1] / MM - float(height)) < 0.05
                           for g, w in zip(got, want)), (width, height, quiet, media,
                                                         [(g[0] / MM, g[1] / MM) for g in got], want)
                r = sp.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                assert r <= 0, (width, media, "the sheet runs past the page", r)
                lay = box_offsets(sp)
                assert all(abs(o) <= 0.5 for o in lay), (width, media, lay)
                # centred in its cell, and the blank quiet zone stays inside the
                # border - spilled evenly, never against the line
                gaps = sp.evaluate("""() => [...document.querySelectorAll('td.bc')].map(td => {
                    const t = td.getBoundingClientRect(), s = td.querySelector('svg').getBoundingClientRect();
                    return [s.left - t.left, t.right - s.right]; })""")
                assert all(g[0] >= 1 and g[1] >= 1 for g in gaps), \
                    (width, media, "the barcode reaches the cell border", gaps)
                assert all(abs(g[0] - g[1]) <= 1 for g in gaps), \
                    (width, media, "the barcode is off-centre in its cell", gaps)
                sp.close()
    set_text()


@test("Settings: an Admin sees the card and its preview, every control locked with the reason")
def t_settings_admin_locked():
    T.packed_box()
    with H.browser() as b:
        pg = settings_card(b, "Admin")
        for sel in ("#bt_font", "#bt_size", "#bt_spacing", "#bt_gap", "#bt_bold",
                    "#bt_barw", "#bt_barh", "#bt_quiet",
                    'button[onclick="btSave()"]', 'button[onclick="btReset()"]'):
            assert pg.is_disabled(sel), sel + " is editable by an Admin"
            assert "Super Admin" in (pg.get_attribute(sel, "title") or ""), sel
        assert pg.is_visible("#bt_cell svg")
        pg.close()


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
    sys.exit(1 if failed else 0)
