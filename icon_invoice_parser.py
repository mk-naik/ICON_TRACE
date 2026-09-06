"""
ICON TRACE - Tax Invoice parser
================================
Reads an HO Tax Invoice PDF (Tally screen -> "Microsoft: Print To PDF") and
returns structured JSON for the Create Challan screen.

DESIGN RULES (agreed, do not change without a decision):

  1. Parse by LABEL TEXT, never by fixed x/y coordinates. Vijay's print
     settings decide the layout; label text does not move.
  2. FINGERPRINT FIRST. If the expected labels are absent, refuse the parse.
     A parser that silently returns wrong values is worse than one that stops.
  3. THREE FIELD CLASSES:
       copy    - transcription, no independent source in ICON TRACE.
       compare - quantity / model / customer. NEVER copied as truth. These
                 come from scanned boxes; the invoice value is only the
                 declared expectation, used for reconciliation.
       never   - rate, amount, tax. Not parsed at all. ICON TRACE stays out
                 of financial documents.
  4. A field that is not found is left BLANK and flagged. Never guessed,
     never filled from a plausible neighbour.
  5. QR decode is BEST EFFORT. The Print-to-PDF path degrades the QR to
     113x113 px; it may not decode. It is never a hard requirement.
  6. IRN is the primary invoice reference, not the invoice number.

Requires: pymupdf                (mandatory)
          pyzbar + Pillow        (optional - QR cross-check only)

Windows note: pyzbar needs libzbar-64.dll beside it. If it is missing the
script still runs and reports qr.available = false.

Usage:
    python icon_invoice_parser.py INVOICE.pdf
    python icon_invoice_parser.py INVOICE.pdf --json out.json
    python icon_invoice_parser.py INVOICE.pdf --expect-qty 290
"""

import sys, os, re, json, argparse, datetime

# Bump on every change to extraction behaviour. `--selftest` proves which
# build is actually running, so "it does not detect X" can be answered in
# one command instead of by guesswork.
__version__ = "2026.09.09"


try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        sys.exit("pymupdf is required:  pip install pymupdf")

# Unit-2's own GSTIN. The seller on every invoice we handle must be this.
OWN_GSTIN = "22AADCI5761L3ZE"

# GST state codes -> state, for deriving IGST vs CGST/SGST.
STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}

# Labels that must ALL be present or we refuse the parse.
FINGERPRINT = ["Invoice No.", "IRN", "Consignee", "Buyer", "HSN/SAC",
               "Description of Goods", "GSTIN/UIN"]

# Fields that are legitimately absent from most invoices. A blank here means
# "the document does not carry it", not "the parser failed". Flagging both
# the same amber teaches operators to ignore amber, which is how a real
# missing vehicle number gets waved through.
OPTIONAL_FIELDS = {
    "delivery_note", "dispatch_doc_no",        # Tally slots nobody at HO fills
    "buyer_contact_name", "buyer_contact_phone",
    "consignee_contact_name", "consignee_contact_phone",
    "transporter_id", "ewb_distance_km", "ewb_valid_upto",
    "payment_terms", "ho_reference", "po_date", "ack_no", "ack_date",
    "destination", "lr_no",                    # LR is blank on some challans
}

# GSTIN: 2-digit state + 10-char PAN + entity code + 'Z' + checksum.
#
# The entity code may be a LETTER once a taxpayer passes 9 registrations in a
# state, and the final checksum may be a DIGIT. An earlier pattern demanded a
# digit then two letters, which silently returned nothing for 27ABNFR6585K1Z9
# - a whole invoice arrived with no GSTIN, no state and no tax mode.
GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z][A-Z][0-9A-Z])\b")

