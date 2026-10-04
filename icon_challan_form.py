"""
ICON TRACE - what the printed Dispatch Challan Cum Gate Pass (Version 1) says.

The plant's own form is IS-MP-STR-FM-09. Its fixed text lives here, and so
does the tidying of party details that were filed under an older invoice
parser (a challan already issued keeps what it stored; the print cleans it,
the stored row is never rewritten).

`print_context()` is the one place that turns database rows into what a
Version 1 template shows. It is a pure function (no Flask, no database), so
every format - the plant's original layout ("classic") and the redesign
("premium") - reads the same facts, and the facts can be tested on their own.
"""

import datetime
import re
import sys
from decimal import Decimal

import icon_invoice_parser as P

# The form's own header block (Revision date and number as the plant printed
# them on its form - FM-09, revision 0, 01.03.2026).
DOC_NO = "IS-MP-STR-FM-09"
REV_DATE = "01.03.2026"
REV_NO = "0"

OWN_NAME = "ICON SOLAR-EN POWER TECHNOLOGIES PVT LTD"
OWN_NAME_FULL = "ICON SOLAR-EN POWER TECHNOLOGIES PRIVATE LIMITED"
OWN_UNIT = "UNIT-2"
OWN_ADDRESS = ("Khasra No 1553/1, 1564, 1566, 1568/1, 1568/2, P.H.N.-00005, "
               "Mandir Hasaud, Arang, Tekari, Raipur, Chhattisgarh 493225")
OWN_GSTIN = P.OWN_GSTIN
OWN_STATE = "Chhattisgarh"
OWN_STATE_CODE = "22"

SUPPLIER = ("ICON SOLAR-EN POWER TECHNOLOGIES PVT.LTD",
            "Mandir Hasaud, Arang, Tekari, Raipur",
            "RAIPUR, CHHATTISGARH, PIN-492001")
# People the transporter or the consignee can call, as printed on the form.
SUPPLIER_CONTACTS = (("Mr. Rohan Tiwari", "7089000318"),
                     ("Mr. Prakash Kandpal", "7089000327"),
                     ("Mr. Yasin Anshari", "7880182400"))

# The two formats a Version 1 challan can be printed in. "premium" is the
# redesign; "classic" keeps the plant's original layout exactly as it was
# first built, in case management prefers it. Default and switch: see
# app.challan_print and the Settings value `print_style`.
STYLES = ("premium", "classic")
DEFAULT_STYLE = "premium"

_TRAIL_LABEL = re.compile(
    r"[\s,;-]*(?:contact(?:\s+(?:number|no\.?|person))?|mob(?:ile)?(?:\s*no\.?)?)"
    r"\s*[-:.]*\s*$", re.I)


def pick_style(asked, configured=None):
    """The style to print: what was asked for on this request, else the
    configured default, else the built-in default. Anything unknown falls
    back - a mistyped ?style= must never produce a blank page."""
    for cand in (asked, configured):
        c = (cand or "").strip().lower()
        if c in STYLES:
            return c
    return DEFAULT_STYLE


def dmy(iso):
    """2026-10-03 -> 03.10.2026, the way the plant writes a date."""
    try:
        return datetime.date.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return str(iso) if iso else ""


def clean_address(addr):
    """Drop Tally's 'Delivery Address -' label in front, and a 'Contact
    number' label left dangling at the end once its number was lifted out."""
    if not addr:
        return ""
    s = P.ADDR_LABEL_RE.sub("", " ".join(str(addr).split()))
    return _TRAIL_LABEL.sub("", s).strip(" ,;-")


def phone10(raw):
    """The ten digits of an Indian mobile, however it was written; '' if none."""
    m = P.PHONE_RE.search(str(raw or ""))
    return (m.group(1) + m.group(2)) if m else ""


def phone_display(raw):
    """A mobile the way it is easiest to read aloud: 98765 43210. What does
    not look like a mobile (a landline, two numbers) is shown as typed, tidied -
    nothing a person entered is dropped from the page."""
    d = phone10(raw)
    if d:
        return "%s %s" % (d[:5], d[5:])
    return " ".join(str(raw or "").split())


def state_of(gstin):
    code = (gstin or "")[:2]
    if not code.isdigit():
        return None, None
    return P.STATE_CODES.get(code, code), code


def party(name, address, gstin, phone=None):
    st, code = state_of(gstin)
    addr = clean_address(address)
    # the contact number is often already written inside the address text
    # ("CONTACT NO: Dhaleshwar (93990 63401)"); printing it again as its own
    # line is noise, so it stays only when the address does not carry it
    digits = phone10(phone)
    if digits and digits in re.sub(r"\D", "", addr):
        digits, shown = "", ""
    else:
        shown = phone_display(phone) if digits else ""
    return {"name": " ".join((name or "").split()), "address": addr,
            "phone": digits, "phone_fmt": shown,
            "gstin": gstin or "", "state": st, "state_code": code}


def lr_number(raw):
    """The LR / GR number: Tally's cell carries a date ('dt. 3-Oct-26') with
    or without a number; only the number is the LR number."""
    return P.ref_number(raw) or ""


