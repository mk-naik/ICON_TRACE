"""
ICON TRACE - FQC evidence.

FQC reads the Sun Simulator and EL DIRECTLY, not through the server.

SS, EL and FQC share one switch. The server is roughly four switches away.
Routing evidence via the server would make FQC depend on four hops the data
never needs to cross, so the flow is:

    SS  ->  FQC  ->  Server          not   SS -> Server -> FQC

The server runs its own ingest for the Flash Test Report, which gives a
second path for free. Fallback chain:

    read SS live  ->  ask the server  ->  NC

TWO ABSENCE STATES, and they mean opposite things:

    NC   No Connection. The source is unreachable. Nothing is wrong with the
         module; the network is down. Grade provisionally on verbal
         information and confirm when the link returns.

    NA   Not Available. The source IS reachable and the serial genuinely is
         not there. This is a QUALITY SIGNAL, not missing data - the usual
         causes are electrical faults at the SS input: probe or Zig not
         seated at the JB connector, plus-minus interchanged, poor soldering.
         An NA module may have a junction box defect and must go to review.
         Never wave it through.

Unit-1's monitor.py proves live reading works - it polls the SS CSV over SMB
every 800 ms on size and mtime. But it reads the TAIL, meaning whatever just
came off the tester. FQC needs a LOOKUP BY SERIAL, which is a different
access pattern, and because the file is written live a short row means the
write is in progress: retry, never report absent.
"""

import os, csv, io, time, random, datetime

NC  = "NC"      # source unreachable
NA  = "NA"      # source reachable, no row at all for this serial
BAD = "BAD"     # row(s) exist but every reading is invalid - the probe was
                # not connected. Confirmed in real data: Pmax ~0.005 W,
                # Isc = nan, Voc negative. Strongest quality signal there is,
                # because the module WAS tested and could not be read.
OK  = "OK"

# A real SS export has NO header row and ~87 columns. Confirmed layout:
#   0 TestTime  1 ID  2 Pmax  3 Isc  4 Voc  5 Ipm  6 Vpm  7 FF
#   8 Rs  9 Rs_M  10 Rsh  11 Eff  12 T_Object  13 T_Target  14 Irr_Target
COL_TIME, COL_ID, COL_PMAX, COL_ISC, COL_VOC = 0, 1, 2, 3, 4

# The tester measures far more than Pmax, and the Flash Test Report the
# customer receives carries all of it. Reading only Pmax meant FQC could show
# a module's power but not why it graded the way it did. Every column here is
# independently configurable in Settings, same as Serial and Pmax — the real
# export's layout has shifted once already and will again.
PARAMS = [("pmax", "Pmax", "ss_pmax_col", 2, "W"),
          ("isc", "Isc", "ss_isc_col", 3, "A"),
          ("voc", "Voc", "ss_voc_col", 4, "V"),
          ("ipm", "Ipm", "ss_ipm_col", 5, "A"),
          ("vpm", "Vpm", "ss_vpm_col", 6, "V"),
          ("ff", "FF", "ss_ff_col", 7, "%"),
          ("rs", "Rs", "ss_rs_col", 8, "ohm"),
          ("rsh", "Rsh", "ss_rsh_col", 10, "ohm"),
          ("eff", "Efficiency", "ss_eff_col", 11, "%"),
          ("temp", "Cell temp", "ss_temp_col", 12, "C"),
          ("irr", "Irradiance", "ss_irr_col", 14, "W/m2")]


def _param_cols(cfg):
    """(key, label, column, unit) for every SS parameter, each read from its
    own Settings field rather than assumed at the default position."""
    out = []
    for key, label, cfg_key, default, unit in PARAMS:
        try:
            col = int(cfg.get(cfg_key, default))
        except (TypeError, ValueError):
            col = default
        out.append((key, label, col, unit))
    return out

SERIAL_SHAPE = None      # set lazily to avoid an import cycle


def _looks_like_serial(s):
    import re
    global SERIAL_SHAPE
    if SERIAL_SHAPE is None:
        SERIAL_SHAPE = re.compile(r"^ICON\d{3}[A-Z]\d{2}[0-9A-C]\d{7}$")
    return bool(SERIAL_SHAPE.match((s or "").strip().upper()))


