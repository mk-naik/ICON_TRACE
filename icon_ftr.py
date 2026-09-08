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

# The columns and their headings. The POSITION of each one is not here: it
# comes from the same Settings map FQC reads, through ev.param_cols(), so the
# report and the grading screen can never disagree about which column Pmax is
# in. A second column map maintained beside the first is how the FTR ends up
# quoting Rsh as a module's power.
COLUMNS = [
    ("serial", "Module Serial"),
    ("pmax", "Pmax (W)"),
    ("isc", "Isc (A)"),
    ("voc", "Voc (V)"),
    ("ipm", "Ipm (A)"),
    ("vpm", "Vpm (V)"),
    ("ff", "FF (%)"),
    ("rs", "Rs (ohm)"),
    ("rsh", "Rsh (ohm)"),
    ("eff", "Efficiency (%)"),
    ("temp", "Cell Temp (C)"),
    ("irr", "Irradiance (W/m2)"),
    ("tested_at", "Tested"),
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
    # Both lines: each has its own tester, its own export and its own column
    # map, and a challan's boxes can carry modules built on either.
    srcs = ev.sources(cfg)
    out = {"rows": [], "missing": [],
           "source": ", ".join("%s %s" % (s["label"], s["ss_path"])
                               for s in srcs if s["ss_path"]),
           "generated": datetime.datetime.now().isoformat(timespec="seconds")}
    live = [s for s in srcs if s["ss_path"] and os.path.exists(s["ss_path"])]
    if not live:
        out["error"] = ("No Sun Simulator export is reachable%s. Set the "
                        "paths in Settings - the FTR is built from them, not "
                        "typed." % (" (%s)" % out["source"] if out["source"]
                                    else ""))
        out["missing"] = [{"serial": s, "why": "no source"} for s in serials]
        return out
    out["unreachable"] = [s["label"] for s in srcs
                          if s["ss_path"] and s not in live]

    want = {s.strip().upper() for s in serials}
    hits = {}
    for src in live:
        # one map per source, shared with FQC - see COLUMNS above
        col = dict((k, c) for (k, _lab, c, _u) in src["cols"])
        col["tested_at"] = ev.COL_TIME
        scol = src["serial_col"]
        need = max([scol] + list(col.values()))
        with open(src["ss_path"], "r", encoding="utf-8-sig",
                  errors="replace", newline="") as fh:
            for r in csv.reader(fh):
                if len(r) <= need:
                    continue
                sid = r[scol].strip().upper()
                if sid in want:
                    hits.setdefault(sid, []).append((src, col, r))

    for s in serials:
        key = s.strip().upper()
        rs = hits.get(key, [])
        good = [(src, col, r) for (src, col, r) in rs
                if ev.reading_is_valid(r, col["pmax"], col["isc"],
                                       col["voc"])[0]]
        if not good:
            why = ("tested %d time(s), never read - probe, polarity or "
                   "soldering" % len(rs)) if rs else "no row in the export"
            if not rs and out["unreachable"]:
                why += " (%s could not be read)" % ", ".join(out["unreachable"])
            out["missing"].append({"serial": s, "why": why,
                                   "attempts": len(rs)})
            continue
        src, col, last = max(good, key=lambda t: t[2][ev.COL_TIME])
        row = {"serial": s, "line": src["line"]}
        for key_name, _label in COLUMNS:
            idx = col.get(key_name)
            if idx is None:                       # 'serial', already set
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
