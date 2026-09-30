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

A pass has two halves, and they are kept apart on purpose:

    collect()   reads - the CSV, the EL share, the tester's result files, the
                database - and writes NOTHING. Slow, over the network, and it
                holds no database write lock while it runs.
    apply()     writes what collect() found, briefly, in one transaction.

Reading over a slow or unreachable share used to happen inside a write
transaction, so one stalled share stalled every save in the plant.

It is also QUIET: a pass that finds nothing new writes nothing - not an
INSERT ... DO NOTHING, not a refreshed timestamp. Every write to review_item
tells every open Needs Review window "changed", and the poller used to say so
every minute about rows it had already recorded.

An unplanned module is ONE item per SERIAL, standing for its latest scan, with
its Sun Simulator reading saved beside it (ftr_reading): the CSV is cut each
shift and by the time Incharge plans the serial the row is gone. The reading
is looked for in the CSV and then in the tester's own result file, so a module
whose row was already cut before the poller saw it still gets one.
"""

import os, datetime, logging, threading, time

import icon_evidence as ev
import icon_clock as clock

log = logging.getLogger("icontrace.ingest")

# A module whose reading could not be found anywhere (BAD, or NA on every
# source) is not asked again every minute - just every quarter of an hour.
_NO_READING = {}                 # serial -> time.time() of the last try
_RETRY_AFTER_S = 900
BACKFILL_PER_PASS = 100          # open items with no saved reading, per pass
BACKFILL_BUDGET_S = 8            # ...and never longer than this per pass


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


def _el_day_name(name):
    """The date an EL folder name means, as (y, m, d), or None. The real share
    has both spellings - 30 folders named 2026-09-29 and one named 16-09-2026 -
    and a stray `New folder` nobody dated at all."""
    parts = (name or "").strip().split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    a, b, c = (int(p) for p in parts)
    if len(parts[0]) == 4:
        y, m, d = a, b, c
    else:
        d, m, y = a, b, c
    if not (2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return (y, m, d)


def _el_day_dirs(root, days=2):
    """The newest `days` DATE folders on the EL share, newest first.

    By the date the name means, not by the name. Sorting names put the share's
    stray `New folder` first ('N' > '2'), and the poller asks for one day: it
    took that folder, which holds verdict folders directly and so yielded no
    images at all - scan_ss_skip could never find anything. A folder that is
    not a date is not a day's work and is ignored."""
    dated = []
    for e in _safe_scandir(root):
        if not e.is_dir():
            continue
        key = _el_day_name(e.name)
        if key:
            dated.append((key, e))
    dated.sort(key=lambda p: p[0], reverse=True)
    return [e for _key, e in dated[:days]]


