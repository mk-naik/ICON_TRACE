"""
ICON TRACE - the packing list's barcode settings (the bars and the text under
them), through the server.

    python test_barcode_text.py

Bartender and Zebra Designer let the person who designs a label choose the
module width and height of a barcode, and the font, size, letter spacing, bold,
italic and underline of the text under it. Here those are Settings (Super Admin
writes, everyone else reads), the packing list prints with them, and the text is
always centred on the bars and always below them. These tests hold the server's
side: what is accepted, what is refused and why (a width the cell cannot hold,
too), that a refusal stores nothing, and that the sheet carries the stored
values. test_barcode_text_ui.py measures the printed result in a real browser.
"""

import csv, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_bctext_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402
import icon_barcode as bc                                    # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


MODEL = "ISEN625-G12R"
SS = os.path.join(TMP, "ss.csv")
EL = os.path.join(TMP, "el", "OK")
os.makedirs(EL)
# one Jan-Sep serial and one Oct-Dec serial: different barcode widths
SERIALS = ["ICON625R1290710001", "ICON625R12A0710002"]


def stored():
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    return {k: cfg[k] for k in bc.SETTING_DEFAULTS}


def client(role="Super Admin", login_id=None):
    c = APP.app.test_client()
    AUTH.test_login(c, role=role, login_id=login_id)
    return c


def packed_box():
    """A closed pallet holding SERIALS, built the way the plant builds one."""
    store.wipe()
    AUTH.ensure_auth_schema()
    rows = []
    for i, s in enumerate(SERIALS):
        open(os.path.join(EL, s + ".jpg"), "w").close()
        rows.append(["2026-09-09 10:0%d:00" % i, s, "630.5", "12.1", "48.9",
                     "11.8", "52.5", "96.1", "0.41", "0.4", "210.0", "23.1",
                     "25", "25", "1000"])
    with open(SS, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_csv_path": SS, "el_root": os.path.dirname(EL),
                            "ss_a_csv_path": "", "ss_b_csv_path": "",
                            "el_a_root": "", "el_b_root": ""})
        for i, s in enumerate(SERIALS):
            store.insert(cur, "serial", {
                "serial": s, "build_instance": 1, "model": MODEL,
                "wattage": 625, "customer": "STOCK", "dcr": "DCR",
                "format_version": 2, "date_produced": "2026-09-09",
                "shift": 1, "sequence": i, "state": "planned"})
    c = client()
    for s in SERIALS:
        assert c.post("/api/fqc", json={"serial": s, "outcome": "pass"}).status_code == 200
    b = c.post("/api/box/open", json={"grade": "A", "model": MODEL,
                                      "capacity": len(SERIALS)}).get_json()
    for s in SERIALS:
        assert c.post("/api/box/%d/scan" % b["box_id"], json={"serial": s}).status_code == 200
    c.post("/api/box/%d/close" % b["box_id"], json={})
    return c, b["box_id"]


@test("out of the box: Arial, 10 pt, bold, no spacing - and the sheet prints with it")
def t_defaults():
    c, box = packed_box()
    assert stored() == bc.SETTING_DEFAULTS, stored()
    html = c.get("/box/%d/sheet" % box).get_data(as_text=True)
    assert html.count('class="bct"') == len(SERIALS), "a barcode has no text under it"
    assert "font-family:Arial, Helvetica, sans-serif;font-size:10pt;font-weight:700" in html


@test("a Super Admin's save is stored, normalised, and the sheet prints with it")
def t_super_admin_saves():
    c, box = packed_box()
    r = c.post("/api/settings", json={
        "bc_text_font": "consolas", "bc_text_size": "12.50",
        "bc_text_spacing": "1.5", "bc_text_gap": "1", "bc_text_bold": "false",
        "bc_text_italic": "true", "bc_text_underline": "0"})
    assert r.status_code == 200, r.get_json()
    s = stored()
    assert s["bc_text_font"] == "consolas" and s["bc_text_size"] == "12.5", s
    assert s["bc_text_bold"] == "0" and s["bc_text_italic"] == "1", s
    html = c.get("/box/%d/sheet" % box).get_data(as_text=True)
    for want in ("font-size:12.5pt", "font-weight:400", "font-style:italic",
                 "letter-spacing:1.5pt;margin-right:-1.5pt", "margin-top:1mm"):
        assert want in html, want
    # Jinja escapes the font stack's quotes; the browser reads them back
    assert "Consolas, &#39;Courier New&#39;, monospace" in html


