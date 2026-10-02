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

import icon_bom_match as BM
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


# The materials a traceability file names, by header -> the BOM item key that
# bom_materials() understands. The file and the form name some differently:
# "String Alignment Tape" is the form's Cell Alignment Tape, "Channel & JB
# sealant" its Sealant, "EPE/POE" its Encapsulant, and the cell / string
# ribbons are two separate columns.
def _bom_key(h):
    """Which BOM item a (lower-case) header names, or None."""
    if "alignment" in h and "tape" in h:
        return "align_tape"
    if "lead" in h and "bending" in h:
        return "lead_tape"
    if "edge" in h and "seal" in h:
        return "edge_tape"
    if "string" in h and ("inter" in h or "connector" in h):
        return "string_ic"
    if ("cell" in h and ("inter" in h or "connector" in h)) or "ribbon" in h:
        return "cell_ic"
    if "cell" in h and "make" in h:
        return "cell"
    if "glass" in h and "front" in h:
        return "glass_front"
    if "glass" in h and ("back" in h or "rear" in h):
        return "glass_back"
    if "frame" in h:
        return "frame"
    if "epe" in h or "poe" in h or "encapsulant" in h:
        return "epe"
    if h.startswith("flux"):
        return "flux"
    if "junction" in h:
        return "jb"
    if "sealant" in h:
        return "sealant"
    if "potting" in h:
        return "potting"
    if "rfid" in h:
        return "rfid"
    return None


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

            # A batch / invoice column is never matched by its own header: it is
            # read by POSITION, as the column immediately right of its material
            # (both ribbons head theirs "Ribbon Invoice/Batch no").
            if "invoice" in h or "batch" in h:
                continue
            if "cell type" in h:
                put("cell_type")
            elif "bus bar" in h or "busbar" in h:
                put("bus_bar")
            elif "size" in h:
                put("sizes")
            elif "incharge" in h or "in-charge" in h or "in charge" in h:
                put("incharge")
            elif _bom_key(h):
                key = "mat:" + _bom_key(h)
                if key not in cm:
                    cm[key] = c
                    nxt = _txt(row[c + 1]).lower() if c + 1 < len(row) else ""
                    if "invoice" in nxt or "batch" in nxt:
                        cm[key + ":batch"] = c + 1
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

def _extract_bom(r, cell):
    """One row's raw BOM: the descriptive columns and, per material the file
    names, its make text and the batch text from the column beside it. Nothing
    is interpreted here - bom_materials() matches it against the master."""
    items = {}
    for key in ("cell", "glass_front", "glass_back", "cell_ic", "string_ic",
                "flux", "epe", "align_tape", "lead_tape", "edge_tape", "jb",
                "sealant", "potting", "frame", "rfid"):
        make = _txt(cell(r, "mat:" + key)) or None
        batch = _txt(cell(r, "mat:" + key + ":batch")) or None
        if make or batch:
            items[key] = {"make": make, "batch": batch}
    return {"cell_type": _txt(cell(r, "cell_type")) or None,
            "bus_bar": _txt(cell(r, "bus_bar")) or None,
            "sizes": _txt(cell(r, "sizes")) or None,
            "items": items}


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
                             "cell_type", "bus_bar", "sizes", "incharge")
                 if k in cm] + [k for k in cm if k.startswith("mat:")]
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
            "incharge_raw": _txt(cell(r, "incharge")) or None,
            "bom": _extract_bom(r, cell),
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
# Matched against the LIVE material master (db.materials): each material by its
# name and the module's family (G12R / G2X), each make to the master's own
# spelling, every size compared with the master's. A material the file does
# not mention and that has a single possible make is recorded with it (the
# "single make selects by default" rule) - the file is silent, the master is not
# ambiguous.

_D = "\u2014"
# bom item key -> the master materials it fills, in order
_TARGETS = {
    "cell": ["Solar Cell"],
    "glass_front": ["Solar Glass " + _D + " Front"],
    "glass_back": ["Solar Glass " + _D + " Rear"],
    "frame": ["Aluminium Frame"],
    "epe": ["Encapsulant"],
    "cell_ic": ["Cell Inter Connector"],
    "string_ic": ["String Inter Connector " + _D + " Centre",
                  "String Inter Connector " + _D + " Edge"],
    "flux": ["Flux"],
    "align_tape": ["Cell Alignment Tape"],
    "lead_tape": ["Lead Bending Tape"],
    "edge_tape": ["Edge Sealing Tape"],
    "jb": ["Junction Box 30 A"],
    "sealant": ["Sealant (Frame + JB)"],
    "potting": ["Potting Material " + _D + " Part A",
                "Potting Material " + _D + " Part B"],
    "rfid": ["RFID Sticker"],
}
_AND = re.compile(r"\bAND\b", re.I)


def _note(kind, material, text, detail):
    return {"kind": kind, "material": material, "text": text, "detail": detail}


def _pick(members, text, holes=None):
    """One master material out of several that are alternatives (Junction Box
    0.4 / 0.3 mtr, Lead Bending Tape 20 / 15 mm): the one whose size the file's
    text states. (member, matched?) - matched is None when the text states no
    size to go by. Variants that share their size and differ in the frame's
    mounting holes (790 / 1000, 1400, 1094) are told apart by the file's
    "Modules Sizes" column, `holes`."""
    if len(members) == 1:
        return members[0], None
    same = [m for m in members if BM.same_dims(text, m.get("size"))]
    live = [m for m in members if not m.get("legacy")] or members
    pool = same or live
    if len(pool) > 1 and holes and BM.holes(holes) and any(BM.holes(m.get("size")) for m in pool):
        for m in pool:
            if BM.holes(m.get("size")) == BM.holes(holes):
                return m, (True if same else False)
        return pool[0], False                  # the file's holes are not in the master
    if same:
        return same[0], True
    return live[0], (None if not BM.dims(text) else False)


