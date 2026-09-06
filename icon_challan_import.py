"""
ICON TRACE - Dispatch Challan workbook importer
===============================================
Reads the real challan Excel files (IS-DD.MM.YYYY/SEQ, form IS-MP-STR-FM-09)
and produces structured rows ready for the database.

This is the historical importer. Dispatch cannot go live without it: the rule
"a dispatched serial's customer can never change" is blind for every serial
shipped before go-live until this data is loaded.

DESIGN RULES (agreed, do not change without a decision):

  1. Read by LABEL, never by cell address. The workbook is made by copying
     the previous file, so rows drift.
  2. Store the challan number as fy + seq INTEGERS plus an optional suffix.
     The zero-padding is a display setting, not part of the number. The
     financial year starts 1 April.
  3. `742` and `742 (A)` are two real distinct documents that both went to a
     customer. Never normalise the suffix away. Never put a unique constraint
     on seq alone.
  4. Decompose every serial ONCE, here, and store format_version,
     date_produced, shift and sequence as real columns. Nothing downstream
     ever parses the string again.
  5. Pick the parser PER SERIAL, not per file. June v1 stock ships alongside
     August v2 stock, so one challan can carry both.
  6. The box cell is four facts in one blob. Split it into four columns.
  7. Reconcile and report. Never silently repair.

Serial layout, confirmed against real challans:

    ICON  <watt:3>  R  <YY:2>  <month>  <DD:2>  <shift:1>  <seq>
                          |       |                          |
                    base 2014     |                    v1: 3 digits
                    12 = 2026     |                    v2: 4 digits
                                  |
                        v1: 2 digits (01-12)
                        v2: 1 hex char (1-9, A=Oct, B=Nov, C=Dec)

Both forms are 10 characters after the R, so length cannot tell them apart.
The 1 Aug 2026 cutover does.

Usage:
    python icon_challan_import.py CHALLAN.xlsx [MORE.xlsx ...]
    python icon_challan_import.py *.xlsx --json out.json
    python icon_challan_import.py *.xlsx --sql  rows.sql
"""

import sys, os, re, json, argparse, datetime

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl is required:  pip install openpyxl")

YEAR_BASE = 2014
V2_CUTOVER = datetime.date(2026, 8, 1)
HEX_MONTH = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
             "9": 9, "A": 10, "B": 11, "C": 12}

# The v2 month is a HEX character, so the body is not all digits from
# October (A), November (B) and December (C). A \\d{10} body silently
# rejected every one of them - and would have done so first on 1 Oct.
SERIAL_RE = re.compile(r"^ICON(\d{3})([A-Z])(\d{2}[0-9A-C]\d{7})$")
CHALLAN_RE = re.compile(
    r"^\s*IS\s*-\s*(\d{2})\.(\d{2})\.(\d{4})\s*/\s*(\d+)\s*(\(([A-Z])\))?\s*$")


# --------------------------------------------------------------------------
# serial decomposition
# --------------------------------------------------------------------------

def _mkdate(yy, mm, dd):
    try:
        return datetime.date(YEAR_BASE + yy, mm, dd)
    except ValueError:
        return None


def _out(s, watt, fam, yy, pick, note=None):
    out = {"serial": s, "ok": True, "wattage": watt, "family": fam,
           "year": YEAR_BASE + yy}
    out.update(pick)
    out["date_produced"] = pick["date_produced"].isoformat()
    if note:
        out["note"] = note
    return out