def _el_recent_files(root, days=2):
    """(serial, category, mtime, path) for every EL image filed under the
    most recent `days` date folders - date / shift / category / file, the
    shape Stage 2 confirmed on the real share. Any folder that does not
    match (an odd nesting, an unreadable directory) is skipped, not fatal -
    the point is what CAN be read, same as read_el()."""
    for dd in _el_day_dirs(root, days):
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
    just is not planned yet). One event per ROW - collect() keeps the latest
    per serial."""
    out = []
    known = {}                       # serial -> in master? (one look per serial)
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
            if sid not in known:
                known[sid] = db.find_serial(cur, sid) is not None
            if not known[sid]:
                out.append({"kind": "not_in_master_unplanned", "serial": sid,
                            "line": s["line"], "at": at})
    return out


SS_SKIP_CONFIRM_PER_PASS = 150    # result files asked about, per pass
SS_SKIP_BUDGET_S = 5              # ...and never longer than this


def scan_ss_skip(cfg, cur, db, line=None, days=2):
    """A serial in the master, an EL image on file for it, and the Sun
    Simulator has NO reading for it anywhere - the tester was skipped, which a
    "failed reading" (a row that IS there but invalid) never catches.

    "Anywhere" is the point, and it is why this used to be unusable. The live
    CSV is cut every shift and no archive path is configured, so "not in the
    CSV" means nothing an hour later: every module of the previous shift looked
    skipped. Each candidate is now confirmed against the tester's OWN result
    file (one per module, kept per day) before it is flagged - measured on the
    real share: 15 candidates, all 15 had a result file, so nothing false was
    raised, at 6 ms each.

    If the result files cannot be read at all, nothing is flagged: with the CSV
    cut there would be no way to tell a skipped module from one whose row has
    simply been moved away, and a flood of false skips is worse than a quiet
    detector."""
    out = []
    budget = time.time() + SS_SKIP_BUDGET_S
    asked = 0
    for s in ev.sources(cfg, line):
        root = s["el_root"]
        if not root or not os.path.isdir(root):
            continue
        # can the claim be checked? either the archive holds the cut rows, or
        # the tester's per-module result files are readable
        xml_root = s.get("xml_root")
        can_confirm = bool(xml_root and os.path.isdir(xml_root))
        arc = _archive_path(cfg, s["line"])
        if not can_confirm and not (arc and os.path.exists(arc)):
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
            if can_confirm:
                if asked >= SS_SKIP_CONFIRM_PER_PASS or time.time() > budget:
                    break                    # the rest wait for the next pass
                asked += 1
                if ev._xml_row(s, serial) is not None:
                    continue                 # tested after all: its row was cut
            out.append({"kind": "ss_skip", "serial": serial, "line": s["line"],
                       "el_path": path, "el_mtime": mtime})
    return out


def scan_looked_up_no_decision(cur, db, store, window_minutes=30,
                               look_back_days=3):
    """A lookup old enough that it is not simply mid-decision, with no FQC
    record for that serial written since. Only the last few days are asked
    about: this used to walk every lookup ever logged, each with a scan of
    every decision ever made, on every pass."""
    now = clock.now()
    cutoff = (now - datetime.timedelta(minutes=window_minutes)
              ).isoformat(timespec="seconds")
    since = (now - datetime.timedelta(days=look_back_days)
             ).isoformat(timespec="seconds")
    rows = store.rows(cur, "SELECT * FROM fqc_lookup_log WHERE at<=%s AND "
                           "at>=%s ORDER BY lookup_id", (cutoff, since))
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


def _reading_for(cfg, serial, line):
    """The Sun Simulator reading for one serial - the CSV, then the tester's
    own result file - or None when there is no valid one."""
    r = ev.read_sun_simulator(cfg, serial, line)
    return r if r.get("state") == ev.OK else None


def collect(cfg, cur, db, store, line=None, backfill=True):
    """Everything a pass reads, and nothing it writes."""
    coll = {"ss_skip": scan_ss_skip(cfg, cur, db, line),
            "looked_up": scan_looked_up_no_decision(cur, db, store),
            "ftr": scan_ftr_anomalies(cfg, line),
            "malformed": [], "unplanned": {}, "readings": {}}

    # one unplanned event per SERIAL - its latest scan
    for e in scan_not_in_master(cfg, cur, db, line):
        if e["kind"] == "not_in_master_malformed":
            coll["malformed"].append(e)
            continue
        old = coll["unplanned"].get(e["serial"])
        if old is None or (e.get("at") or "") >= (old.get("at") or ""):
            coll["unplanned"][e["serial"]] = e

    # Their Sun Simulator readings: saved once, refreshed only by a newer test.
    # Read only where the one on file is older than the scan just seen.
    saved = db.ftr_saved_times(cur, list(coll["unplanned"]))
    for serial, e in coll["unplanned"].items():
        if saved.get(serial, "") >= (e.get("at") or ""):
            continue
        r = _reading_for(cfg, serial, e.get("line"))
        if r:
            coll["readings"][serial] = r

    # And the ones already open with NO reading - flagged before readings were
    # kept, or whose CSV row was cut before a pass saw it. Bounded per pass:
    # the tester's result file is asked for each, over the network.
    if backfill:
        now = time.time()
        budget = now + BACKFILL_BUDGET_S
        cand = store.rows(
            cur, "SELECT r.serial, r.line FROM review_item r WHERE "
                 "r.type='not_in_master_unplanned' AND r.status='open' AND "
                 "NOT EXISTS (SELECT 1 FROM ftr_reading f WHERE "
                 "f.serial=r.serial) ORDER BY r.review_id DESC LIMIT %s",
            (BACKFILL_PER_PASS * 4,))
        done = 0
        for c in cand:
            serial = c["serial"]
            if serial in coll["readings"]:
                continue
            if now - _NO_READING.get(serial, 0) < _RETRY_AFTER_S:
                continue
            if done >= BACKFILL_PER_PASS or time.time() > budget:
                break
            done += 1
            r = _reading_for(cfg, serial, c.get("line"))
            if r:
                coll["readings"][serial] = r
                _NO_READING.pop(serial, None)
            else:
                _NO_READING[serial] = time.time()
    return coll


def apply(cur, db, coll):
    """Write what collect() found - only what is new. Returns {kind: n_new}:
    how many were genuinely NEW this pass, not how many the scan looked at
    (most were on file from the last pass, a minute ago)."""
    out = {}

    def bump(k):
        out[k] = out.get(k, 0) + 1

    for key, source in (("ss_skip", "el_ingest"), ("looked_up", "fqc_lookup"),
                        ("ftr", "ftr_scan"), ("malformed", "ss_ingest")):
        for e in coll[key]:
            k = e["kind"]
            rid = _raw_id(k, e.get("line"), e["serial"], e.get("at"))
            if db.ingest_review_item(cur, k, e["serial"], rid, source,
                                     line=e.get("line"), event_at=e.get("at")):
                bump(k)

    # one item per serial, standing for its latest scan
    for serial, e in coll["unplanned"].items():
        if db.find_serial(cur, serial) is not None:
            continue                        # planned since collect() looked
        res = db.upsert_unplanned_item(cur, serial, "ss_ingest",
                                       line=e.get("line"), event_at=e.get("at"))
        if res in ("created", "reopened"):
            bump("not_in_master_unplanned")

    for serial, r in coll["readings"].items():
        db.save_ftr_reading_if_newer(cur, serial, r.get("line"),
                                     r.get("tested_at"), r)

    closed = db.close_planned_items(cur)     # planned by any route since
    if closed:
        out["planned_closed"] = closed
    db.prune_lookup_log(cur)
    return out


def run(cfg, cur, db, store, line=None):
    """One pass on the connection given (tests, and anything that already
    holds one). The poller uses run_pass(), which keeps the reading and the
    writing in separate, short transactions."""
    return apply(cur, db, collect(cfg, cur, db, store, line))


def run_pass():
    """One pass as the poller runs it: read (no write lock held while files
    and shares are read), then write (brief)."""
    import store, db
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
        coll = collect(cfg, cur, db, store)
    with store.conn() as (cx, cur):
        return apply(cur, db, coll)


def start_background(interval=60):
    """A daemon thread that runs one pass every `interval` seconds.

    Called once, from serve.py - never from app.py, which also loads under
    the test suite and (in dev) Flask's reloader, neither of which should
    have a filesystem poller running on a timer. One failed pass (a share
    unreachable, a malformed row) is logged and skipped, not fatal - the
    next pass 60 seconds later tries again.

    The poller is the ONLY thing that runs a pass. Opening Needs Review used
    to run one too, inside the request: two windows on that screen then
    re-ran it for each other without end, each pass telling the other
    "changed".
    """
    def loop():
        while True:
            try:
                counts = run_pass()
                if counts:
                    log.info("new: %s", counts)
            except Exception:
                log.exception("ingest pass failed")
            time.sleep(interval)

    t = threading.Thread(target=loop, name="icon-ingest", daemon=True)
    t.start()
    return t