# Indian mobile, written every which way on these invoices:
#     MOB NO- 8420115051                       number alone
#     Contact Person- 76971 62443 Horilal ji   label, number, then name
#     Mr Kumbhare 88886 39498                  name, then number
PHONE_RE = re.compile(r"\b([6-9]\d{4})[\s.-]?(\d{5})\b")
CONTACT_LABEL_RE = re.compile(
    r"\b(MOB(?:ILE)?\.?\s*(?:NO\.?)?|CONTACT\s*PERSON|CONTACT|PH(?:ONE)?\.?|TEL\.?)"
    r"\s*[-:.]?\s*", re.I)
PIN_RE = re.compile(r"\b\d{6}\b")
DATE_RE  = re.compile(r"\b(\d{1,2}-[A-Za-z]{3}-\d{2,4})\b")
IRN_RE   = re.compile(r"\b([0-9a-f]{64})\b")


# --------------------------------------------------------------------------
# page geometry
# --------------------------------------------------------------------------

class Page:
    """Words plus the table's own drawn rules, so we can bound a cell without
    hard-coding a single coordinate."""

    def __init__(self, page):
        self.page = page
        self.words = [
            {"t": w[4], "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3]}
            for w in page.get_text("words")
        ]
        self.words.sort(key=lambda w: (round(w["y0"], 1), w["x0"]))
        self.hlines = self._rules(horizontal=True)
        self.text = page.get_text()

    def _rules(self, horizontal=True):
        vals = set()
        for d in self.page.get_drawings():
            for it in d["items"]:
                if it[0] == "l":
                    a, b = it[1], it[2]
                    if horizontal and abs(a.y - b.y) < 0.8:
                        vals.add(round(a.y, 1))
                    elif not horizontal and abs(a.x - b.x) < 0.8:
                        vals.add(round(a.x, 1))
                elif it[0] == "re":
                    r = it[1]
                    if horizontal and r.height < 0.8:
                        vals.add(round(r.y0, 1))
                    elif not horizontal and r.width < 0.8:
                        vals.add(round(r.x0, 1))
        return sorted(vals)

    def find_label(self, label, occurrence=0):
        """Locate a label by matching its words in sequence. Returns the box
        around the whole label, or None."""
        parts = label.split()
        hits = []
        n = len(self.words)
        for i in range(n):
            if self.words[i]["t"] != parts[0]:
                continue
            j, k, row = i, 0, []
            while j < n and k < len(parts):
                w = self.words[j]
                if w["t"] != parts[k]:
                    break
                row.append(w)
                j += 1
                k += 1
            if k == len(parts):
                hits.append({
                    "x0": min(w["x0"] for w in row),
                    "y0": min(w["y0"] for w in row),
                    "x1": max(w["x1"] for w in row),
                    "y1": max(w["y1"] for w in row),
                    "idx": i, "end": j, "widx": set(range(i, j)),
                })
        if occurrence < len(hits):
            return hits[occurrence]
        return None

    def value_right(self, label, occurrence=0, wrap=False):
        """Tally also prints 'Label : value' on one line (IRN, Ack No.,
        Valid Upto). Read to the right of the label, not below it."""
        lab = self.find_label(label, occurrence)
        if not lab:
            return None, None
        row = [self.words[i] for i in range(len(self.words))
               if i not in lab["widx"]
               and abs(self.words[i]["y0"] - lab["y0"]) < 3.5
               and self.words[i]["x0"] > lab["x1"] - 1]
        row.sort(key=lambda w: w["x0"])
        parts = [w["t"] for w in row if w["t"] != ":"]
        if not parts:
            return None, lab

        val = " ".join(parts).strip(" :")
        if wrap:
            # a wrapped value continues on rows that start no further left
            # than the value did; a new label always starts at the margin
            vx = min(w["x0"] for w in row)
            ys = sorted({round(w["y0"], 1) for w in self.words
                         if w["y0"] > lab["y1"] - 1})
            for y in ys:
                line = [w for w in self.words if abs(w["y0"] - y) < 3.5]
                if not line or min(w["x0"] for w in line) < vx - 2:
                    break
                val += " " + " ".join(w["t"] for w in sorted(
                    line, key=lambda w: w["x0"]))
        return val.strip(), lab

    def next_rule_below(self, y, default=None):
        for h in self.hlines:
            if h > y + 1.0:
                return h
        return default

    def value_below(self, label, occurrence=0, right_pad=200, max_lines=6):
        """The value Tally prints under a label, bounded by the table's next
        horizontal rule and by the next label starting on the same row."""
        lab = self.find_label(label, occurrence)
        if not lab:
            return None, None
        bottom = self.next_rule_below(lab["y1"], lab["y1"] + 30)

        # A label further right on the same row closes this column. Compare
        # against the label's START, and skip the label's own words - matching
        # "Consignee" must not let its own "(Ship to)" clamp the column.
        right = lab["x0"] + right_pad
        for i, w in enumerate(self.words):
            if i in lab["widx"]:
                continue
            if abs(w["y0"] - lab["y0"]) < 2.0 and w["x0"] > lab["x0"] + 8:
                right = min(right, w["x0"] - 2)

        picked = [
            w for w in self.words
            if w["y0"] >= lab["y1"] - 1 and w["y1"] <= bottom + 1
            and w["x0"] >= lab["x0"] - 4 and w["x1"] <= right + 4
        ]
        if not picked:
            return None, lab

        lines, cur, cy = [], [], None
        for w in picked:
            if cy is None or abs(w["y0"] - cy) < 3.5:
                cur.append(w); cy = w["y0"] if cy is None else cy
            else:
                lines.append(cur); cur = [w]; cy = w["y0"]
        if cur:
            lines.append(cur)

        out = [" ".join(w["t"] for w in ln) for ln in lines[:max_lines]]
        val = " ".join(out).strip(" :")
        return (val or None), lab

    def block_between(self, start_label, stop_labels):
        """Multi-line block under a label, ending at the first stop label."""
        lab = self.find_label(start_label)
        if not lab:
            return None
        stop_y = None
        for s in stop_labels:
            o = self.find_label(s)
            if o and o["y0"] > lab["y1"]:
                stop_y = o["y0"] if stop_y is None else min(stop_y, o["y0"])
        if stop_y is None:
            stop_y = lab["y1"] + 90

        # The party block owns the whole left column. Do not clamp on
        # same-row words: the address lines are wider than the label.
        right = lab["x0"] + 275

        picked = [w for w in self.words
                  if lab["y1"] - 1 <= w["y0"] and w["y1"] <= stop_y - 1
                  and lab["x0"] - 4 <= w["x0"] and w["x1"] <= right + 4]
        if not picked:
            return None

        lines, cur, cy = [], [], None
        for w in picked:
            if cy is None or abs(w["y0"] - cy) < 3.5:
                cur.append(w); cy = w["y0"] if cy is None else cy
            else:
                lines.append(" ".join(x["t"] for x in cur)); cur = [w]; cy = w["y0"]
        if cur:
            lines.append(" ".join(x["t"] for x in cur))
        return [ln for ln in lines if ln.strip()]


# --------------------------------------------------------------------------
# QR - best effort only
# --------------------------------------------------------------------------

def decode_qrs(doc):
    out = {"available": False, "einvoice": None, "ewaybill": None, "note": ""}
    try:
        from pyzbar.pyzbar import decode as zdecode
        from PIL import Image
        import io, base64
    except Exception as e:
        # NOT just ImportError. On Windows pyzbar imports as a Python module
        # and then dies at module level loading libzbar-64.dll / libiconv.dll,
        # which raises FileNotFoundError (an OSError). Catching ImportError
        # alone lets that escape and take the whole request down.
        msg = str(e)
        if "libzbar" in msg or "libiconv" in msg or "DLL" in msg:
            out["note"] = (
                "pyzbar is installed but its native library will not load "
                "(%s). Install the Visual C++ Redistributable for Visual "
                "Studio 2013 (x64). QR cross-check skipped - parsing "
                "continues on the text layer." % e.__class__.__name__)
        else:
            out["note"] = ("QR decoding unavailable (%s: %s). Parsing "
                           "continues on the text layer."
                           % (e.__class__.__name__, msg[:120]))
        return out

    out["available"] = True
    payloads = []
    for pno in range(doc.page_count):
        for img in doc[pno].get_images(full=True):
            try:
                pix = doc.extract_image(img[0])
                im = Image.open(io.BytesIO(pix["image"])).convert("L")
            except Exception:
                continue
            # Print-to-PDF downsamples these badly. Upscale before decoding.
            for scale in (4, 6, 8, 10):
                big = im.resize((im.width * scale, im.height * scale),
                                Image.NEAREST)
                res = zdecode(big)
                if res:
                    payloads.append(res[0].data.decode("utf-8", "replace"))
                    break

    for p in payloads:
        if p.count(".") == 2 and len(p) > 300:
            try:
                import base64 as b64
                seg = p.split(".")[1]
                raw = b64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))
                obj = json.loads(raw)
                if isinstance(obj.get("data"), str):
                    obj = json.loads(obj["data"])
                out["einvoice"] = obj
            except Exception:
                pass
        elif "EWB" in p.upper():
            out["ewaybill"] = p.strip()

    if not payloads:
        out["note"] = ("No QR decoded. Expected on this layout - the "
                       "Print-to-PDF path degrades them. Not an error.")
    return out


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def norm_date(s):
    if not s:
        return None
    m = DATE_RE.search(s)
    if not m:
        return None
    raw = m.group(1)
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def first_gstin(lines):
    for ln in lines or []:
        m = GSTIN_RE.search(ln.replace(" ", ""))
        if m:
            return m.group(1)
        m = GSTIN_RE.search(ln)
        if m:
            return m.group(1)
    return None