def _num(v):
    try:
        f = float(v)
        return None if f != f else f          # NaN
    except (TypeError, ValueError):
        return None


def reading_is_valid(row, pmax_col=COL_PMAX, isc_col=COL_ISC, voc_col=COL_VOC):
    """A disconnected probe leaves a row behind, so presence is not enough.

    Real signature, straight out of the plant's own export:
        Pmax 0.005500   Isc nan   Voc -0.898088   Ipm -0.004184

    The three columns default to the standard export layout so callers
    without a mapped Settings config (the FTR generator, the anomaly scan
    with no cfg) still work; a caller holding cfg passes its mapped columns.
    """
    pmax = _num(row[pmax_col]) if len(row) > pmax_col else None
    isc  = _num(row[isc_col])  if len(row) > isc_col else None
    voc  = _num(row[voc_col])  if len(row) > voc_col else None
    if pmax is None or pmax < 1.0:
        return False, "Pmax is %s - the probe was not reading." % row[pmax_col]
    if isc is None:
        return False, "Isc is %r - probe not connected." % row[isc_col]
    if voc is None or voc <= 0:
        return False, "Voc is %s - polarity or connection fault." % row[voc_col]
    return True, None


def _read_rows(path, retries=3, pause=0.15):
    """Read a CSV that is being appended to. A short final row means the
    write is mid-flight - retry rather than treat it as absent."""
    last = None
    for _ in range(retries):
        with open(path, "r", encoding="utf-8", errors="replace",
                  newline="") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            time.sleep(pause)
            continue
        widths = [len(r) for r in rows if r]
        if not widths:
            time.sleep(pause)
            continue
        full = max(widths)
        if len(rows[-1]) < full:          # partial write in progress
            last = rows
            time.sleep(pause)
            continue
        return rows
    return last or []


def read_sun_simulator(cfg, serial):
    """Look up one serial in the live SS CSV.

    A module can appear more than once - retesting after a failed probe is
    routine, and 12 of 53 serials in a real 45-minute sample had two rows.
    So collect EVERY row for the serial and take the latest VALID one. Only
    if none is valid does the module carry a fault.
    """
    path = (cfg.get("ss_csv_path") or "").strip()
    if not path:
        return {"state": NC, "pmax": None, "attempts": 0,
                "note": "No Sun Simulator path configured (Settings)."}
    if not os.path.exists(path):
        return {"state": NC, "pmax": None, "attempts": 0,
                "note": "Sun Simulator share unreachable: %s" % path}
    try:
        scol = int(cfg.get("ss_serial_col", COL_ID))
        cols = _param_cols(cfg)
        pcol = dict((k, c) for (k, _lab, c, _u) in cols)["pmax"]
        max_col = max([scol] + [c for (_k, _lab, c, _u) in cols])
        want = serial.strip().upper()
        hits = [r for r in _read_rows(path)
                if len(r) > max_col and r[scol].strip().upper() == want]
    except Exception as e:
        return {"state": NC, "pmax": None, "attempts": 0,
                "note": "SS read failed: %s" % e}

    if not hits:
        return {"state": NA, "pmax": None, "attempts": 0,
                "note": "Reachable, but this serial is not in the file. It may "
                        "not have reached the tester yet, or it was tested "
                        "under a scanned-in-error ID."}

    isc_col = dict((k, c) for (k, _lab, c, _u) in cols)["isc"]
    voc_col = dict((k, c) for (k, _lab, c, _u) in cols)["voc"]
    good = [r for r in hits if reading_is_valid(r, pcol, isc_col, voc_col)[0]]
    if good:
        last = max(good, key=lambda r: r[COL_TIME])
        out = {"state": OK, "pmax": _num(last[pcol]),
               "tested_at": last[COL_TIME], "attempts": len(hits),
               "note": "Read live from the Sun Simulator%s."
                       % (" (retested %d times)" % len(hits) if len(hits) > 1
                          else "")}
        # the full measurement, not just power - each column independently
        # mapped in Settings, same as Serial and Pmax
        out["params"] = [{"key": k, "label": lab, "unit": u,
                          "value": _num(last[i]) if len(last) > i else None}
                         for (k, lab, i, u) in cols]
        for (k, _lab, i, _u) in cols:
            out[k] = _num(last[i]) if len(last) > i else None
        return out

    _, why = reading_is_valid(hits[-1], pcol, isc_col, voc_col)
    return {"state": BAD, "pmax": None, "attempts": len(hits),
            "tested_at": hits[-1][COL_TIME],
            "note": "Tested %d time(s) and never read. %s Check the probe/Zig "
                    "at the JB connector, plus-minus polarity and the "
                    "soldering." % (len(hits), why)}


