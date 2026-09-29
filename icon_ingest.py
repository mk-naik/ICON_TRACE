"""
ICON TRACE - Stage 5 event recording.

Four things a shift already produces and the system used to throw away the
moment the screen moved on:

    NOT IN MASTER    a serial the Sun Simulator read that is not in the
                      serial master - split at detection into MALFORMED (the
                      text does not even look like a serial - a scanner
                      misfire, likely Cancel) and UNPLANNED (it looks right,
                      genuinely is not planned yet - Incharge plans it with
                      an indent). 5 in one 41-minute shift, nothing written.

    SS SKIP           a serial in the master with an EL image on file, but
                      no Sun Simulator row at all - not a bad reading
                      (icon_evidence already catches that, "failed"), a
                      MISSING one. 4 in that same shift.

    LOOKED UP, NO      an operator scanned a module at FQC and never clicked
    DECISION           Pass, Reject or Discard.

    FTR ANOMALY        icon_evidence.scan_anomalies()'s own junk/failed
                        rows - read live for the FQC screen today, never
                        kept anywhere.

Detection is read-only and returns plain dicts; db.ingest_review_item()
writes them, keyed on (type, raw_id) so re-running the same scan over the
same CSV row or EL file is a no-op, not a duplicate.
"""

import os, datetime, logging, threading, time

import icon_evidence as ev
import icon_clock as clock

log = logging.getLogger("icontrace.ingest")


def _el_stem_serial(stem):
    """The serial an EL filename means ('<SERIAL>' or a recapture
    '<SERIAL>_N'), or None - the same shape read_el()/_el_recapture_n()
    matches against a KNOWN serial, applied here with none in hand yet."""
    stem = (stem or "").strip().upper()
    base = stem
    if "_" in stem:
        head, _, tail = stem.rpartition("_")
        if tail.isdigit():
            base = head
    return base if ev._looks_like_serial(base) else None


def _safe_scandir(path):
    try:
        return list(os.scandir(path))
    except OSError:
        return []


def _el_recent_files(root, days=2):
    """(serial, category, mtime, path) for every EL image filed under the
    most recent `days` date folders - date / shift / category / file, the
    shape Stage 2 confirmed on the real share. Any folder that does not
    match (an odd nesting, an unreadable directory) is skipped, not fatal -
    the point is what CAN be read, same as read_el()."""
    dirs = [e for e in _safe_scandir(root) if e.is_dir()]
    dirs.sort(key=lambda e: e.name, reverse=True)
    for dd in dirs[:days]:
        for shift_e in _safe_scandir(dd.path):
            if not shift_e.is_dir():
                continue
            for cat_e in _safe_scandir(shift_e.path):
                if not cat_e.is_dir():
                    continue
                cat = cat_e.name.strip()
                for f in _safe_scandir(cat_e.path):
                    if not f.is_file():
                        continue
                    serial = _el_stem_serial(os.path.splitext(f.name)[0])
                    if not serial:
                        continue
                    try:
                        mtime = f.stat().st_mtime
                    except OSError:
                        continue
                    yield serial, cat, mtime, f.path


def _archive_path(cfg, ln):
    """The archive destination the live CSV is manually cut and pasted to,
    each shift - reading it too is what makes a scan safe to run at any
    time, not only in a window nothing is being moved."""
    p = (cfg.get("ss_%s_archive_path" % ln.lower()) or "").strip()
    if ln.upper() == "A":
        p = p or (cfg.get("ss_archive_path") or "").strip()
    return p


def _ss_rows(cfg, s):
    """Every row for this source, archive first, then the live path - a row
    moved between polls is read from wherever it now sits, exactly once
    (the caller dedupes on the tester's own timestamp, not the file it came
    from). Live last on purpose: a caller that only wants the newest N
    (scan_not_in_master, a truncating tail slice) must not have the live
    file's own recent rows crowded out by however big the archive is."""
    rows = []
    arc = _archive_path(cfg, s["line"])
    if arc and os.path.exists(arc):
        rows.extend(ev._read_rows(arc))
    if s["ss_path"] and os.path.exists(s["ss_path"]):
        rows.extend(ev._read_rows(s["ss_path"]))
    return rows


def scan_not_in_master(cfg, cur, db, line=None, limit=2000):
    """Every non-calibration SS row whose serial is not in the master,
    split MALFORMED (does not look like a serial at all) vs UNPLANNED (does,
    just is not planned yet)."""
    out = []
    for s in ev.sources(cfg, line):
        rows = _ss_rows(cfg, s)
        if not rows:
            continue
        scol = s["serial_col"]
        for r in rows[-limit:]:
            if len(r) <= scol:
                continue
            sid_raw = r[scol].strip()
            if not sid_raw or ev.is_calibration(sid_raw):
                continue
            at = r[ev.COL_TIME] if len(r) > ev.COL_TIME else ""
            if not ev._looks_like_serial(sid_raw):
                out.append({"kind": "not_in_master_malformed", "serial": sid_raw,
                            "line": s["line"], "at": at})
                continue
            sid = sid_raw.upper()
            if db.find_serial(cur, sid) is None:
                out.append({"kind": "not_in_master_unplanned", "serial": sid,
                            "line": s["line"], "at": at})
    return out