@test("bad values are refused with the reason, and a refused save stores nothing - "
      "not even its good values")
def t_refusals():
    c, _ = packed_box()
    for body, word in (({"bc_text_font": "Comic Sans"}, "font"),
                       ({"bc_text_size": "40"}, "6 to 20"),
                       ({"bc_text_size": "5"}, "6 to 20"),
                       ({"bc_text_spacing": "abc"}, "number"),
                       ({"bc_text_gap": "-1"}, "0 to 5"),
                       ({"bc_text_bold": "maybe"}, "on or off"),
                       ({"bc_text_font": "x;}body{display:none"}, "font"),
                       ({"bc_text_font": "consolas", "bc_text_size": "99"}, "6 to 20"),
                       ({"bc_bar_width": "0.45"}, "0.15 to 0.4 mm"),
                       ({"bc_bar_height": "30"}, "6 to 20 mm"),
                       ({"bc_bar_quiet": "4"}, "10 to 25 modules"),
                       ({"bc_bar_quiet": "12.5"}, "whole number"),
                       # a good bar value does not rescue a bad text value, nor the reverse
                       ({"bc_bar_width": "0.3", "bc_text_size": "99"}, "6 to 20"),
                       ({"bc_text_size": "12", "bc_bar_height": "2"}, "6 to 20 mm")):
        r = c.post("/api/settings", json=body)
        assert r.status_code == 400, (body, r.status_code)
        assert word in r.get_json()["why"], (body, r.get_json())
        assert stored() == bc.SETTING_DEFAULTS, ("a refused save stored something", body, stored())


@test("an Admin cannot change it - the server refuses and nothing is stored")
def t_admin_refused():
    packed_box()
    c = client(role="Admin", login_id="admin1")
    r = c.post("/api/settings", json={"bc_text_size": "14"})
    assert r.status_code == 403, r.status_code
    assert stored() == bc.SETTING_DEFAULTS, stored()


@test("the sheet's barcodes are bars only, sized in mm - the text is beside the SVG, "
      "and the bars-off fallback still carries every serial")
def t_sheet_markup():
    c, box = packed_box()
    html = c.get("/box/%d/sheet" % box).get_data(as_text=True)
    assert 'width="53.086mm"' in html and 'width="58.674mm"' in html, \
        "a Jan-Sep and an Oct-Dec serial should print 189 and 211 modules wide"
    svgs = html.split("<svg")[1:]
    assert not any("<text" in s.split("</svg>")[0] for s in svgs if 'mm"' in s), \
        "text is still drawn inside a barcode SVG, where it shrinks with the bars"
    for s in SERIALS:
        assert html.count(s) >= 2, s       # under the bars, and the .txt fallback


@test("the bars are Settings too: a save is stored, normalised, and the packing list "
      "prints its barcodes at that module width, height and quiet zone")
def t_bar_settings_saved_and_printed():
    c, box = packed_box()
    d = bc.BAR_DEFAULTS
    assert (stored()["bc_bar_width"], stored()["bc_bar_height"], stored()["bc_bar_quiet"]) == \
        (d["bc_bar_width"], d["bc_bar_height"], d["bc_bar_quiet"])
    r = c.post("/api/settings", json={"bc_bar_width": "0.3000", "bc_bar_height": "14.50",
                                      "bc_bar_quiet": "12"})
    assert r.status_code == 200, r.get_json()
    s = stored()
    assert (s["bc_bar_width"], s["bc_bar_height"], s["bc_bar_quiet"]) == ("0.3", "14.5", "12"), s
    assert s["bc_text_size"] == bc.TEXT_DEFAULTS["bc_text_size"], "a bars-only save moved the text"
    html = c.get("/box/%d/sheet" % box).get_data(as_text=True)
    # Jan-Sep serial = 189 modules, Oct-Dec = 211, plus 12 of quiet zone each side
    assert 'width="%.3fmm"' % ((189 + 24) * 0.3) in html, "module width / quiet zone not used"
    assert 'width="%.3fmm"' % ((211 + 24) * 0.3) in html
    assert html.count('height="14.500mm"') == len(SERIALS), "bar height not used"
    assert 'data-quiet="12"' in html
    # the text under the bars is unchanged by it
    assert "font-size:10pt" in html


