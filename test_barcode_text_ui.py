"""
ICON TRACE - the packing list's barcode text, measured in a real browser.

    python test_barcode_text_ui.py        (needs Playwright + Chromium)

"Always centred on the barcode" is a claim about pixels, so it is checked in
pixels: each barcode on the sheet is photographed and the ink of its text is
compared with the ink of its bars. Letter-spacing is the trap - browsers add
it after the last letter too, so plain centred text drifts left by half a
space. Also here: the sheet stays inside the page whatever the setting, the
Settings preview is drawn at the width the sheet really has, and the Settings
card saves for a Super Admin and is locked, with the reason, for an Admin.
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
    with store.conn() as (cx, cur):
        db.set_config(cur, dict(bc.TEXT_DEFAULTS, **{"bc_text_" + k: str(v) for k, v in kw.items()}))


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


@test("the Settings preview box is the width of the real printed barcode cell (within 1 mm)")
def t_preview_cell_is_true():
    _, box = T.packed_box()
    with H.browser() as b:
        pg = sheet(b, box, width=A4_PRINTABLE_PX, media="print")
        cell = pg.evaluate("""() => { const td = document.querySelector('td.bc'), cs = getComputedStyle(td);
            return td.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight); }""") / MM
        assert abs(cell - H.APP.PACKING_LIST_BARCODE_CELL_MM) <= 1.0, \
            "the packing list cell is %.1f mm; PACKING_LIST_BARCODE_CELL_MM says %d - update it" % (
                cell, H.APP.PACKING_LIST_BARCODE_CELL_MM)
        pg.close()


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
        assert T.stored() == bc.TEXT_DEFAULTS, T.stored()
        pg.fill("#bt_size", "14"); pg.fill("#bt_spacing", "0")
        pg.uncheck("#bt_bold")
        pg.click('button[onclick="btSave()"]')
        pg.wait_for_timeout(1200)
        s = T.stored()
        assert s["bc_text_size"] == "14" and s["bc_text_font"] == "consolas" \
            and s["bc_text_bold"] == "0", s
        assert not pg.errors, pg.errors
        pg.close()


@test("Settings: an Admin sees the card and its preview, every control locked with the reason")
def t_settings_admin_locked():
    T.packed_box()
    with H.browser() as b:
        pg = settings_card(b, "Admin")
        for sel in ("#bt_font", "#bt_size", "#bt_spacing", "#bt_gap", "#bt_bold",
                    'button[onclick="btSave()"]'):
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
