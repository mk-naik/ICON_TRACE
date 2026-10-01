"""
ICON TRACE - monthly traceability workbook importer (the parsing half).

ICON's own monthly Excel ("TRACEABILITY SEP-2026") is the record of which
serial RANGES were produced, on which date and shift, for which customer,
with the bill of materials that went into them. It feeds Production Entry,
and - for months this system was not yet running - backfill.

THIS MODULE PARSES ONLY. It reads a workbook into validated, structured
ranges and never touches the database; app.py turns a chosen range into a
production entry (and, in backfill mode, the serial/allocation/indent rows
behind it, with the BOM as the allocation's final material set). Kept apart
so the parse is unit-testable against a built workbook with no server, and
so a bad file is DIAGNOSED, never half-imported.

Ported in spirit from a previous project's importer - the same idea of
finding the header by keyword, forward-filling merged cells, and validating
a range against its stated quantity - but the serial parsing is ICON_TRACE's
own icon_challan_import.decompose(), the model/wattage come from the serial
itself, and customers go through icon_customers.resolve(), not that
project's MySQL customer_mapping table.
"""

import datetime
import re

import icon_challan_import as chimport
import icon_customers as customers
import icon_serial as gen

# family char in the serial ('R') -> the model-name family ('G12R')
_FAM_NAME = {v: k for k, v in gen.FAMILY.items()}

SHIFTS = ("A", "B", "C")


# --------------------------------------------------------------------------
# header detection - by keyword, tolerant of column order and of a title
# block above the table (the real file has 11 summary rows before row 12's
# header). The row where serial + ending + quantity are all present is the
# header; everything below it is data.
# --------------------------------------------------------------------------

def _txt(v):
    return "" if v is None else str(v).strip()


def _find_header(rows):
    """(header_index, colmap) or (None, None). colmap maps canonical keys to
    absolute column indices. Core keys (date/shift/wattage/serial/ending/
    quantity/customer/remark) plus the BOM columns, matched most-specific
    first so 'Solar Glass (Front) Invoice/Batch no' does not also claim the
    bare 'Solar Glass (Front)' slot."""
    for i, row in enumerate(rows):
        cm = {}
        for c, cell in enumerate(row):
            h = _txt(cell).lower()
            if not h:
                continue

            def put(key):
                if key not in cm:
                    cm[key] = c

            # BOM - specific (invoice/batch) variants first
            is_batch = ("invoice" in h or "batch" in h)
            if "cell" in h and "invoice" in h:
                put("cell_batch")
            elif "cell make" in h or ("cell" in h and "make" in h):
                put("cell_make")
            elif "cell type" in h:
                put("cell_type")
            elif "bus bar" in h or "busbar" in h:
                put("bus_bar")
            elif "glass" in h and "front" in h and is_batch:
                put("glass_front_batch")
            elif "glass" in h and "front" in h:
                put("glass_front")
            elif "glass" in h and ("back" in h or "rear" in h) and is_batch:
                put("glass_back_batch")
            elif "glass" in h and ("back" in h or "rear" in h):
                put("glass_back")
            elif ("inter connector" in h or "interconnector" in h
                  or "ribbon" in h) and is_batch:
                put("ribbon_batch")
            elif "inter connector" in h or "interconnector" in h or "ribbon" in h:
                put("ribbon")
            elif "size" in h:
                put("sizes")
            # core columns
            elif "ending" in h:
                put("ending")
            elif "serial" in h:
                put("serial")
            elif "quantity" in h or h == "qty":
                put("quantity")
            elif "date" in h:
                put("date")
            elif "shift" in h:
                put("shift")
            elif "wattage" in h:
                put("wattage")
            elif "customer" in h:
                put("customer")
            elif "remark" in h:
                put("remark")

        if "serial" in cm and "ending" in cm and "quantity" in cm:
            return i, cm
    return None, None