# Rows the tester writes that are not modules at all: calibration, reference
# panels and dry runs. Routine, expected, and NOT anomalies - flagging them
# would train operators to ignore the panel.
CALIBRATION_IDS = {"1", "0", "REFE", "REFERANCE", "REFERENCE", "TEST", "CAL"}


def is_calibration(sid):
    s = (sid or "").strip().upper()
    return (s in CALIBRATION_IDS or s.startswith("REF")
            or (s.isdigit() and len(s) <= 4))


def scan_anomalies(cfg, limit=200):
    """Rows the tester wrote that no serial lookup will ever find.

    Calibration and reference rows are counted, never flagged. What is left
    is either a barcode that would not scan, or a module that was tested and
    never read.
    """
    path = (cfg.get("ss_csv_path") or "").strip()
    if not path or not os.path.exists(path):
            return {"available": False, "junk": [], "failed": [], "calibration": 0}
    scol = int(cfg.get("ss_serial_col", COL_ID))
    cols = dict((k, c) for (k, _lab, c, _u) in _param_cols(cfg))
    pcol, isc_col, voc_col = cols["pmax"], cols["isc"], cols["voc"]
    rows = _read_rows(path)[-limit:]
    junk, by, calib = [], {}, 0
    for r in rows:
        if len(r) <= max(scol, pcol, isc_col, voc_col):
            continue
        sid = r[scol].strip()
        if is_calibration(sid):
            calib += 1
        elif not _looks_like_serial(sid):
            junk.append({"at": r[COL_TIME], "id": sid, "pmax": r[pcol]})
        else:
            by.setdefault(sid.upper(), []).append(r)
    failed = []
    for sid, rs in by.items():
        if not any(reading_is_valid(r, pcol, isc_col, voc_col)[0] for r in rs):
            failed.append({"serial": sid, "attempts": len(rs),
                           "at": rs[-1][COL_TIME],
                           "why": reading_is_valid(rs[-1], pcol, isc_col, voc_col)[1]})
    return {"available": True, "junk": junk, "failed": failed,
            "calibration": calib}


def read_el(cfg, serial):
    """EL verdict comes from the folder the image was filed under."""
    root = (cfg.get("el_root") or "").strip()
    if not root:
        return {"state": NC, "verdict": None,
                "note": "No EL folder configured (Settings)."}
    if not os.path.isdir(root):
        return {"state": NC, "verdict": None,
                "note": "EL share unreachable: %s" % root}
    try:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if os.path.splitext(fn)[0].strip().upper() == serial.upper():
                    verdict = os.path.basename(dirpath).strip()
                    return {"state": OK, "verdict": verdict or "OK",
                            "path": os.path.join(dirpath, fn),
                            "note": "Folder name is the operator's verdict."}
    except Exception as e:
        return {"state": NC, "verdict": None, "note": "EL read failed: %s" % e}
    return {"state": NA, "verdict": None,
            "note": "Reachable, but no image for this serial."}


def _sim_params(w, ratio, rnd):
    isc = round(w * ratio / 38.9, 3)
    voc = round(48.9 + rnd.uniform(-.4, .4), 3)
    ipm = round(isc * 0.95, 3)
    vpm = round(w * ratio / ipm, 3) if ipm else None
    ff = round((w * ratio) / (isc * voc) * 100, 2) if isc and voc else None
    return {"isc": isc, "voc": voc, "ipm": ipm, "vpm": vpm, "ff": ff,
            "rs": round(rnd.uniform(.35, .45), 3),
            "rsh": round(rnd.uniform(180, 460), 2),
            "eff": round(23.0 + rnd.uniform(-.4, .5), 3),
            "temp": round(24 + rnd.uniform(0, 2), 2), "irr": 1000.0}


