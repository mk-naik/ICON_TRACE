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


# (key, label, default column, unit) - the shape gather() iterates, without
# needing a config to resolve positions it is not going to use
PARAMS_KEYS = [(k, lab, default, unit)
               for (k, lab, _cfg_key, default, unit) in PARAMS]


def param_cols(cfg):
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

# Unit-2 runs two lines and each has its OWN Sun Simulator and EL. Two
# testers means two exports, and they can be reconfigured or replaced one at
# a time - so each source carries its own column map rather than sharing one.
LINES = ("A", "B")


def sources(cfg, line=None):
    """The configured evidence sources, one per line, each fully resolved.

    Reads the per-line settings (ss_a_csv_path, ss_a_pmax_col, el_a_root …)
    and falls back to the single-source keys for Line A, so a system
    configured before there were two lines keeps working untouched.
    """
    out = []
    for ln in LINES:
        p = "ss_%s_" % ln.lower()
        ss = (cfg.get(p + "csv_path") or "").strip()
        el = (cfg.get("el_%s_root" % ln.lower()) or "").strip()
        if ln == "A":
            ss = ss or (cfg.get("ss_csv_path") or "").strip()
            el = el or (cfg.get("el_root") or "").strip()
        if not ss and not el:
            continue

        def col(key, default, prefix=p):
            for k in (prefix + key, "ss_" + key):        # per line, then shared
                if cfg.get(k) not in (None, ""):
                    try:
                        return int(cfg[k])
                    except (TypeError, ValueError):
                        pass
            return default

        cols = [(k, lab, col(cfg_key[3:], default), unit)
                for (k, lab, cfg_key, default, unit) in PARAMS]
        by = dict((k, c) for (k, _lab, c, _u) in cols)
        out.append({
            "line": ln, "label": "Line %s" % ln,
            "ss_path": ss, "el_root": el,
            "serial_col": col("serial_col", COL_ID),
            "cols": cols, "pmax_col": by["pmax"], "isc_col": by["isc"],
            "voc_col": by["voc"],
        })
    if line:
        out = [s for s in out if s["line"] == str(line).upper()]
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


def read_sun_simulator(cfg, serial, line=None):
    """Look up one serial across the Sun Simulators.

    Unit-2 has TWO lines and each has its own tester, so there are two CSVs
    and either may hold the serial. A serial carries no line indicator, so
    with no line given both are searched and the latest valid row across
    them wins.

    A module can appear more than once - retesting after a failed probe is
    routine, and 12 of 53 serials in a real 45-minute sample had two rows.
    So collect EVERY row for the serial and take the latest VALID one. Only
    if none is valid does the module carry a fault.

    WHY THE UNREACHABLE CASE IS NC AND NOT NA: NA means the tester was
    reachable and the serial genuinely is not there, which is a quality
    signal that sends the module to review. If one line's share is down, the
    serial may be sitting on it - so a miss with any source unreachable is
    NC, and the note names the line that could not be read.
    """
    srcs = sources(cfg, line)
    if not srcs:
        return {"state": NC, "pmax": None, "attempts": 0,
                "note": "No Sun Simulator path configured (Settings)."}

    want = serial.strip().upper()
    hits, down, read = [], [], []
    for s in srcs:
        if not s["ss_path"]:
            continue
        if not os.path.exists(s["ss_path"]):
            down.append(s)
            continue
        try:
            cols = s["cols"]
            scol = s["serial_col"]
            top = max([scol] + [c for (_k, _lab, c, _u) in cols])
            for r in _read_rows(s["ss_path"]):
                if len(r) > top and r[scol].strip().upper() == want:
                    hits.append((s, r))
            read.append(s)
        except Exception as e:
            down.append(dict(s, error=str(e)))

    if not read and not hits:
        why = "; ".join("%s: %s" % (s["label"], s.get("error") or "unreachable")
                        for s in down) or "no path configured"
        return {"state": NC, "pmax": None, "attempts": 0,
                "note": "No Sun Simulator could be read (%s)." % why}

    if not hits:
        if down:
            return {"state": NC, "pmax": None, "attempts": 0,
                    "note": "Not on %s, and %s could not be read — the serial "
                            "may be on it. Confirm when the link returns."
                            % (", ".join(s["label"] for s in read),
                               ", ".join(s["label"] for s in down))}
        return {"state": NA, "pmax": None, "attempts": 0,
                "note": "Reachable on %s, but this serial is not in the file. "
                        "It may not have reached the tester yet, or it was "
                        "tested under a scanned-in-error ID."
                        % ", ".join(s["label"] for s in read)}

    good = [(s, r) for (s, r) in hits
            if reading_is_valid(r, s["pmax_col"], s["isc_col"],
                                s["voc_col"])[0]]
    if good:
        src, last = max(good, key=lambda pair: pair[1][COL_TIME])
        cols = src["cols"]
        out = {"state": OK, "pmax": _num(last[src["pmax_col"]]),
               "tested_at": last[COL_TIME], "attempts": len(hits),
               "line": src["line"], "source": src["label"],
               "note": "Read live from %s%s." % (
                   src["label"],
                   " (retested %d times)" % len(hits) if len(hits) > 1 else "")}
        # the full measurement, not just power - each column independently
        # mapped in Settings, per source, same as Serial and Pmax
        out["params"] = [{"key": k, "label": lab, "unit": u,
                          "value": _num(last[i]) if len(last) > i else None}
                         for (k, lab, i, u) in cols]
        for (k, _lab, i, _u) in cols:
            out[k] = _num(last[i]) if len(last) > i else None
        return out

    src, last = hits[-1]
    _, why = reading_is_valid(last, src["pmax_col"], src["isc_col"],
                              src["voc_col"])
    return {"state": BAD, "pmax": None, "attempts": len(hits),
            "tested_at": last[COL_TIME], "line": src["line"],
            "source": src["label"],
            "note": "Tested %d time(s) on %s and never read. %s Check the "
                    "probe/Zig at the JB connector, plus-minus polarity and "
                    "the soldering." % (len(hits), src["label"], why)}