def split_contact(lines):
    """Pull the contact person out of a party block.

    Returns (name, phone, remaining_lines). The phone is always extracted.
    The line is only removed from the address when what is left of it reads
    like a name - if the residue still looks like address content (a PIN
    code, or simply long) the line stays put and only the number is lifted
    out, so nothing is lost from the printed address.
    """
    for i, ln in enumerate(lines):
        m = PHONE_RE.search(ln)
        if not m:
            continue
        phone = "".join(c for c in m.group(0) if c.isdigit())
        residue = (ln[:m.start()] + " " + ln[m.end():])
        residue = CONTACT_LABEL_RE.sub(" ", residue)
        residue = " ".join(residue.split()).strip(" -:,.")

        looks_like_name = (
            residue == ""
            or (len(residue) <= 40 and not any(c.isdigit() for c in residue)
                and not PIN_RE.search(residue)))
        if looks_like_name:
            return (residue or None), phone, lines[:i] + lines[i + 1:]
        return None, phone, lines          # keep the line, take the number
    return None, None, lines


def clean_party(lines):
    """Name is the first line; address is everything before GSTIN/State."""
    if not lines:
        return None, []
    name, addr = None, []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^(GSTIN|State Name|E-Mail|IEC)", s, re.I):
            continue
        if name is None:
            name = s
        else:
            addr.append(s)
    return name, addr


