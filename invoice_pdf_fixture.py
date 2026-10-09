"""
ICON TRACE - a synthetic HO Tax Invoice PDF for tests (no real invoice is ever
opened). Laid out so icon_invoice_parser reads it by label, the way it reads
HO's Tally print: the right-hand reference grid with its rules, the
Consignee / Buyer blocks, the goods line, and the e-Way Bill on page 2.

    path = make_pdf(folder, "TINV/26-27/001", 36)
    irn_of("TINV/26-27/001")          # the IRN printed on it

Used by test_invoice_confirm.py and test_invoice_screen_ui.py.
"""

import datetime, hashlib, os

import icon_clock as clock

try:
    import pymupdf
except ImportError:                                          # pragma: no cover
    import fitz as pymupdf


def irn_of(seed):
    return hashlib.sha256(("TEST-IRN-" + seed).encode()).hexdigest()


def make_pdf(folder, invoice_no, qty, irn_seed=None, ewb_upto=None,
             qty_text=None, name=None):
    """A two-page invoice. ewb_upto is printed as given (default: ten days
    on, as 19-Oct-2026); qty_text replaces the goods line's quantity ("" for
    an invoice the parser finds no quantity on); name picks the file name."""
    if ewb_upto is None:
        ewb_upto = (clock.today() + datetime.timedelta(days=10)).strftime("%d-%b-%Y")
    path = os.path.join(folder, name or "%s.pdf" % hashlib.md5(
        (invoice_no + (irn_seed or "") + ewb_upto + str(qty_text)).encode()
    ).hexdigest()[:10])
    doc = pymupdf.open()
    p = doc.new_page(width=595, height=842)

    def t(x, y, s, fs=7):
        p.insert_text((x, y), s, fontsize=fs, fontname="helv")
    t(30, 46, "IRN : " + irn_of(irn_seed or invoice_no), 6.5)
    t(30, 58, "Ack No. : 132600001111")
    t(30, 70, "Ack Date : 8-Oct-26")
    y = 90
    p.draw_line((305, y - 2), (585, y - 2), width=0.5)
    for l1, v1, l2, v2 in (("Invoice No.", invoice_no, "Dated", "8-Oct-26"),
                           ("Dispatched through", "ALL INDIA TRANSPORT",
                            "Destination", "Aizawl"),
                           ("Bill of Lading/LR-RR No.", "2678",
                            "Motor Vehicle No.", "CG04MP1466"),
                           ("e-Way Bill No.", "331004512789", "", "")):
        t(310, y + 8, l1)
        t(310, y + 18, v1, 7.5)
        if l2:
            t(450, y + 8, l2)
            t(450, y + 18, v2, 7.5)
        y += 24
        p.draw_line((305, y - 2), (585, y - 2), width=0.5)
    for y0, label in ((160, "Consignee (Ship to)"), (250, "Buyer (Bill to)")):
        t(30, y0, label)
        t(30, y0 + 10, "AGNI GREEN POWER LIMITED (MZ)", 7.5)
        t(30, y0 + 19, "Sairang Road, Aizawl, Mizoram 796001")
        t(30, y0 + 28, "GSTIN/UIN : 15AACCA2122Q1ZT")
        t(30, y0 + 37, "State Name : Mizoram, Code : 15")
    t(30, 400, "Sl Description of Goods")
    t(330, 400, "HSN/SAC")
    p.draw_line((25, 404), (585, 404), width=0.5)
    t(30, 416, "1 SOLAR PV MODULE-ISEN630-G12R", 7.5)
    t(330, 416, "85414300", 7.5)
    t(400, 416, "{:,}.000 pcs".format(qty) if qty_text is None else qty_text, 7.5)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((30, 75), "Valid Upto : " + ewb_upto, fontsize=8,
                   fontname="helv")
    doc.save(path)
    doc.close()
    return path