def _party_key(p):
    """Two parties are the same party when name, address and GSTIN agree once
    case, spacing and punctuation are set aside."""
    def n(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    return (n(p.get("name")), n(p.get("address")), n(p.get("gstin")))


def description_of(model, dcr=None):
    """SOLAR PV MODULE-ISEN625-G12R-DCR. HO writes the bare model when it
    means NDCR (icon_models), so only DCR carries a suffix."""
    m = (model or "").strip()
    if not m:
        return "SOLAR PV MODULE"            # a line is never printed without a name
    return "SOLAR PV MODULE-%s%s" % (
        m, "-DCR" if (dcr or "").strip().upper() == "DCR" else "")


def fmt_kw(kw):
    """kW to at most three decimals, trailing zeros dropped: 22.5, 450, 0.625."""
    q = Decimal(kw).quantize(Decimal("0.001"))
    s = format(q.normalize(), "f")
    return s if "." not in s else s.rstrip("0").rstrip(".")


def goods_lines(goods_rows, ch=None):
    """One line per model on the challan, from the modules actually on it.

    goods_rows: dicts with model, dcr, wattage, qty (one per model + DCR +
    wattage, counted from challan_serial). kW is derived, never typed:
    wattage x quantity / 1000 per line, summed for the total - exactly, not
    from an average wattage. A challan whose modules are not in the serial
    master (an old import) falls back to the figures on the challan itself.
    """
    lines = []
    # modules that are not in the serial master (some historical imports) have
    # no model of their own; a challan of ONE model still knows it
    own = (ch or {}).get("model") or ""
    single = own if own and " + " not in own else ""
    for r in goods_rows or []:
        if not r.get("qty"):
            continue
        w = int(r.get("wattage") or 0)
        q = int(r["qty"])
        model = r.get("model") or single
        lines.append({"model": model, "dcr": r.get("dcr") or "",
                      "description": description_of(model, r.get("dcr")),
                      "wattage": w, "qty": q,
                      "kw": fmt_kw(Decimal(w * q) / Decimal(1000)),
                      "_kw": Decimal(w * q) / Decimal(1000)})
    if not lines and ch and ch.get("qty"):
        w = int(ch.get("wattage") or 0)
        q = int(ch["qty"])
        lines.append({"model": ch.get("model") or "", "dcr": "",
                      "description": description_of(ch.get("model")),
                      "wattage": w, "qty": q,
                      "kw": fmt_kw(Decimal(w * q) / Decimal(1000)),
                      "_kw": Decimal(w * q) / Decimal(1000)})
    for i, ln in enumerate(lines, 1):
        ln["no"] = i
    return lines


def print_context(ch, boxes, goods_rows, inv, no, qr_svg, style="premium",
                  switch_url="?style=classic"):
    """Everything a Version 1 template needs, as one dict.

    ch         the challan row
    boxes      its challan_box rows, in loading order
    goods_rows counted from challan_serial joined to the serial master
    inv        the invoice row it was raised against ({} when there is none)
    no         the display number, IS-03.10.2026/0001
    qr_svg     the QR as inline SVG (identity only: ICONTRACE|CHALLAN|<no>)
    style      which format is being printed ("premium" or "classic")
    switch_url link target (a query string) of the OTHER format, for the
               toolbar that is shown on screen and never printed
    """
    inv = inv or {}
    ch = ch or {}
    buyer = party(ch.get("buyer_name") or inv.get("buyer_name"),
                  inv.get("buyer_address"),
                  ch.get("buyer_gstin") or inv.get("buyer_gstin"),
                  inv.get("buyer_contact_phone"))
    # The ship-to is the challan's own when it was typed there, else the
    # invoice's; "same as buyer" has no ship-to of its own to show.
    if (ch.get("consignee_name") or ch.get("consignee_address")
            or inv.get("consignee_name") or inv.get("consignee_address")):
        cons = party(ch.get("consignee_name") or inv.get("consignee_name")
                     or buyer["name"],
                     ch.get("consignee_address") or inv.get("consignee_address"),
                     inv.get("consignee_gstin") or buyer["gstin"],
                     inv.get("consignee_contact_phone"))
    else:
        cons = dict(buyer)

    goods = goods_lines(goods_rows, ch)
    qty = sum(g["qty"] for g in goods)
    kw = fmt_kw(sum((g["_kw"] for g in goods), Decimal(0)))
    # Only a pallet that has a number can be listed - an old import may carry
    # pallets whose number was never recorded, and a list of blank entries (or a
    # made-up "Pallet 3") would be worse than saying how many there are. They
    # still count: n_pallets is every pallet, n_unnumbered the ones left off the list.
    numbered = [b for b in (boxes or []) if str(b.get("box_no") or "").strip()]
    pallets = [{"no": str(b["box_no"]).strip(), "qty": b.get("qty") or 0} for b in numbered]
    n_pallets = len(boxes or [])
    return {
        "style": style, "switch_url": switch_url,
        "other_style": "classic" if style == "premium" else "premium",
        # --- the facts, flat -------------------------------------------
        "no": no,
        "challan_date": dmy(ch.get("challan_date")),
        "invoice_no": ch.get("invoice_no") or inv.get("invoice_no") or "",
        "invoice_date": dmy(inv.get("invoice_date")),
        "vehicle_no": ch.get("vehicle_no") or "",
        "transporter": " ".join((ch.get("transporter") or "").split()),
        "lr_copy": lr_number(ch.get("lr_no")),
        "driver_name": " ".join((ch.get("driver_name") or "").split()),
        "driver_mobile": phone_display(ch.get("driver_mobile")),
        "cons": cons, "buyer": buyer,
        "same_party": _party_key(cons) == _party_key(buyer),
        "goods": goods, "qty": qty, "kw": kw,
        "pallets": pallets, "n_pallets": n_pallets,
        "n_unnumbered": n_pallets - len(pallets),
        "qr": qr_svg,
        "logo_url": "/static/enicon-logo.svg",
        # --- the plant's own form text ---------------------------------
        "form": sys.modules[__name__],
        # --- what the first (classic) template was written against -----
        "ch": ch, "boxes": boxes or [],
    }