# Rows the tester writes that are not modules at all: calibration, reference
# panels and dry runs. Routine, expected, and NOT anomalies - flagging them
# would train operators to ignore the panel.
CALIBRATION_IDS = {"1", "0", "REFE", "REFERANCE", "REFERENCE", "TEST", "CAL"}


def is_calibration(sid):
    s = (sid or "").strip().upper()
    return (s in CALIBRATION_IDS or s.startswith("REF")
            or (s.isdigit() and len(s) <= 4))


def scan_anomalies(cfg, limit=200, line=None):
    """Rows the testers wrote that no serial lookup will ever find.

    Calibration and reference rows are counted, never flagged. What is left
    is either a barcode that would not scan, or a module that was tested and
    never read. Both lines are scanned, and each row says which it came from.
    """
    junk, failed, calib, seen_any = [], [], 0, False
    for s in sources(cfg, line):
        path = s["ss_path"]
        if not path or not os.path.exists(path):
            continue
        seen_any = True
        scol, pcol = s["serial_col"], s["pmax_col"]
        isc_col, voc_col = s["isc_col"], s["voc_col"]
        by = {}
        for r in _read_rows(path)[-limit:]:
            if len(r) <= max(scol, pcol, isc_col, voc_col):
                continue
            sid = r[scol].strip()
            if is_calibration(sid):
                calib += 1
            elif not _looks_like_serial(sid):
                junk.append({"at": r[COL_TIME], "id": sid, "pmax": r[pcol],
                             "line": s["line"]})
            else:
                by.setdefault(sid.upper(), []).append(r)
        for sid, rs in by.items():
            if not any(reading_is_valid(r, pcol, isc_col, voc_col)[0] for r in rs):
                failed.append({"serial": sid, "attempts": len(rs),
                               "at": rs[-1][COL_TIME], "line": s["line"],
                               "why": reading_is_valid(rs[-1], pcol, isc_col,
                                                       voc_col)[1]})
    if not seen_any:
        return {"available": False, "junk": [], "failed": [], "calibration": 0}
    return {"available": True, "junk": junk, "failed": failed,
            "calibration": calib}