# --------------------------------------------------------------------------
# main parse
# --------------------------------------------------------------------------

def parse(path, expect_qty=None):
    """Open, parse, and ALWAYS close.

    A PDF left open holds a Windows file handle, so the caller's cleanup
    `os.remove()` fails with WinError 32 and a clean refusal turns into an
    Internal Server Error. On Linux the delete succeeds and the bug stays
    invisible, which is exactly how it reached the plant.
    """
    doc = pymupdf.open(path)
    try:
        return _parse(doc, path, expect_qty)
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _parse(doc, path, expect_qty=None):
    meta = doc.metadata or {}
    r = {
        "source_file": os.path.basename(path),
        "parsed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "producer": meta.get("producer"),
        "pages": doc.page_count,
        "fingerprint": {"ok": False, "missing": []},
        "fields": {},
        "compare_only": {},
        "not_parsed": ["rate", "amount", "taxable_value", "tax_amount",
                       "total_invoice_value"],
        "qr": {},
        "checks": [],
        "blocked": False,
    }

    p0 = Page(doc[0])

    missing = [lab for lab in FINGERPRINT if lab not in p0.text]
    r["fingerprint"] = {"ok": not missing, "missing": missing}
    if missing:
        r["blocked"] = True
        r["checks"].append({
            "level": "block", "id": "fingerprint",
            "msg": "Not a recognised HO Tax Invoice - missing labels: "
                   + ", ".join(missing) + ". Refusing to parse rather than guess."})
        return r

    def put(key, label, cls="copy", occ=0, pad=200, post=None, lines=1):
        val, lab = p0.value_below(label, occurrence=occ, right_pad=pad,
                                  max_lines=lines)
        if val and post:
            val = post(val)
        target = r["fields"] if cls == "copy" else r["compare_only"]
        target[key] = {"value": val, "found": bool(val), "label": label,
                       "class": cls, "edited": False}

    def put_right(key, label, post=None, wrap=False):
        val, _ = p0.value_right(label, wrap=wrap)
        if val and post:
            val = post(val)
        r["fields"][key] = {"value": val, "found": bool(val), "label": label,
                            "class": "copy", "edited": False}

    # ---- identity -------------------------------------------------------
    # IRN wraps across two lines with a trailing hyphen.
    irn, _ = p0.value_right("IRN", wrap=True)
    if irn:
        irn = re.sub(r"[^0-9a-fA-F]", "", irn)
        irn = irn if len(irn) == 64 else None
    r["fields"]["irn"] = {"value": irn, "found": bool(irn), "label": "IRN",
                          "class": "copy", "edited": False}

    put_right("ack_no",   "Ack No.")
    put_right("ack_date", "Ack Date", post=norm_date)

    put("invoice_no",   "Invoice No.",        pad=100)
    put("ewb_no",       "e-Way Bill No.",     pad=100)
    put("invoice_date", "Dated", occ=0, pad=80, post=norm_date)

    # ---- commercial references -----------------------------------------
    put("ho_reference", "Reference No. & Date.", pad=180)
    put("po_no",        "Buyer's Order No.",     pad=160)
    put("po_date",      "Dated", occ=1, pad=80, post=norm_date)
    put("delivery_note",    "Delivery Note",   pad=120)
    put("dispatch_doc_no",  "Dispatch Doc No.", pad=120)

    # ---- transport ------------------------------------------------------
    put("transporter", "Dispatched through",       pad=120)
    put("lr_no",       "Bill of Lading/LR-RR No.", pad=120)
    put("vehicle_no",  "Motor Vehicle No.",        pad=130)
    put("destination", "Destination",              pad=130)
    put("payment_terms", "Mode/Terms of Payment",  pad=120, lines=2)

    # ---- parties --------------------------------------------------------
    cons = p0.block_between("Consignee (Ship to)", ["Buyer (Bill to)"])
    buyr = p0.block_between("Buyer (Bill to)", ["Description of Goods"])
    # the Buyer block runs to the goods table; stop it at its own State Name
    if buyr:
        cut = len(buyr)
        for i, ln in enumerate(buyr):
            if ln.strip().startswith("State Name"):
                cut = i + 1
                break
        buyr = buyr[:cut]

    cname, caddr = clean_party(cons)
    bname, baddr = clean_party(buyr)

    for key, nm, ad, blk in (("consignee", cname, caddr, cons),
                             ("buyer", bname, baddr, buyr)):
        contact_name, contact_phone, ad = split_contact(ad or [])
        r["fields"][key + "_name"] = {"value": nm, "found": bool(nm),
            "label": key, "class": "copy", "edited": False}
        r["fields"][key + "_address"] = {"value": " ".join(ad) or None,
            "found": bool(ad), "label": key, "class": "copy", "edited": False}
        g = first_gstin(blk)
        r["fields"][key + "_gstin"] = {"value": g, "found": bool(g),
            "label": key, "class": "copy", "edited": False}
        r["fields"][key + "_contact_name"] = {
            "value": contact_name, "found": bool(contact_name),
            "label": key + " contact", "class": "copy", "edited": False}
        r["fields"][key + "_contact_phone"] = {
            "value": contact_phone, "found": bool(contact_phone),
            "label": key + " contact", "class": "copy", "edited": False}

    # ---- goods line: COMPARE ONLY ---------------------------------------
    desc = re.search(r"SOLAR PV MODULE-([A-Z0-9\-]+)", p0.text)
    r["compare_only"]["model"] = {
        "value": desc.group(1) if desc else None, "found": bool(desc),
        "label": "Description of Goods", "class": "compare", "edited": False}

    qm = re.search(r"([\d,]+)\.\d{3}\s*pcs", p0.text)
    qty = int(qm.group(1).replace(",", "")) if qm else None
    r["compare_only"]["quantity"] = {"value": qty, "found": qty is not None,
        "label": "Quantity", "class": "compare", "edited": False}

    hm = re.search(r"\b(\d{8})\b", p0.text)
    r["compare_only"]["hsn"] = {"value": hm.group(1) if hm else None,
        "found": bool(hm), "label": "HSN/SAC", "class": "compare",
        "edited": False}

    # ---- page 2: e-Way Bill --------------------------------------------
    if doc.page_count > 1:
        # Page 2's text order is scrambled by the print driver - the date is
        # emitted before its own label. Read by position, never by regex.
        p1 = Page(doc[1])
        vu, _ = p1.value_right("Valid Upto")
        r["fields"]["ewb_valid_upto"] = {
            "value": norm_date(vu) if vu else None, "found": bool(norm_date(vu)),
            "label": "Valid Upto", "class": "copy", "edited": False}
        tid, _ = p1.value_right("Transporter ID")
        if tid:
            m = re.search(r"\b([0-9A-Z]{15})\b", tid)
            tid = m.group(1) if m else None
        r["fields"]["transporter_id"] = {
            "value": tid, "found": bool(tid),
            "label": "Transporter ID", "class": "copy", "edited": False}
        dist, _ = p1.value_right("Approx Distance:")
        if dist:
            m = re.search(r"(\d+)\s*KM", dist)
            dist = int(m.group(1)) if m else None
        r["fields"]["ewb_distance_km"] = {
            "value": dist, "found": dist is not None,
            "label": "Approx Distance", "class": "copy", "edited": False}

    # ---- derived --------------------------------------------------------
    bg = r["fields"]["buyer_gstin"]["value"]
    cg = r["fields"]["consignee_gstin"]["value"]
    code = bg[:2] if bg else None
    # Defined even when the GSTIN is missing, so the operator sees a flagged
    # blank field instead of the row silently disappearing from the screen.
    r["fields"]["buyer_state"] = {
        "value": STATE_CODES.get(code, code) if code else None,
        "found": bool(code), "label": "derived from GSTIN",
        "class": "copy", "edited": False}
    r["fields"]["tax_mode"] = {
        "value": ("IGST" if code != OWN_GSTIN[:2] else "CGST/SGST")
                 if code else None,
        "found": bool(code), "label": "derived from GSTIN state code",
        "class": "copy", "edited": False}

    same = bool(bg and cg and bg == cg
                and (r["fields"]["buyer_address"]["value"] or "").strip()
                 == (r["fields"]["consignee_address"]["value"] or "").strip())
    r["fields"]["consignee_same_as_buyer"] = {"value": same, "found": True,
        "label": "derived by comparison", "class": "copy", "edited": False}

    # ---- QR (best effort) ----------------------------------------------
    r["qr"] = decode_qrs(doc)
    # the document is closed by parse(), not here - see the note there

    # ---- checks ---------------------------------------------------------
    checks = r["checks"]
    qi = (r["qr"].get("einvoice") or {})

    if qi:
        seller = qi.get("SellerGstin")
        if seller and seller != OWN_GSTIN:
            r["blocked"] = True
            checks.append({"level": "block", "id": "seller",
                "msg": "Seller GSTIN %s is not Unit-2 (%s). Wrong invoice."
                       % (seller, OWN_GSTIN)})
        else:
            checks.append({"level": "ok", "id": "seller",
                           "msg": "Seller GSTIN matches Unit-2."})
        dn = qi.get("DocNo")
        if dn and r["fields"]["invoice_no"]["value"]:
            same_no = dn.strip() == r["fields"]["invoice_no"]["value"].strip()
            checks.append({"level": "ok" if same_no else "warn", "id": "qr_docno",
                "msg": ("QR invoice number agrees with the printed text."
                        if same_no else
                        "QR says %s but the text says %s - PDF may be altered."
                        % (dn, r["fields"]["invoice_no"]["value"]))})
        if qi.get("Irn") and r["fields"]["irn"]["value"]:
            if qi["Irn"] != r["fields"]["irn"]["value"]:
                checks.append({"level": "warn", "id": "qr_irn",
                    "msg": "QR IRN does not match the printed IRN."})
    else:
        checks.append({"level": "info", "id": "qr",
            "msg": r["qr"].get("note") or "QR not decoded - proceeding on text."})

    vu = r["fields"].get("ewb_valid_upto", {}).get("value")
    if vu:
        d = datetime.date.fromisoformat(vu)
        left = (d - datetime.date.today()).days
        if left < 0:
            r["blocked"] = True
            checks.append({"level": "block", "id": "ewb_expired",
                "msg": "e-Way Bill expired on %s. The vehicle must not move."
                       % vu})
        else:
            checks.append({"level": "ok" if left > 1 else "warn", "id": "ewb",
                "msg": "e-Way Bill valid until %s (%d day%s left)."
                       % (vu, left, "" if left == 1 else "s")})

    if expect_qty is not None:
        inv = r["compare_only"]["quantity"]["value"]
        if inv is None:
            r["blocked"] = True
            checks.append({"level": "block", "id": "qty",
                "msg": "Invoice quantity not found. Type it before continuing."})
        elif inv != expect_qty:
            r["blocked"] = True
            checks.append({"level": "block", "id": "qty",
                "msg": "Invoice declares %d, boxes scanned total %d - short by "
                       "%d. No override: fix the packing or have HO reissue."
                       % (inv, expect_qty, inv - expect_qty)})
        else:
            checks.append({"level": "ok", "id": "qty",
                "msg": "Invoice quantity %d matches the scanned box total." % inv})

    for group in ("fields", "compare_only"):
        for k, v in r[group].items():
            v["optional"] = k in OPTIONAL_FIELDS

    missing_required = [k for g in ("fields", "compare_only")
                        for k, v in r[g].items()
                        if not v["found"] and not v["optional"]]
    absent_optional = [k for g in ("fields", "compare_only")
                       for k, v in r[g].items()
                       if not v["found"] and v["optional"]]
    if missing_required:
        checks.append({"level": "warn", "id": "blank",
            "msg": "Expected but not found - type these in: "
                   + ", ".join(missing_required)})
    if absent_optional:
        checks.append({"level": "info", "id": "absent",
            "msg": "Not present on this invoice, which is normal: "
                   + ", ".join(absent_optional)})
    return r