def decompose(serial, box_pack_date=None):
    """Return the stored columns for one serial, or a reason it failed.
    box_pack_date only breaks a genuine tie; it never overrides a clear read."""
    s = (serial or "").strip().upper()
    m = SERIAL_RE.match(s)
    if not m:
        return {"serial": s, "ok": False,
                "why": "does not match ICON<watt>R<10 digits>"}
    watt, fam, body = int(m.group(1)), m.group(2), m.group(3)

    yy = int(body[0:2])

    # Build both readings on STRUCTURE alone. The cutover is a tiebreaker
    # further down, never a filter.
    #
    # Unit-2 moved to v2 on 1 Aug 2026. Unit-1 did not - it still issues v1,
    # so a Unit-1 module made in August 2026 is a v1 serial dated after the
    # cutover. Treating the cutover as a filter rejected every one of them.

    # v1: YY MM DD S SSS
    # Only attempt this when the month field is actually two digits - a v2
    # serial from October onward carries A/B/C there.
    v1 = None
    d1 = _mkdate(yy, int(body[2:4]), int(body[4:6])) if body[2:6].isdigit() else None
    if d1:
        v1 = {"format_version": 1, "date_produced": d1,
              "shift": int(body[6]), "sequence": int(body[7:10])}

    # v2: YY M DD S SSSS
    v2 = None
    mo = HEX_MONTH.get(body[2])
    if mo:
        d2 = _mkdate(yy, mo, int(body[3:5]))
        if d2:
            v2 = {"format_version": 2, "date_produced": d2,
                  "shift": int(body[5]), "sequence": int(body[6:10])}

    if v1 and not v2:
        pick, note = v1, None
        if v1["date_produced"] >= V2_CUTOVER:
            note = ("v1 format dated on or after the cutover - expected for "
                    "Unit-1, which did not move to v2")
    elif v2 and not v1:
        pick, note = v2, None
    elif v1 and v2:
        # Both structurally valid. The cutover settles most of these: only
        # one reading can sit on the correct side of 1 Aug 2026.
        s1 = v1["date_produced"] < V2_CUTOVER
        s2 = v2["date_produced"] >= V2_CUTOVER
        if s1 and not s2:
            return _out(s, watt, fam, yy, v1, "cutover resolved an ambiguous read")
        if s2 and not s1:
            return _out(s, watt, fam, yy, v2, "cutover resolved an ambiguous read")
        # Both readings are internally valid. Only the box's pack date can
        # settle it, and a module is never packed before it is made.
        if box_pack_date:
            c1 = (box_pack_date - v1["date_produced"]).days
            c2 = (box_pack_date - v2["date_produced"]).days
            ok1, ok2 = 0 <= c1 <= 400, 0 <= c2 <= 400
            if ok1 and not ok2:
                pick, note = v1, "ambiguous - resolved by box pack date"
            elif ok2 and not ok1:
                pick, note = v2, "ambiguous - resolved by box pack date"
            else:
                return {"serial": s, "ok": False,
                        "why": "AMBIGUOUS: reads as v1 %s and v2 %s. "
                               "Pack date does not settle it - needs a human."
                               % (v1["date_produced"], v2["date_produced"])}
        else:
            return {"serial": s, "ok": False,
                    "why": "AMBIGUOUS: reads as v1 %s and v2 %s, no pack date."
                           % (v1["date_produced"], v2["date_produced"])}
    else:
        return {"serial": s, "ok": False,
                "why": "no valid date under either format"}

    return _out(s, watt, fam, yy, pick, note)


# --------------------------------------------------------------------------
# workbook reading
# --------------------------------------------------------------------------

def _txt(v):
    return "" if v is None else str(v).strip()


def label_value(rows, *labels):
    """Find a cell whose text starts with one of the labels, return the next
    non-empty cell on that row. Address-independent by design."""
    for row in rows:
        for i, c in enumerate(row):
            t = _txt(c).rstrip(" -:").upper()
            for lab in labels:
                if t.startswith(lab.upper()):
                    for j in range(i + 1, len(row)):
                        v = _txt(row[j])
                        if v:
                            return v
    return None