def read_el(cfg, serial, line=None):
    """EL verdict comes from the folder the image was filed under.

    Two lines, two EL stations, two output folders - so with no line given
    both are searched. Unreachable is NC and not NA for the same reason as
    the Sun Simulator: the image may be sitting on the share that is down.
    """
    srcs = [s for s in sources(cfg, line) if s["el_root"]]
    if not srcs:
        return {"state": NC, "verdict": None,
                "note": "No EL folder configured (Settings)."}
    down, read = [], []
    for s in srcs:
        root = s["el_root"]
        if not os.path.isdir(root):
            down.append(s)
            continue
        try:
            for dirpath, _dirs, files in os.walk(root):
                for fn in files:
                    if os.path.splitext(fn)[0].strip().upper() == serial.upper():
                        return {"state": OK,
                                "verdict": os.path.basename(dirpath).strip() or "OK",
                                "path": os.path.join(dirpath, fn),
                                "line": s["line"], "source": s["label"],
                                "note": "Folder name is the operator's verdict "
                                        "(%s)." % s["label"]}
            read.append(s)
        except Exception as e:
            down.append(dict(s, error=str(e)))
    if not read:
        return {"state": NC, "verdict": None,
                "note": "No EL folder could be read (%s)."
                        % "; ".join("%s: %s" % (s["label"],
                                                s.get("error") or "unreachable")
                                    for s in down)}
    if down:
        return {"state": NC, "verdict": None,
                "note": "No image on %s, and %s could not be read — it may be "
                        "there." % (", ".join(s["label"] for s in read),
                                    ", ".join(s["label"] for s in down))}
    return {"state": NA, "verdict": None,
            "note": "Reachable on %s, but no image for this serial."
                    % ", ".join(s["label"] for s in read)}


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


# EL verdicts that mean "nothing wrong with this module". Anything else is a
# defect, whatever the module measures - a cracked cell is not an A module on
# the strength of its power.
EL_CLEAN = ("ok", "pass", "")


def propose_outcome(wattage, ss, el):
    """PASS or REJECT, proposed. Never decided here.

    A module passes when it makes its rated wattage AND the EL is clean:

        Pmax >= wattage   and   EL verdict clean   ->  pass
        anything else                              ->  reject

    Pmax is measured against the module's own wattage, not a tolerance band
    below it. A 590 W module reading 585 W is not a 590 W module, and the
    customer is buying the number on the label.

    Returns (outcome, why) where outcome is 'pass', 'reject', or None when
    there is not enough evidence to propose anything.
    """
    if ss["state"] == BAD:
        return None, ("The tester could not read this module. That is a "
                      "fault, not missing data - it has to be looked at "
                      "before it can be judged.")
    if ss["state"] != OK or el["state"] != OK:
        return None, ("Evidence incomplete - decide on what is in front of "
                      "you and it will be confirmed when the source returns.")

    pmax = ss.get("pmax") or 0
    want = float(wattage or 0)
    verdict = (el.get("verdict") or "").strip()
    clean = verdict.strip().lower() in EL_CLEAN

    if pmax >= want and clean:
        return "pass", "EL clean and Pmax %.1f W is at or above the %g W " \
                       "wattage." % (pmax, want)
    if pmax < want and not clean:
        return "reject", "EL reads %r and Pmax %.1f W is below the %g W " \
                         "wattage." % (verdict, pmax, want)
    if pmax < want:
        return "reject", "EL is clean but Pmax %.1f W is below the %g W " \
                         "wattage." % (pmax, want)
    return "reject", "Pmax %.1f W meets the %g W wattage, but the EL " \
                     "reads %r." % (pmax, want, verdict)


def gather(cfg, serial, wattage, sandbox=False, line=None):
    """One call for the FQC screen. Returns evidence plus a proposed grade.

    `line` narrows the lookup to that line's tester - the FQC station knows
    its own line from station_config. Left out, both are searched, because
    the serial itself carries no line indicator.
    """
    if sandbox:
        ss, el = simulate(serial, wattage)
    else:
        ss = read_sun_simulator(cfg, serial, line)
        el = read_el(cfg, serial, line)
    outcome, why = propose_outcome(wattage, ss, el)
    degraded = ss["state"] != OK or el["state"] != OK
    out = {
        "pmax": ss.get("pmax"), "params": ss.get("params") or [],
        "wattage": wattage,
        "ss_state": ss["state"], "ss_note": ss["note"],
        "ss_attempts": ss.get("attempts"), "tested_at": ss.get("tested_at"),
        "ss_line": ss.get("line"), "el_line": el.get("line"),
        "fault": ss["state"] == BAD,
        "el": el.get("verdict"), "el_state": el["state"], "el_note": el["note"],
        "el_path": el.get("path"),
        "proposed": outcome, "why": why,
        "degraded": degraded,
        "mode": "provisional" if degraded else "confirmed",
        "sandbox": sandbox,
    }
    # Every measured value, not only Pmax. The FQC screen shows Voc, Isc and
    # Fill factor beside it and they were reaching it as nothing at all -
    # gather() returned the list in `params` but none of the values by name,
    # so the panel read e.voc and found undefined.
    for (k, _lab, _i, _u) in PARAMS_KEYS:
        if k not in out:
            out[k] = ss.get(k)
    return out