# --------------------------------------------------------------------------


def selftest():
    """Prove this build extracts what it claims. No PDF needed."""
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  %-4s %-34s got %r" % ("PASS" if good else "FAIL", label, got))

    print("icon_invoice_parser %s" % __version__)
    print("\ncontact person / phone")
    n, p, rest = split_contact(["MIZORAM PIN CODE - 796009", "MOB NO- 8420115051"])
    check("number only", (n, p), (None, "8420115051"))
    n, p, rest = split_contact(["District -Rajnandgaon- 491444 Chhattisgarh",
                                "Contact Person- 76971 62443 Horilal ji"])
    check("label + number + name", (n, p), ("Horilal ji", "7697162443"))
    n, p, rest = split_contact(["Dist - Satara Maharashtra 415107",
                                "Mr Kumbhare 88886 39498"])
    check("name + number", (n, p), ("Mr Kumbhare", "8888639498"))
    n, p, rest = split_contact(["Village- Charbhata, District -Rajnandgaon- 491444"])
    check("PIN is not a phone", (n, p), (None, None))
    n, p, rest = split_contact(["Nagpur 440001 Mob 9876543210"])
    check("address line kept", (n, p, len(rest)), (None, "9876543210", 1))

    print("\nGSTIN")
    for g in ("22AADCI5761L3ZE", "27ABNFR6585K1Z9", "15AACCA2122Q1ZT",
              "22AAFCA7929N1ZC", "22AACCP9830A1ZV", "22AADCI5761L1ZG"):
        check(g, bool(GSTIN_RE.search(g)), True)

    print("\n%s" % ("ALL PASS - this build has the contact and GSTIN fixes."
                     if ok else
                     "FAILURES ABOVE - you are running an older copy of this file."))
    return ok