def parse_box_blob(blob):
    """`BOX-A005   27-08-2026 \\n BIN-2   (B-SHIFT)` -> four columns."""
    out = {"box_no": None, "pack_date": None, "bin": None, "shift": None,
           "raw": blob}
    if not blob:
        return out
    t = " ".join(str(blob).split())
    m = re.search(r"BOX\s*(?:NO)?\s*[-:]?\s*([A-Z]?\s?\d+)", t, re.I)
    if m:
        out["box_no"] = m.group(1).replace(" ", "").upper()
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t)
    if m:
        try:
            out["pack_date"] = datetime.date(
                int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    m = re.search(r"BIN\s*[-:]?\s*(\d+)", t, re.I)
    if m:
        out["bin"] = int(m.group(1))
    m = re.search(r"\(([ABC])\s*-?\s*SHIFT\)", t, re.I)
    if m:
        out["shift"] = m.group(1).upper()
    else:
        # the other house style writes a bare digit at the end
        m = re.search(r"BIN\s*[-:]?\s*\d+\s+(\d)\b", t, re.I)
        if m:
            out["shift"] = {"1": "A", "2": "B", "3": "C"}.get(m.group(1),
                                                              m.group(1))
    return out


def fin_year(d):
    """Indian financial year starting 1 April. Returns the opening year."""
    return d.year if d.month >= 4 else d.year - 1


def read_challan(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = [[c.value for c in r] for r in ws.iter_rows()]

    r = {"source_file": os.path.basename(path), "header": {}, "boxes": [],
         "serials": [], "issues": [], "ok": True}
    H = r["header"]

    raw_no = label_value(rows, "CHALLAN NO")
    H["challan_no_raw"] = raw_no
    m = CHALLAN_RE.match(raw_no or "")
    if m:
        d = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        H["challan_date"] = d.isoformat()
        H["fy"] = fin_year(d)
        H["fy_label"] = "%d-%02d" % (H["fy"], (H["fy"] + 1) % 100)
        H["seq"] = int(m.group(4))
        H["suffix"] = m.group(6)
        H["display"] = "IS-%s/%04d%s" % (d.strftime("%d.%m.%Y"), H["seq"],
                                         " (%s)" % H["suffix"] if H["suffix"]
                                         else "")
    else:
        r["ok"] = False
        r["issues"].append({"level": "block",
            "msg": "Challan number %r does not match IS-DD.MM.YYYY/SEQ."
                   % raw_no})

    H["invoice_no"] = label_value(rows, "INVOICE NO")
    H["invoice_date"] = label_value(rows, "INVOICE DATE")
    H["lr_no"] = label_value(rows, "LR COPY")
    H["vehicle_no"] = label_value(rows, "LR.NO")     # the form mislabels this
    H["driver_mobile"] = label_value(rows, "MOB")
    H["transporter"] = label_value(rows, "TRANSPORTER NAME")
    H["supplier_gstin"] = label_value(rows, "GSTIN:")
    H["buyer_gstin"] = label_value(rows, "GSTIN/UNIQUE")
    H["form"] = label_value(rows, "DOC NO")

    for row in rows:
        for c in row:
            t = _txt(c)
            if t.upper().startswith("CONSIGNEE"):
                H["consignee"] = " ".join(t.split("\n")[1:]).strip() or None
            elif t.upper().startswith("BUYER"):
                H["buyer"] = " ".join(t.split("\n")[1:]).strip() or None

    # goods line - the row under the DESCRIPTION / WATTAGE / Qty header
    for i, row in enumerate(rows):
        cells = [_txt(c).upper() for c in row]
        if "DESCRIPTION" in cells and "WATTAGE" in cells:
            hdr = {v: j for j, v in enumerate(cells) if v}
            for nxt in rows[i + 1:i + 4]:
                desc = _txt(nxt[hdr["DESCRIPTION"]]) if "DESCRIPTION" in hdr else ""
                if not desc:
                    continue
                H["description"] = desc
                mm = re.search(r"(ISEN\d{3}-[A-Z0-9]+(?:-[ND]?DCR)?)", desc)
                H["model"] = mm.group(1) if mm else None
                for k, key in (("WATTAGE", "wattage"), ("QTY.", "qty"),
                               ("KW", "kw")):
                    if k in hdr and nxt[hdr[k]] is not None:
                        try:
                            H[key] = float(nxt[hdr[k]])
                        except (TypeError, ValueError):
                            H[key] = None
                break
            break

    # serial table
    start = None
    for i, row in enumerate(rows):
        cells = [_txt(c).upper() for c in row]
        if "BARCODE" in cells:
            start = i + 1
            bcol = cells.index("BARCODE")
            dcol = cells.index("BOX NO") if "BOX NO" in cells else bcol + 1
            break
    if start is None:
        r["ok"] = False
        r["issues"].append({"level": "block", "msg": "No BARCODE column found."})
        return r

    cur = None
    for row in rows[start:]:
        code = _txt(row[bcol]) if bcol < len(row) else ""
        blob = _txt(row[dcol]) if dcol < len(row) else ""
        if blob:
            cur = parse_box_blob(blob)
            cur["serials"] = []
            r["boxes"].append(cur)
        if not code.upper().startswith("ICON"):
            continue
        pd = None
        if cur and cur.get("pack_date"):
            pd = datetime.date.fromisoformat(cur["pack_date"])
        d = decompose(code, box_pack_date=pd)
        d["box_no"] = cur["box_no"] if cur else None
        r["serials"].append(d)
        if cur:
            cur["serials"].append(d["serial"])

    reconcile(r)
    return r


def reconcile(r):
    H, S, B, I = r["header"], r["serials"], r["boxes"], r["issues"]
    n = len(S)

    qty = H.get("qty")
    if qty is not None and int(qty) != n:
        r["ok"] = False
        I.append({"level": "block",
            "msg": "Header says %d modules but %d serials are listed."
                   % (int(qty), n)})
    elif qty is not None:
        I.append({"level": "ok",
                  "msg": "Serial count %d matches the stated quantity." % n})

    if H.get("wattage") and H.get("kw") is not None and qty:
        derived = round(H["wattage"] * qty / 1000.0, 1)
        if abs(derived - H["kw"]) > 0.05:
            I.append({"level": "warn",
                "msg": "KW on the sheet is %s but wattage x qty derives %s."
                       % (H["kw"], derived)})
        else:
            I.append({"level": "ok", "msg": "KW %s agrees with qty x wattage."
                                            % H["kw"]})

    bad = [s for s in S if not s["ok"]]
    if bad:
        r["ok"] = False
        for s in bad[:10]:
            I.append({"level": "block",
                      "msg": "%s - %s" % (s["serial"], s["why"])})
        if len(bad) > 10:
            I.append({"level": "block",
                      "msg": "...and %d more unreadable serials." % (len(bad) - 10)})

    seen, dup = set(), []
    for s in S:
        if s["serial"] in seen:
            dup.append(s["serial"])
        seen.add(s["serial"])
    if dup:
        r["ok"] = False
        I.append({"level": "block",
            "msg": "Duplicate serials inside this challan: %s"
                   % ", ".join(sorted(set(dup))[:6])})

    good = [s for s in S if s["ok"]]
    if good:
        vs = sorted({s["format_version"] for s in good})
        I.append({"level": "info",
            "msg": "Serial formats present: %s"
                   % ", ".join("v%d (%d)" % (v, sum(
                       1 for s in good if s["format_version"] == v)) for v in vs)})
        wat = {s["wattage"] for s in good}
        if H.get("wattage") and wat != {int(H["wattage"])}:
            I.append({"level": "warn",
                "msg": "Header wattage %d but serials carry %s."
                       % (int(H["wattage"]), sorted(wat))})

    if B:
        sizes = [len(b["serials"]) for b in B]
        full = [s for s in sizes if s == max(sizes)]
        part = [s for s in sizes if s != max(sizes)]
        I.append({"level": "info",
            "msg": "%d boxes: %d of %d, %s."
                   % (len(B), len(full), max(sizes),
                      "no partial" if not part
                      else "partial " + "+".join(str(x) for x in part))})
        for b in B:
            miss = [k for k in ("box_no", "pack_date", "bin", "shift")
                    if not b.get(k)]
            if miss:
                I.append({"level": "warn",
                    "msg": "Box %s: could not split %s out of %r"
                           % (b.get("box_no") or "?", "/".join(miss),
                              (b["raw"] or "")[:44])})


# --------------------------------------------------------------------------

def report(r):
    H = r["header"]
    print("=" * 74)
    print("ICON TRACE  ·  challan import  ·  %s" % r["source_file"])
    print("=" * 74)
    print(" challan     %s" % H.get("challan_no_raw"))
    if "seq" in H:
        print("             fy=%s  seq=%s  suffix=%s   -> renders as %s"
              % (H.get("fy_label"), H.get("seq"), H.get("suffix") or "-",
                 H.get("display")))
    for k in ("challan_date", "invoice_no", "invoice_date", "vehicle_no",
              "lr_no", "transporter", "buyer_gstin", "model", "wattage",
              "qty", "kw"):
        if H.get(k) is not None:
            print(" %-11s %s" % (k, H[k]))
    print()
    print(" boxes %d · serials %d" % (len(r["boxes"]), len(r["serials"])))
    for b in r["boxes"]:
        print("   %-8s %-11s bin %-3s shift %-3s  %d modules"
              % (b.get("box_no") or "?", b.get("pack_date") or "?",
                 b.get("bin") or "?", b.get("shift") or "?", len(b["serials"])))
    ok = [s for s in r["serials"] if s["ok"]]
    if ok:
        print()
        print(" sample decomposition")
        for s in (ok[0], ok[-1]):
            print("   %s -> v%d  %s  shift %s  seq %d  %dW"
                  % (s["serial"], s["format_version"], s["date_produced"],
                     s["shift"], s["sequence"], s["wattage"]))
    print()
    for it in r["issues"]:
        tag = {"ok": "  OK  ", "warn": " WARN ", "block": "BLOCK ",
               "info": " INFO "}[it["level"]]
        print(" [%s] %s" % (tag, it["msg"]))
    print()
    print(" RESULT: %s" % ("importable" if r["ok"]
                           else "HELD - fix before loading"))


def to_sql(results):
    out = ["-- ICON TRACE historical challan import",
           "-- seq is NOT unique on its own: 742 and 742 (A) both exist.",
           "-- UNIQUE KEY should be (fy, seq, suffix).", ""]
    for r in results:
        if not r["ok"]:
            out.append("-- SKIPPED %s (held)" % r["source_file"])
            continue
        H = r["header"]
        out.append(
            "INSERT INTO challan (fy, seq, suffix, challan_date, invoice_no, "
            "vehicle_no, lr_no, transporter, buyer_gstin, model, wattage, qty) "
            "VALUES (%d, %d, %s, '%s', '%s', '%s', '%s', '%s', '%s', '%s', %d, %d);"
            % (H["fy"], H["seq"],
               "'%s'" % H["suffix"] if H.get("suffix") else "NULL",
               H.get("challan_date"), H.get("invoice_no") or "",
               H.get("vehicle_no") or "", H.get("lr_no") or "",
               (H.get("transporter") or "").replace("'", "''"),
               H.get("buyer_gstin") or "", H.get("model") or "",
               int(H.get("wattage") or 0), int(H.get("qty") or 0)))
        for s in r["serials"]:
            out.append(
                "INSERT INTO challan_serial (fy, seq, suffix, serial, box_no, "
                "format_version, date_produced, shift, sequence, wattage) "
                "VALUES (%d, %d, %s, '%s', '%s', %d, '%s', %d, %d, %d);"
                % (H["fy"], H["seq"],
                   "'%s'" % H["suffix"] if H.get("suffix") else "NULL",
                   s["serial"], s.get("box_no") or "", s["format_version"],
                   s["date_produced"], s["shift"], s["sequence"], s["wattage"]))
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Import challan workbooks.")
    ap.add_argument("xlsx", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--sql")
    a = ap.parse_args()

    res = []
    for p in a.xlsx:
        r = read_challan(p)
        report(r)
        print()
        res.append(r)

    held = [r for r in res if not r["ok"]]
    print("=" * 74)
    print("%d file(s): %d importable, %d held"
          % (len(res), len(res) - len(held), len(held)))

    # cross-file: the same serial must never appear on two challans
    where = {}
    for r in res:
        for s in r["serials"]:
            where.setdefault(s["serial"], []).append(
                r["header"].get("challan_no_raw") or r["source_file"])
    clash = {k: v for k, v in where.items() if len(v) > 1}
    if clash:
        print("BLOCK: %d serial(s) appear on more than one challan, e.g. %s"
              % (len(clash), list(clash.items())[0]))
    else:
        print("No serial appears on more than one challan.")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, default=str)
        print("JSON -> %s" % a.json)
    if a.sql:
        with open(a.sql, "w", encoding="utf-8") as fh:
            fh.write(to_sql(res))
        print("SQL  -> %s" % a.sql)
    sys.exit(2 if held else 0)