def scan_ss_skip(cfg, cur, db, line=None, days=1):
    """A serial in the master, an EL image on file for it, and no Sun
    Simulator row anywhere in the current CSV - the tester skipped it
    entirely, which a "failed reading" (a row that IS there but invalid)
    never catches."""
    out = []
    for s in ev.sources(cfg, line):
        root = s["el_root"]
        if not root or not os.path.isdir(root):
            continue
        ss_serials = set()
        scol = s["serial_col"]
        for r in _ss_rows(cfg, s):
            if len(r) > scol:
                ss_serials.add(r[scol].strip().upper())
        seen = set()
        for serial, cat, mtime, path in _el_recent_files(root, days=days):
            if serial in seen or serial in ss_serials:
                seen.add(serial)
                continue
            seen.add(serial)
            if db.find_serial(cur, serial) is None:
                continue                     # not_in_master's job, not this one
            out.append({"kind": "ss_skip", "serial": serial, "line": s["line"],
                       "el_path": path, "el_mtime": mtime})
    return out


def scan_looked_up_no_decision(cur, db, store, window_minutes=30):
    """A lookup old enough that it is not simply mid-decision, with no FQC
    record for that serial written since."""
    cutoff = (clock.now() - datetime.timedelta(minutes=window_minutes)
             ).isoformat(timespec="seconds")
    rows = store.rows(cur, "SELECT * FROM fqc_lookup_log WHERE at<=%s "
                           "ORDER BY lookup_id", (cutoff,))
    out = []
    for r in rows:
        decided = store.one(cur, "SELECT 1 FROM fqc_record WHERE serial=%s "
                                 "AND at>=%s", (r["serial"], r["at"]))
        if not decided:
            out.append({"kind": "looked_up_no_decision", "serial": r["serial"],
                       "line": r.get("line"), "lookup_id": r["lookup_id"],
                       "at": r["at"]})
    return out


def scan_ftr_anomalies(cfg, line=None):
    """icon_evidence.scan_anomalies()'s own rows, given a raw_id so they can
    be kept instead of only shown for as long as the FQC screen is open."""
    data = ev.scan_anomalies(cfg, line=line)
    out = []
    for j in data.get("junk") or []:
        out.append({"kind": "ftr_junk", "serial": j.get("id") or "", "at": j.get("at"),
                   "line": j.get("line"), "pmax": j.get("pmax")})
    for f in data.get("failed") or []:
        out.append({"kind": "ftr_failed", "serial": f.get("serial") or "",
                   "at": f.get("at"), "line": f.get("line"), "why": f.get("why")})
    return out


def _raw_id(kind, line, serial, at):
    return "%s|%s|%s|%s" % (kind, line or "", serial, at or "")


def run(cfg, cur, db, store, line=None):
    """One pass over all four sources. Returns {kind: n_new} - how many
    were genuinely NEW this pass, not how many the scan looked at (most
    will already be on file from the last pass, 60 seconds ago).

    not_in_master_unplanned is the one exception to "new": it is one open
    item per SERIAL, not per scan - a module read five times before it is
    planned updates the same item five times (db.ingest_review_item_latest),
    and each time its Sun Simulator reading is saved too (ftr_reading), so
    whichever scan turns out to be the last one before Incharge plans it is
    the one FQC can still use, even if the CSV has moved on by then.
    """
    out = {}

    def take(events, source):
        for e in events:
            kind = e["kind"]
            rid = _raw_id(kind, e.get("line"), e["serial"], e.get("at"))
            new = db.ingest_review_item(cur, kind, e["serial"], rid, source,
                                        line=e.get("line"))
            if new:
                out[kind] = out.get(kind, 0) + 1

    take(scan_ss_skip(cfg, cur, db, line), "el_ingest")
    take(scan_looked_up_no_decision(cur, db, store), "fqc_lookup")
    take(scan_ftr_anomalies(cfg, line), "ftr_scan")

    for e in scan_not_in_master(cfg, cur, db, line):
        kind = e["kind"]
        if kind == "not_in_master_unplanned":
            result = db.ingest_review_item_latest(cur, kind, e["serial"],
                                                  "ss_ingest", line=e.get("line"))
            reading = ev.read_sun_simulator(cfg, e["serial"], e.get("line"))
            if reading.get("state") == ev.OK:
                db.save_ftr_reading(cur, e["serial"], e.get("line"),
                                    reading.get("tested_at"), reading)
            if result == "created":
                out[kind] = out.get(kind, 0) + 1
        else:
            rid = _raw_id(kind, e.get("line"), e["serial"], e.get("at"))
            if db.ingest_review_item(cur, kind, e["serial"], rid, "ss_ingest",
                                     line=e.get("line")):
                out[kind] = out.get(kind, 0) + 1
    return out


def start_background(interval=60):
    """A daemon thread that runs one pass every `interval` seconds.

    Called once, from serve.py - never from app.py, which also loads under
    the test suite and (in dev) Flask's reloader, neither of which should
    have a filesystem poller running on a timer. One failed pass (a share
    unreachable, a malformed row) is logged and skipped, not fatal - the
    next pass 60 seconds later tries again.
    """
    import store, db

    def loop():
        while True:
            try:
                with store.conn() as (cx, cur):
                    cfg = db.get_config(cur)
                    counts = run(cfg, cur, db, store)
                    if counts:
                        log.info("new: %s", counts)
            except Exception:
                log.exception("ingest pass failed")
            time.sleep(interval)

    t = threading.Thread(target=loop, name="icon-ingest", daemon=True)
    t.start()
    return t