def _default_make(m):
    """The make a material takes when nobody chose: its only make, or the
    default the master names (one of its makes)."""
    makes = m.get("makes") or []
    if len(makes) == 1:
        return makes[0]
    d = m.get("default_make")
    return d if d in makes else None


def bom_materials(bom, catalog, wattage=None, known_efficiencies=()):
    """One range's raw BOM -> {"rows": [{material_no, vendor, efficiency,
    batch}], "notes": [...], "new_efficiencies": [...]}.

    `catalog` is the live material master (db.materials). Makes are resolved to
    its spelling and several are joined with one separator; batches likewise;
    cell efficiencies are read out of the cell text. A material the file leaves
    empty is not written. Whatever the master does not agree with is a NOTE -
    an unmatched make, a size that differs, an efficiency not yet on the list -
    never silently dropped or changed."""
    fam = (bom.get("cell_type") or "").strip().upper()
    fam = "G2X" if fam.startswith("G2") else "G12R"
    items = bom.get("items") or {}
    rows, notes, used, filled_groups, new_eff = [], [], set(), set(), []
    known = set(known_efficiencies)

    def members(name):
        return [m for m in catalog
                if m["name"] == name and (m.get("series") or "") in ("", fam)]

    for key, names in _TARGETS.items():
        it = items.get(key)
        if not it:
            continue
        make_txt, batch_txt = it.get("make"), it.get("batch")
        texts = [make_txt] * len(names)
        if key == "string_ic" and make_txt and len(_AND.split(make_txt)) == 2:
            texts = [t.strip() for t in _AND.split(make_txt)]       # centre AND edge
        for name, text in zip(names, texts):
            mem = members(name)
            if not mem:
                notes.append(_note("missing", name, text,
                                   "%s is not in the material master" % name))
                continue
            m, matched = _pick(mem, text or "",
                               bom.get("sizes") if name == "Aluminium Frame" else None)
            # A size that is exactly another module type's (the G2X / M10R frame on a
            # G12R module) is physically impossible - the FILE is wrong, never the
            # master (Mukesh). Checked before any "no variant has this size" note.
            dims_off = BM.same_dims(text, m.get("size")) is False
            other = [x for x in catalog if x["name"] == name
                     and (x.get("series") or "") not in ("", fam)
                     and BM.same_dims(text, x.get("size"))] if dims_off else []
            if other:
                notes.append(_note("file_error", name, text,
                    "the file's size is the %s module's (%s); a %s module "
                    "cannot take it, so the FILE is wrong, not the master - "
                    "recorded as the %s one (%s), please correct the file"
                    % (other[0]["series"], other[0]["size"], fam, fam, m.get("size"))))
            elif matched is False:
                notes.append(_note("size", name, text,
                    "no %s in the master has the %s the file states%s; recorded "
                    "against %s (%s)" % (name,
                        "size" if dims_off else "mounting holes",
                        " (%s)" % bom.get("sizes") if not dims_off and bom.get("sizes") else "",
                        m.get("size"), m["n"])))
            elif dims_off:
                notes.append(_note("size", name, text,
                    "the size in the file differs from the master's (%s) - make "
                    "recorded, size not changed" % m.get("size")))
            vendor = None
            if text:
                got, left = BM.match_makes(text, m.get("makes") or [])
                vendor = BM.join(got + left) or None
                if left:
                    notes.append(_note("make", name, text,
                        "make not in the master: %s - kept as written; add it to "
                        "the master's makes, or correct the file" % ", ".join(left)))
            eff = None
            if key == "cell":
                vals = BM.efficiencies(text or "")
                eff = BM.join(vals) or None
                for v in vals:
                    if v not in known and v not in new_eff:
                        new_eff.append(v)
            batch = BM.clean_batch(batch_txt)
            if vendor or batch or eff:
                rows.append({"material_no": m["n"], "vendor": vendor,
                             "efficiency": eff, "batch": batch})
                used.add(m["n"])
                if m.get("group"):
                    filled_groups.add(m["group"])

    # the file is silent about these, and the master has only one answer
    in_file = {n for key in items for n in _TARGETS.get(key, [])}
    for m in catalog:
        series = m.get("series") or ""
        applies = (series in ("", fam)
                   or (series == "LABEL" and wattage is not None
                       and str(m.get("watt")) == str(wattage)))
        if (not applies or m["n"] in used or m.get("legacy") or m["name"] in in_file
                or (m.get("group") and m["group"] in filled_groups)
                or not _default_make(m)):
            continue
        make = _default_make(m)
        rows.append({"material_no": m["n"], "vendor": make,
                     "efficiency": None, "batch": None})
        notes.append(_note("default", m["name"], None,
                           "not in the file; the master's %s is %s"
                           % ("only make" if len(m["makes"]) == 1 else "default make", make)))
    rows.sort(key=lambda r: r["material_no"])
    return {"rows": rows, "notes": notes, "new_efficiencies": new_eff}