# --------------------------------------------------------------------------
# per-field parsing
# --------------------------------------------------------------------------

def _parse_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = _txt(v)
    if not s or s.upper() in ("N/A", "NA"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y",
                "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
                "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_wattage(v):
    """'620W' / '620 W' / 620 -> 620, or None."""
    s = _txt(v).upper().replace("W", "").strip()
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _clean_remark(v):
    """The real file carries a boolean checkmark in Remark (True); that is
    not a remark, so booleans and empties become nothing."""
    if isinstance(v, bool) or v is None:
        return None
    s = _txt(v)
    return s or None


_PREFIX = re.compile(r"^\s*\([^)]*\)\s*")   # a leading "(SGS) " style tag

# The "Special Customer" column is not always a customer. These are internal
# production categories, all ICON Stock: "SR MODULE" is a String Rework module
# (tracked apart, packing warns before mixing it in - see serial.rework);
# "NORMAL" is ordinary stock production, no special customer at all.
_REWORK = {"SR MODULE", "SR MODULES", "STRING REWORK", "STRING REWORK MODULE"}
_STOCK_CATEGORY = {"NORMAL", "STOCK", "GENERAL STOCK", "ICON STOCK"}


def resolve_customer(raw):
    """(code, name, resolved, rework). Internal production categories resolve to
    ICON Stock - 'SR MODULE' as a String Rework module (rework True). Otherwise
    the name as written, then with a leading parenthetical tag stripped
    ('(SGS) AGRAWAL CHANNEL' -> 'AGRAWAL CHANNEL', an alias the master knows).
    Unresolved -> (None, raw, False, False); the caller imports it against ICON
    Stock and flags it."""
    raw = _txt(raw)
    if not raw:
        return None, "", False, False
    up = raw.upper()
    stock = customers.resolve("ICON Stock")
    if up in _REWORK:
        return stock["customer_code"], stock["name"], True, True
    if up in _STOCK_CATEGORY:
        return stock["customer_code"], stock["name"], True, False
    for cand in (raw, _PREFIX.sub("", raw).strip()):
        if not cand:
            continue
        c = customers.resolve(cand)
        if c:
            return c["customer_code"], c["name"], True, False
    return None, raw, False, False


def _model_of(d):
    """The model string a decomposed serial implies, e.g. 'ISEN625-G12R'."""
    fam = _FAM_NAME.get(d.get("family"))
    return "ISEN%d-%s" % (d["wattage"], fam) if fam else None


def _seq_len(d):
    return 4 if d.get("format_version") == 2 else 3


# --------------------------------------------------------------------------
# main parse
# --------------------------------------------------------------------------

def parse(source):
    """Parse a traceability workbook (a path, or a file-like/bytes) into
    validated ranges grouped by date and shift. Never raises on bad data - a
    row that cannot be trusted goes to `problems` with a reason, and the good
    rows still come back."""
    import openpyxl
    import io
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    ws = wb.worksheets[0]           # the traceability sheet is always first
    rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    # a month label from the title block, if present ("... month SEPTEMBER - 2026")
    month_label = None
    for r in rows[:11]:
        for cell in r:
            s = _txt(cell)
            m = re.search(r"month\s+(.+)$", s, re.I)
            if m:
                month_label = m.group(1).strip()
                break
        if month_label:
            break

    hdr, cm = _find_header(rows)
    if hdr is None:
        return {"ok": False, "why": "No traceability header found (a row with "
                "Serial No., Ending No and Quantity). Is this the monthly "
                "traceability report?", "ranges": [], "problems": [],
                "dates": [], "shifts_by_date": {}, "unresolved_customers": [],
                "sheet": ws.title, "month_label": month_label}

    data = rows[hdr + 1:]
    width = max((len(r) for r in data), default=0)

    # forward-fill the CONTEXT columns only (merged cells read as None in the
    # continuation rows); serial/ending/quantity are always per-row.
    fill_keys = [k for k in ("date", "shift", "wattage", "customer", "remark",
                             "cell_make", "cell_batch", "cell_type", "bus_bar",
                             "sizes", "glass_front", "glass_front_batch",
                             "glass_back", "glass_back_batch", "ribbon",
                             "ribbon_batch") if k in cm]
    carried = {}
    norm = []
    for r in data:
        r = list(r) + [None] * (width - len(r))
        for k in fill_keys:
            c = cm[k]
            if c < len(r) and r[c] not in (None, ""):
                carried[k] = r[c]
            elif k in carried:
                r[c] = carried[k]
        norm.append(r)

    def cell(r, key):
        c = cm.get(key)
        return r[c] if (c is not None and c < len(r)) else None

    ranges, problems = [], []
    unresolved = {}

    for n, r in enumerate(norm):
        excel_row = hdr + 2 + n           # 1-based row number in the sheet
        start_raw = _txt(cell(r, "serial"))
        if not start_raw:
            continue                      # blank / summary / spacer row
        end_raw = _txt(cell(r, "ending")) or start_raw
        qty_raw = cell(r, "quantity")

        def problem(why):
            problems.append({"row": excel_row, "serial": start_raw,
                             "ending": end_raw, "why": why})

        ds = chimport.decompose(start_raw.upper())
        de = chimport.decompose(end_raw.upper())
        if not ds.get("ok"):
            problem("start serial %s - %s" % (start_raw, ds.get("why")))
            continue
        if not de.get("ok"):
            problem("end serial %s - %s" % (end_raw, de.get("why")))
            continue
        if ds["wattage"] != de["wattage"] or ds["family"] != de["family"]:
            problem("start and end serials are different models/wattages")
            continue

        sl = _seq_len(ds)
        if len(start_raw) != len(end_raw) or start_raw[:-sl].upper() != end_raw[:-sl].upper():
            problem("start and end were not printed in the same batch")
            continue
        if ds["sequence"] > de["sequence"]:
            problem("start serial is greater than end serial")
            continue

        span = de["sequence"] - ds["sequence"] + 1
        try:
            qty = int(float(qty_raw)) if qty_raw not in (None, "") else span
        except (TypeError, ValueError):
            problem("quantity %r is not a number" % (qty_raw,))
            continue
        if qty != span:
            problem("quantity %d does not match the serial span %d "
                    "(%s to %s)" % (qty, span, start_raw, end_raw))
            continue

        the_date = _parse_date(cell(r, "date"))
        if the_date is None:
            problem("no readable date")
            continue
        shift = _txt(cell(r, "shift")).upper()[:1]
        if shift not in SHIFTS:
            problem("shift %r is not A, B or C" % (_txt(cell(r, "shift")),))
            continue

        watt_col = _parse_wattage(cell(r, "wattage"))
        if watt_col is not None and watt_col != ds["wattage"]:
            problem("the row says %dW but the serial is a %dW module - the "
                    "wattage in the serial is the nameplate"
                    % (watt_col, ds["wattage"]))
            continue

        code, name, resolved, rework = resolve_customer(cell(r, "customer"))
        if not resolved and _txt(cell(r, "customer")):
            unresolved[_txt(cell(r, "customer"))] = True

        ranges.append({
            "row": excel_row,
            "date": the_date.isoformat(),
            "shift": shift,
            "wattage": ds["wattage"],
            "model": _model_of(ds),
            "start": start_raw.upper(),
            "end": end_raw.upper(),
            "seq_from": ds["sequence"],
            "seq_to": de["sequence"],
            "qty": qty,
            "customer_raw": _txt(cell(r, "customer")),
            "customer_code": code,
            "customer_name": name,
            "customer_resolved": resolved,
            "rework": rework,
            "remark": _clean_remark(cell(r, "remark")),
            "bom": {
                "cell_make": _txt(cell(r, "cell_make")) or None,
                "cell_batch": _txt(cell(r, "cell_batch")) or None,
                "cell_type": _txt(cell(r, "cell_type")) or None,
                "bus_bar": _txt(cell(r, "bus_bar")) or None,
                "sizes": _txt(cell(r, "sizes")) or None,
                "glass_front": _txt(cell(r, "glass_front")) or None,
                "glass_front_batch": _txt(cell(r, "glass_front_batch")) or None,
                "glass_back": _txt(cell(r, "glass_back")) or None,
                "glass_back_batch": _txt(cell(r, "glass_back_batch")) or None,
                "ribbon": _txt(cell(r, "ribbon")) or None,
                "ribbon_batch": _txt(cell(r, "ribbon_batch")) or None,
            },
        })

    # date -> shifts present, both sorted; and a stable order for the ranges
    ranges.sort(key=lambda x: (x["date"],
                               SHIFTS.index(x["shift"]) if x["shift"] in SHIFTS else 9,
                               x["model"], x["seq_from"]))
    shifts_by_date = {}
    for x in ranges:
        shifts_by_date.setdefault(x["date"], set()).add(x["shift"])
    shifts_by_date = {d: sorted(s, key=lambda z: SHIFTS.index(z))
                      for d, s in shifts_by_date.items()}

    return {
        "ok": True,
        "sheet": ws.title,
        "month_label": month_label,
        "header_row": hdr + 1,
        "ranges": ranges,
        "problems": problems,
        "dates": sorted(shifts_by_date),
        "shifts_by_date": shifts_by_date,
        "unresolved_customers": sorted(unresolved),
        "summary": {
            "ranges": len(ranges),
            "modules": sum(x["qty"] for x in ranges),
            "problems": len(problems),
            "dates": len(shifts_by_date),
        },
    }


# --------------------------------------------------------------------------
# BOM -> allocation_material rows (the file's BOM as the final material set)
# --------------------------------------------------------------------------
#
# material_no comes in a G2X/G12R pair for the physical items; the traceability
# "Cell Type" (G12R / G2X) chooses which. Numbers are icon_materials' own:
#   cell 1(G2X)/5(G12R), glass front 2/6, glass rear 3/7, cell interconnector 12.
_MAT = {
    "G2X": {"cell": 1, "glass_front": 2, "glass_back": 3, "ribbon": 12},
    "G12R": {"cell": 5, "glass_front": 6, "glass_back": 7, "ribbon": 12},
}
_EFF = re.compile(r"(\d{2}(?:\.\d+)?)\s*%")


def bom_materials(bom):
    """Turn one range's parsed BOM into allocation_material rows:
    [{material_no, vendor, efficiency, batch}]. Cell efficiency is pulled out
    of the cell-make text ('LIONSOLAR 25.7% ...' -> '25.7%'). A material with
    nothing recorded for it is left out rather than written blank."""
    fam = (bom.get("cell_type") or "").strip().upper()
    fam = "G2X" if fam.startswith("G2") else "G12R"    # default to G12R
    nums = _MAT[fam]
    out = []

    def add(material_no, vendor, batch, efficiency=None):
        vendor = (vendor or "").strip() or None
        batch = (batch or "").strip() or None
        if vendor or batch or efficiency:
            out.append({"material_no": material_no, "vendor": vendor,
                        "efficiency": efficiency, "batch": batch})

    cell_make = bom.get("cell_make") or ""
    eff = _EFF.search(cell_make)
    add(nums["cell"], cell_make, bom.get("cell_batch"),
        eff.group(1) + "%" if eff else None)
    add(nums["glass_front"], bom.get("glass_front"), bom.get("glass_front_batch"))
    add(nums["glass_back"], bom.get("glass_back"), bom.get("glass_back_batch"))
    add(nums["ribbon"], bom.get("ribbon"), bom.get("ribbon_batch"))
    return out
