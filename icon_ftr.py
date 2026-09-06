"""
ICON TRACE - Flash Test Report.

The FTR that goes to the customer with the challan is Sun Simulator data,
serial by serial. Icon already produces every figure in it - the tester writes
them - and someone assembles the report by hand afterwards.

Since the SS export is already read for FQC, the report is a lookup rather
than a job: give it a list of serials and it returns their measured values.

Two rules that make it trustworthy:

  * The LATEST VALID row wins. Retesting after a failed probe is routine -
    12 of 53 serials in a real sample had two rows - so taking the first
    would report a reading the operator already rejected.

  * A serial with no valid row is reported as MISSING with the reason, never
    dropped and never filled with a plausible number. A gap the customer can
    see is a question; a silent omission is a discrepancy found later.
"""

import os, csv, datetime
import icon_evidence as ev

# Column layout of the real export, confirmed against FTR.csv:
#   0 TestTime  1 ID  2 Pmax  3 Isc  4 Voc  5 Ipm  6 Vpm  7 FF
#   8 Rs  9 Rs_M  10 Rsh  11 Eff  12 T_Object  13 T_Target  14 Irr_Target
COLUMNS = [
    ("serial", "Module Serial", None),
    ("pmax", "Pmax (W)", 2),
    ("isc", "Isc (A)", 3),
    ("voc", "Voc (V)", 4),
    ("ipm", "Ipm (A)", 5),
    ("vpm", "Vpm (V)", 6),
    ("ff", "FF (%)", 7),
    ("rs", "Rs (ohm)", 8),
    ("rsh", "Rsh (ohm)", 10),
    ("eff", "Efficiency (%)", 11),
    ("temp", "Cell Temp (C)", 12),
    ("irr", "Irradiance (W/m2)", 14),
    ("tested_at", "Tested", 0),
]


def _num(v, places=2):
    try:
        f = float(v)
        if f != f:
            return None
        return round(f, places)
    except (TypeError, ValueError):
        return None


def build(cfg, serials):
    """Return one row per serial, in the order given."""
    path = (cfg.get("ss_csv_path") or "").strip()
    out = {"rows": [], "missing": [], "source": path,
           "generated": datetime.datetime.now().isoformat(timespec="seconds")}
    if not path or not os.path.exists(path):
        out["error"] = ("Sun Simulator export not reachable at %r. Set it in "
                        "Settings - the FTR is built from it, not typed."
                        % (path or "(not configured)"))
        out["missing"] = [{"serial": s, "why": "no source"} for s in serials]
        return out

    want = {s.strip().upper() for s in serials}
    hits = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace",
              newline="") as fh:
        for r in csv.reader(fh):
            if len(r) <= 14:
                continue
            sid = r[1].strip().upper()
            if sid in want:
                hits.setdefault(sid, []).append(r)

    for s in serials:
        key = s.strip().upper()
        rs = hits.get(key, [])
        good = [r for r in rs if ev.reading_is_valid(r)[0]]
        if not good:
            why = ("tested %d time(s), never read - probe, polarity or "
                   "soldering" % len(rs)) if rs else "no row in the export"
            out["missing"].append({"serial": s, "why": why,
                                   "attempts": len(rs)})
            continue
        last = max(good, key=lambda r: r[0])
        row = {"serial": s}
        for key_name, _label, idx in COLUMNS:
            if idx is None:
                continue
            row[key_name] = last[idx] if key_name == "tested_at" \
                else _num(last[idx], 3 if key_name in ("rs",) else 2)
        row["retests"] = len(rs) - 1
        out["rows"].append(row)
    return out


def summary(ftr):
    if not ftr["rows"]:
        return {}
    p = [r["pmax"] for r in ftr["rows"] if r.get("pmax") is not None]
    if not p:
        return {}
    return {"count": len(ftr["rows"]), "missing": len(ftr["missing"]),
            "pmax_min": round(min(p), 2), "pmax_max": round(max(p), 2),
            "pmax_avg": round(sum(p) / len(p), 2)}
