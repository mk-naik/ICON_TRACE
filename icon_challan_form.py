"""
ICON TRACE - what the printed Dispatch Challan Cum Gate Pass (Version 1) says.

The plant's own form is IS-MP-STR-FM-09. Its fixed text lives here, and so
does the tidying of party details that were filed under an older invoice
parser (a challan already issued keeps what it stored; the print cleans it,
the stored row is never rewritten).
"""

import datetime
import re

import icon_invoice_parser as P

# The form's own header block (Revision date and number as the plant printed
# them on its form - FM-09, revision 0, 01.03.2026).
DOC_NO = "IS-MP-STR-FM-09"
REV_DATE = "01.03.2026"
REV_NO = "0"

SUPPLIER = ("ICON SOLAR-EN POWER TECHNOLOGIES PVT.LTD",
            "Mandir Hasaud, Arang, Tekari, Raipur",
            "RAIPUR, CHHATTISGARH, PIN-492001")
# People the transporter or the consignee can call, as printed on the form.
SUPPLIER_CONTACTS = (("Mr. Rohan Tiwari", "7089000318"),
                     ("Mr. Prakash Kandpal", "7089000327"),
                     ("Mr. Yasin Anshari", "7880182400"))
OWN_GSTIN = P.OWN_GSTIN

_TRAIL_LABEL = re.compile(
    r"[\s,;-]*(?:contact(?:\s+(?:number|no\.?|person))?|mob(?:ile)?(?:\s*no\.?)?)"
    r"\s*[-:.]*\s*$", re.I)


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


def state_of(gstin):
    code = (gstin or "")[:2]
    if not code.isdigit():
        return None, None
    return P.STATE_CODES.get(code, code), code


def party(name, address, gstin, phone=None):
    st, code = state_of(gstin)
    return {"name": name or "", "address": clean_address(address),
            "phone": phone10(phone), "gstin": gstin or "",
            "state": st, "state_code": code}


def lr_number(raw):
    """The LR / GR number: Tally's cell carries a date ('dt. 3-Oct-26') with
    or without a number; only the number is the LR number."""
    return P.ref_number(raw) or ""
