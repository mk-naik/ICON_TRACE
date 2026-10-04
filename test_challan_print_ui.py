"""
ICON TRACE - the printed challan, in a real browser.

    python test_challan_print_ui.py        (needs Playwright + Chromium)

What a person sees is only decided once the page is running: whether the fonts
the redesign ships actually load from the server, whether the logo and the QR
draw, whether the screen-only toolbar stays off the paper, and - the thing the
plant cares about most - whether a real truck's challan prints on ONE A4 page.
So this opens the real route on the real Flask app in headless Chromium and
prints it to PDF the way Chrome does.

  1. BOTH FORMATS FIT ONE PAGE for a 1-pallet dispatch and for a 20-pallet truck
     (the plant's commonest load), with the QR decoding to the challan's number.
  2. THE REDESIGN'S FONTS ARE LOADED FROM /static/fonts - a missing file would
     silently print in a fallback face.
  3. THE TOOLBAR (Print button, link to the other format) shows on screen and
     is gone on paper; the link works in both directions.
"""

import io
import re
import shutil
import sys
import traceback

import test_challan as T            # first: it fixes the throwaway database
import ui_harness as H              # noqa: E402  (same store and app)
import store                        # noqa: E402

APP = H.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def make_loaded_challan(c, n_pallets, invoice_no):
    """An issued challan of n_pallets pallets, every one loaded."""
    boxes = [T.packed_box(c, [2 * i, 2 * i + 1], customer=None) for i in range(n_pallets)]
    inv = T.make_invoice(qty=2 * n_pallets, invoice_no=invoice_no)
    with store.conn() as (cx, cur):
        cur.execute("UPDATE invoice SET consignee_name='MADHUR IRON & STEEL (INDIA) LIMITED', "
                    "consignee_address='Delivery Address- C/o SRV Mega Solar Power Plant Village "
                    "-Mohabhatta, Kodwa , Tehsil -Berla District -Bemetara (CG) Pincode-491993 "
                    "CONTACT NO: Dhaleshwar (93990 63401)', consignee_gstin='22AAHCM7572R1ZR', "
                    "buyer_address='Ankleshwar Rajpipla Road, Village- Govali, Bharuch- 393001, "
                    "Gujarat', invoice_date='2026-10-02' WHERE invoice_id=%s", (inv,))
    r = c.post("/api/challan", json={
        "action": "create", "boxes": boxes, "invoice_id": inv, "vehicle_no": "MH40BL2144",
        "transporter": "Shree Maruti Integrated Logistics Limited", "lr_no": "1391794",
        "driver_mobile": "98931 18777"}).get_json()
    assert r["ok"], r
    with store.conn() as (cx, cur):
        cur.execute("UPDATE challan_box SET loading_status='loaded'")
    return "/challan/%d/%d/print" % (r["fy"], r["seq"]), r["no"]


def pdf_pages_and_qr(pg, expect_no):
    """Print the open page to PDF as Chrome does; (page count, QR payloads read)."""
    import pymupdf
    from PIL import Image
    from pyzbar.pyzbar import decode
    pg.emulate_media(media="print")
    raw = pg.pdf(format="A4", prefer_css_page_size=True, print_background=True)
    doc = pymupdf.open(stream=raw, filetype="pdf")
    pages = doc.page_count
    pix = doc[0].get_pixmap(dpi=220)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    got = [d.data.decode("utf-8", "replace") for d in decode(img)]
    doc.close()
    return pages, got


def open_print(b, path, style):
    pg = H.open_page(b)
    pg.console_errors = []
    pg.on("console", lambda m: pg.console_errors.append(m.text) if m.type == "error" else None)
    pg.goto(H.base_url() + path + "?style=" + style)
    pg.wait_for_load_state("networkidle")
    pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(300)
    return pg


@test("both formats print a 1-pallet dispatch and a 20-pallet truck on ONE page, "
      "the QR reading the challan's own number")
def t_one_page_and_qr():
    c = T.setup()
    small, small_no = make_loaded_challan(c, 1, "ICON/26-27/911")
    truck, truck_no = make_loaded_challan(c, 20, "ICON/26-27/1003")
    with H.browser() as b:
        for style in ("premium", "classic"):
            for path, no, label in ((small, small_no, "1 pallet"), (truck, truck_no, "20 pallets")):
                pg = open_print(b, path, style)
                pages, got = pdf_pages_and_qr(pg, no)
                assert pages == 1, "%s / %s printed on %d pages" % (style, label, pages)
                assert ("ICONTRACE|CHALLAN|" + no) in got, \
                    "%s / %s: the QR read %r, not the challan's number" % (style, label, got)
                assert not pg.console_errors, (style, label, pg.console_errors)
                pg.close()


@test("the redesign's bundled fonts and the logo actually load from the server")
def t_fonts_and_logo_load():
    c = T.setup()
    path, no = make_loaded_challan(c, 3, "ICON/26-27/911")
    with H.browser() as b:
        pg = open_print(b, path, "premium")
        faces = pg.evaluate("Array.from(document.fonts).map(f => f.family + ' ' + f.status)")
        assert faces, "the redesign declares no font at all"
        assert all(f.endswith(" loaded") for f in faces), \
            "a font file did not load (it would print in a fallback face): %s" % faces
        imgs = pg.evaluate("Array.from(document.images).map(i => (i.getAttribute('src')||'') "
                           "+ ' ' + (i.complete && i.naturalWidth > 0 ? 'ok' : 'BROKEN'))")
        assert imgs and all(i.endswith(" ok") for i in imgs), imgs
        assert any("enicon-logo.svg" in i for i in imgs), imgs
        # at most two families, as designed
        fams = {f.rsplit(" ", 1)[0].split(" 100")[0] for f in faces}
        assert len(fams) <= 3, "more typefaces than the design allows: %s" % faces
        pg.close()


@test("the toolbar shows on screen, stays off the paper, and its link switches format both ways")
def t_toolbar_and_switch():
    c = T.setup()
    path, no = make_loaded_challan(c, 2, "ICON/26-27/911")
    with H.browser() as b:
        pg = open_print(b, path, "premium")
        assert pg.evaluate("getComputedStyle(document.querySelector('.noprint')).display") != "none", \
            "the toolbar is not shown on screen"
        assert pg.query_selector(".noprint button") is not None, "no Print button on screen"
        pg.emulate_media(media="print")
        assert pg.evaluate("getComputedStyle(document.querySelector('.noprint')).display") == "none", \
            "the toolbar would print on the paper"
        pg.emulate_media(media="screen")
        pg.click('.noprint a[href*="style=classic"]')
        pg.wait_for_load_state("networkidle")
        assert "style=classic" in pg.url, pg.url
        assert pg.query_selector('.noprint a[href*="style=premium"]') is not None, \
            "no way back from the original format"
        pg.click('.noprint a[href*="style=premium"]')
        pg.wait_for_load_state("networkidle")
        assert "style=premium" in pg.url and pg.query_selector('.noprint a[href*="style=classic"]'), pg.url
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
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(T.TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