@test("bars that cannot fit the packing list's barcode cell are refused with the "
      "width - judged on the stored values with this save laid over them, and a "
      "refused save stores nothing")
def t_bar_settings_overflow_refused():
    c, _ = packed_box()
    cell = APP.PACKING_LIST_BARCODE_CELL_MM
    widest = bc.code128_modules(APP.BC_SAMPLE_SERIAL)            # 211 modules
    # the largest width that fits with the default quiet zone, and the next step up
    fits = round(cell / (widest + 20) - 0.0005, 3)
    r = c.post("/api/settings", json={"bc_bar_width": str(fits)})
    assert r.status_code == 200, (fits, r.get_json())
    before = stored()
    over = round(cell / (widest + 20) + 0.01, 3)
    r = c.post("/api/settings", json={"bc_bar_width": str(over)})
    assert r.status_code == 400, (over, r.status_code)
    why = r.get_json()["why"]
    assert "%.1f mm" % ((widest + 20) * over) in why and "%d mm" % cell in why, why
    assert stored() == before, "a refused save stored something"
    # the quiet zone alone: fine at the default width, too wide beside the stored one
    r = c.post("/api/settings", json={"bc_bar_quiet": "25"})
    assert r.status_code == 400, "the quiet zone was not judged against the stored width"
    assert stored() == before
    # text settings in the same post are not held up by the bars being fine
    r = c.post("/api/settings", json={"bc_bar_width": "0.254", "bc_bar_quiet": "25",
                                      "bc_text_size": "12"})
    assert r.status_code == 200, r.get_json()
    assert stored()["bc_text_size"] == "12" and stored()["bc_bar_quiet"] == "25"


@test("the Settings screen shows the stored values and a preview of the widest serial")
def t_settings_fragment():
    c, _ = packed_box()
    c.post("/api/settings", json={"bc_text_font": "verdana", "bc_text_size": "11",
                                  "bc_bar_width": "0.3", "bc_bar_height": "13",
                                  "bc_bar_quiet": "14"})
    html = c.get("/view/settings").get_data(as_text=True)
    assert '<option value="verdana" data-css="Verdana, Arial, sans-serif" selected>' in html
    assert 'id="bt_size" type="number" min="6" max="20" step="0.5" value="11"' in html
    assert APP.BC_SAMPLE_SERIAL in html and "width:%dmm" % APP.PACKING_LIST_BARCODE_CELL_MM in html
    for want in ('id="bt_barw" type="number" min="0.15" max="0.4" step="0.001" value="0.3"',
                 'id="bt_barh" type="number" min="6" max="20" step="0.5" value="13"',
                 'id="bt_quiet" type="number" min="10" max="25" step="1" value="14"'):
        assert want in html, want
    # the preview's barcode is drawn with the stored bars: (211 + 28) modules at 0.3 mm
    assert 'width="%.3fmm" height="13.000mm"' % ((211 + 28) * 0.3) in html
    assert '"bc_bar_width": "0.254"' in html, "the defaults for Reset are not in the page"


@test("the standalone /settings page carries the same card - two routes render one "
      "fragment, so both must supply its context (a refused Admin form post too)")
def t_settings_page_same_card():
    c, _ = packed_box()
    html = c.get("/settings").get_data(as_text=True)
    assert 'id="bcTextCard"' in html and 'id="bt_font"' in html
    a = client(role="Admin", login_id="admin1")
    r = a.get("/settings")
    assert r.status_code == 200 and 'id="bcTextCard"' in r.get_data(as_text=True)
    r = a.post("/settings", data={"ss_csv_path": "x"})
    assert r.status_code == 403, r.status_code
    assert 'id="bcTextCard"' in r.get_data(as_text=True)
    assert stored() == bc.SETTING_DEFAULTS, stored()


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
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