def report(r):
    W = "\033[0m"
    print("=" * 74)
    print("ICON TRACE  ·  invoice parse  ·  %s" % r["source_file"])
    print("=" * 74)
    print("producer : %s" % r["producer"])
    fp = r["fingerprint"]
    print("document : %s" % ("recognised" if fp["ok"]
          else "REFUSED - missing " + ", ".join(fp["missing"])))
    if not fp["ok"]:
        return
    print()
    print("-- COPY (transcribed onto the challan) " + "-" * 34)
    for k, v in r["fields"].items():
        mark = " " if v["found"] else "!"
        print(" %s %-24s %s" % (mark, k, v["value"] if v["found"]
                                else "(blank - flagged)"))
    print()
    print("-- COMPARE ONLY (never copied as truth) " + "-" * 33)
    for k, v in r["compare_only"].items():
        mark = " " if v["found"] else "!"
        print(" %s %-24s %s" % (mark, k, v["value"] if v["found"]
                                else "(blank - flagged)"))
    print()
    print("-- NOT PARSED " + "-" * 58)
    print("   " + ", ".join(r["not_parsed"]))
    print()
    q = r["qr"].get("einvoice")
    print("-- QR " + "-" * 66)
    if q:
        for k in ("SellerGstin", "BuyerGstin", "DocNo", "DocDt", "TotInvVal",
                  "ItemCnt", "MainHsnCode", "IrnDt"):
            if k in q:
                print("   %-14s %s" % (k, q[k]))
    else:
        print("   not decoded (best effort only)")
    if r["qr"].get("ewaybill"):
        print("   ewb            %s" % r["qr"]["ewaybill"])
    print()
    print("-- CHECKS " + "-" * 62)
    for c in r["checks"]:
        tag = {"ok": "  OK  ", "warn": " WARN ", "block": "BLOCK ",
               "info": " INFO "}[c["level"]]
        print(" [%s] %s" % (tag, c["msg"]))
    print()
    print("RESULT: %s" % ("BLOCKED - challan cannot be created"
                          if r["blocked"] else "clear to continue"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Parse an HO Tax Invoice PDF.")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--selftest", action="store_true",
                    help="prove which build is running - no PDF needed")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--json", help="write result to this file")
    ap.add_argument("--expect-qty", type=int,
                    help="scanned box total, to reconcile against the invoice")
    a = ap.parse_args()
    if a.version:
        print(__version__); sys.exit(0)
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if not a.pdf:
        ap.error("give a PDF, or --selftest")
    res = parse(a.pdf, expect_qty=a.expect_qty)
    report(res)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, ensure_ascii=False)
        print("\nJSON written to %s" % a.json)
    sys.exit(2 if res["blocked"] else 0)