def simulate(serial, wattage):
    """Sandbox only. Clearly labelled so a simulated value is never mistaken
    for a real one."""
    rnd = random.Random(serial)
    roll = rnd.random()
    if roll < 0.06:
        _r = rnd.uniform(0.93, 0.965)
        _d = {"state": OK, "pmax": round(wattage * _r, 1), "note": "SIMULATED"}
        _d.update(_sim_params(wattage, _r, rnd))
        _d["params"] = [{"key": k, "label": lab, "unit": u, "value": _d.get(k)}
                        for (k, lab, _cfg_key, _i, u) in PARAMS]
        return (_d,
                {"state": OK, "verdict": rnd.choice(["Cell Crack", "Ribbon Short"]),
                 "note": "SIMULATED"})
    if roll < 0.14:
        _r = rnd.uniform(0.965, 0.99)
        _d = {"state": OK, "pmax": round(wattage * _r, 1), "note": "SIMULATED"}
        _d.update(_sim_params(wattage, _r, rnd))
        _d["params"] = [{"key": k, "label": lab, "unit": u, "value": _d.get(k)}
                        for (k, lab, _cfg_key, _i, u) in PARAMS]
        return (_d,
                {"state": OK, "verdict": "PATCHES", "note": "SIMULATED"})
    _r = rnd.uniform(0.99, 1.02)
    _d = {"state": OK, "pmax": round(wattage * _r, 1), "note": "SIMULATED"}
    _d.update(_sim_params(wattage, _r, rnd))
    _d["params"] = [{"key": k, "label": lab, "unit": u, "value": _d.get(k)}
                    for (k, lab, _cfg_key, _i, u) in PARAMS]
    return (_d,
            {"state": OK, "verdict": "OK", "note": "SIMULATED"})


def propose_grade(wattage, ss, el):
    """Propose, never decide. The operator confirms or overrides."""
    if ss["state"] == BAD:
        return None, ("The tester could not read this module. That is a fault, "
                      "not missing data - send it to review before grading.")
    if ss["state"] != OK or el["state"] != OK:
        return None, "Evidence incomplete - grade on verbal information and "\
                     "it will be confirmed when the source returns."
    v = (el.get("verdict") or "").strip().lower()
    if v in ("ok", "pass", ""):
        base = "A"
    elif v in ("patches", "chip cut"):
        base = "GY"
    else:
        base = "BGY"
    ratio = (ss["pmax"] or 0) / float(wattage or 1)
    if base == "A" and ratio < 0.97:
        return "GY", "EL is clean but Pmax is %.1f%% of nameplate." % (ratio*100)
    return base, "EL verdict %r, Pmax %.1f%% of nameplate." % (
        el.get("verdict"), ratio * 100)


def gather(cfg, serial, wattage, sandbox=False):
    """One call for the FQC screen. Returns evidence plus a proposed grade."""
    if sandbox:
        ss, el = simulate(serial, wattage)
    else:
        ss, el = read_sun_simulator(cfg, serial), read_el(cfg, serial)
    grade, why = propose_grade(wattage, ss, el)
    degraded = ss["state"] != OK or el["state"] != OK
    return {
        "pmax": ss.get("pmax"), "params": ss.get("params") or [],
        "ss_state": ss["state"], "ss_note": ss["note"],
        "ss_attempts": ss.get("attempts"), "tested_at": ss.get("tested_at"),
        "fault": ss["state"] == BAD,
        "el": el.get("verdict"), "el_state": el["state"], "el_note": el["note"],
        "el_path": el.get("path"),
        "proposed": grade, "why": why,
        "degraded": degraded,
        "mode": "provisional" if degraded else "confirmed",
        "sandbox": sandbox,
    }
