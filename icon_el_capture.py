"""
ICON TRACE - the Pre-EL, Post EL and Final EL images, indexed for the module
journey and EL Stations.

Unit-2 has three EL stations. FQC's own (Settings: Final EL (FQC) image root folder) is
read by icon_evidence when FQC looks a serial up. The other two are never
looked up - nobody types a serial at either:

    Pre-EL     before lamination; it scans the back label - two machines a
               line, a primary and a secondary beside it
    Post EL    after lamination

so the server finds their images itself, by walking the folders every minute
as icon_ingest does for the FQC EL, and keeps one row per image in el_capture.
Search & Trace reads that table, never the shares.

Final EL IS FQC's own EL (17 Oct 2026, the EL Defect Master: "one station, one
map"): its folders are FQC's - Settings' Final EL (FQC) image root folder, per line - and
the poller indexes them too, as the station 'final_el', so EL Stations and the
analysis read every station's images from one table. FQC still reads a serial's
image off the share when it looks it up (icon_evidence.read_el); the index is
not FQC's evidence. One folder is one machine (Settings refuses FQC's folder as
a Pre-EL or Post EL one), so nothing is indexed twice.

Both stations file an image the way the FQC EL does:

    <root>\\<date>\\<shift>\\<verdict folder>\\<serial>.jpg   re-shot: <serial>_N.jpg

Checked on the real Pre-EL share of Line B (15 Oct 2026): 2,437 images in the
newest two date folders, 42 of them one folder deeper (Lead Open\\Cross), 7
still waiting in a shift folder, 18 whose names are no serial at all. A module
shot again was filed again under its OWN name in another verdict folder (none
was named _N) - so the latest capture is told by its time as well as its
number. The verdict is the folder's name: a person's reading, not a reject.

A pass keeps its reading and its writing apart, like icon_ingest's: the shares
are walked with no database connection open, and what is new is written
briefly afterwards. A pass that finds nothing new writes nothing. A row is
never changed or deleted - an image moved away, or a share switched off,
leaves the record of what was captured.
"""

import os, re, time, logging, datetime, threading

import icon_clock as clock
import icon_defects
import icon_evidence as ev
import icon_ingest

log = logging.getLogger("icontrace.el_capture")

# (station, its name on screen), in process order - the journey's order too
STATIONS = (("pre_el", "Pre-EL"), ("post_el", "Post EL"), ("final_el", "Final EL"))
LABEL = dict(STATIONS)

# Every EL folder the server reads: (settings prefix, station, unit, its name).
# Each line has TWO Pre-EL machines side by side (Mukesh, 16 Oct 2026): the
# primary takes the line's flow and the secondary takes it when the primary
# is busy or down - and an NG module back from rework goes to the OTHER one.
# So one module's Pre-EL images can sit on both machines, named by each on its
# own, and only their times put them in order. Post EL has one machine a line.
SOURCES = (("pre_el", "pre_el", 1, "Pre-EL primary"),
           ("pre_el2", "pre_el", 2, "Pre-EL secondary"),
           ("post_el", "post_el", 1, "Post EL"))
# ... and Final EL, one machine a line, whose folders are FQC's (roots()), not
# settings of their own
FINAL_LABEL = "Final EL"
UNIT_NAME = {1: "primary", 2: "secondary"}

DAYS = 2                 # the newest date folders walked, as icon_ingest's SS skip
MISS_TTL_S = 3600        # a name that is no serial is asked about again after this
_NOT_SERIAL = {}         # name -> time.time() it was found not to be in the master
_DOWN = set()            # (station, folder) unreachable - logged once per outage
_CHUNK = 500             # names per IN (...) list


# ---- what an image says (Mukesh, 16 Oct 2026) ------------------------------
#
# OK is Pass; any other folder is NG. At Pre-EL an NG module goes for rework
# and comes back to Pre-EL - NG, rework, Pre-EL again, until it passes. After
# lamination a module cannot go back to the pre-lamination process, so an NG
# at Post EL takes it off the line to Quality, who decide (Mukesh, 16 Oct: the
# FQC way - a referral, not "rejected"): no rework, and a later image does not
# undo the NG.

_PASS = re.compile(r"^(ok|pass)$", re.I)        # the FQC screen's own test


def is_pass(verdict):
    return bool(_PASS.match((verdict or "").strip()))


def images(rows):
    """One serial's el_capture rows at ONE station as its images, in the order
    they were taken: by TIME, across both Pre-EL machines ("here time is
    crucial" - an NG at one is re-imaged at the other after rework, and each
    machine numbers its own re-shots). The order is only as good as the two EL
    PCs' clocks. An image re-filed under another verdict - same machine, same
    re-shot number, same time: one image, moved - is one image, and the filing
    seen last is the one that stands."""
    out = []
    for r in sorted(rows, key=lambda r: (r["file_time"] or "", r["recapture"] or 0,
                                         r["seen_at"] or "", r["capture_id"])):
        if out and out[-1].get("unit", 1) == r.get("unit", 1) \
                and (out[-1]["recapture"] or 0) == (r["recapture"] or 0) \
                and out[-1]["file_time"] == r["file_time"]:
            out[-1] = r
        else:
            out.append(r)
    return out


# a module's state at a station, and how a person reads it
STATUS_LABEL = {("pre_el", "pass"): "Pass", ("pre_el", "reworked"): "Pass after rework",
                ("pre_el", "in_rework"): "In rework",
                ("pre_el", "machine"): "Passed by the machine",
                ("post_el", "pass"): "Pass", ("post_el", "ng"): "NG",
                ("final_el", "pass"): "Pass", ("final_el", "ng"): "NG",
                ("final_el", "machine"): "Passed by the machine"}

# Pre-EL and Final EL must run in NORMAL mode, never continuous (Mukesh, 17 Oct
# 2026, the EL Defect Master): Pre-EL because a module can be reworked and a
# person must decide, Final EL because it is the end of the process. Post EL may
# run continuous. So at these two an image the machine passed by itself is no
# decision - it is left out of what a module's images add up to (a module with
# nothing else there is 'machine': passed by the machine, counted apart from
# the figures) - and a run of them is an equipment-configuration fault, an
# alert naming the machine (continuous_alerts).
NORMAL_ONLY = ("pre_el", "final_el")


def summary(station, rows):
    """What one serial's images at one station add up to, or None for none.

    Pre-EL: 'pass' (never NG), 'reworked' (NG at least once, its last image
    OK) or 'in_rework' (its last image NG). Post EL: 'pass', or 'ng' the
    moment any image is NG - it is Quality's to decide then, not a later
    image's. Final EL: what its NEWEST image says, as FQC reads it
    (icon_evidence.read_el takes the newest) - the decision is FQC's. A module
    counts on the factory day and shift of its FIRST image at the station.

    At Pre-EL and Final EL (NORMAL_ONLY) an image a machine in continuous mode
    passed by itself is left out of the status - nobody decided it; a module
    with only such images there is 'machine'."""
    imgs = images(rows)
    if not imgs:
        return None
    judged = imgs
    if station in NORMAL_ONLY:
        judged = [i for i in imgs if i.get("mode") != "continuous"]
    ngs = [i for i in judged if not is_pass(i["verdict"])]
    if not judged:
        status, reason = "machine", None
    elif station == "pre_el":
        status = ("pass" if not ngs else
                  "reworked" if is_pass(judged[-1]["verdict"]) else "in_rework")
        reason = ngs[-1]["verdict"] if ngs else None
    elif station == "final_el":
        status = "pass" if is_pass(judged[-1]["verdict"]) else "ng"
        reason = judged[-1]["verdict"] if status == "ng" else None
    else:
        status = "ng" if ngs else "pass"
        reason = ngs[0]["verdict"] if ngs else None
    return {"status": status, "label": STATUS_LABEL[(station, status)],
            "reason": reason, "images": len(imgs),
            "reworks": len(ngs) if station == "pre_el" else 0,
            "first_at": imgs[0]["file_time"], "last_at": imgs[-1]["file_time"],
            "lines": sorted({i["line"] for i in imgs if i["line"]}),
            "units": sorted({i.get("unit", 1) for i in imgs}),
            # passed by the machine in continuous mode - no person decided these
            "continuous": sum(1 for i in imgs if i.get("mode") == "continuous")}


# ---- the EL PCs' clocks --------------------------------------------------------
#
# Images are put in order by their time, and that time is the EL PC's own clock -
# two PCs on Pre-EL - never the server's. The poller records a file within about a
# minute of its filing, so for an image recorded as it came (not in a machine's
# FIRST pass, which takes two days' backlog at once), seen_at - file_time is the
# filing delay plus that PC's lag behind the server, and its SMALLEST value over a
# day is the lag itself, near enough. Below a minute negative: the PC's clock is
# AHEAD. Over ten minutes: most likely BEHIND (or every image filed late).
CLOCK_WINDOW_H = 24
CLOCK_AHEAD_S = -60
CLOCK_BEHIND_S = 600


def clocks(cur, now=None):
    """{(station, unit, line): {"gap_s", "n", "flag", "minutes"}} for every machine
    with images recorded as they came in the last day; a machine with none (only
    its first pass so far) is not measured, and not in the answer."""
    now = now or clock.now()
    since = (now - datetime.timedelta(hours=CLOCK_WINDOW_H)).isoformat(timespec="seconds")
    cur.execute("SELECT station, unit, line, MIN(seen_at) AS first FROM el_capture "
                "GROUP BY station, unit, line")
    first = {(r["station"], r["unit"], r["line"]): r["first"] for r in cur.fetchall()}
    cur.execute("SELECT station, unit, line, file_time, seen_at, mode FROM el_capture "
                "WHERE seen_at >= %s", (since,))
    gaps = {}
    for r in cur.fetchall():
        key = (r["station"], r["unit"], r["line"])
        if r["seen_at"] <= first.get(key, ""):
            continue                       # that machine's first pass: a backlog
        if r["mode"] == "continuous":
            # recorded once CONTINUOUS_AFTER_S old by the PC's own clock - the gap
            # is that wait, whatever the clock says, so it measures nothing
            continue
        try:
            g = (datetime.datetime.fromisoformat(r["seen_at"]) -
                 datetime.datetime.fromisoformat(r["file_time"])).total_seconds()
        except (TypeError, ValueError):
            continue
        gaps.setdefault(key, []).append(g)
    out = {}
    for key, gs in gaps.items():
        g = min(gs)
        out[key] = {"gap_s": int(g), "n": len(gs),
                    "flag": ("ahead" if g < CLOCK_AHEAD_S else
                             "behind" if g > CLOCK_BEHIND_S else None),
                    "minutes": int(round(abs(g) / 60.0))}
    return out


CONTINUOUS_RUN = 5       # images in a row left by the machine: continuous, not a slip


def continuous_alerts(cur, now=None):
    """[{station, unit, line, images, run, first_at, last_at}] - each Pre-EL or
    Final EL machine that ran in continuous mode in the last day.

    In normal mode the machine waits for the operator, so at most the one image
    being decided sits in the shift folder; one left there now and then is an
    image somebody did not file (one at a time, on the real shares, 11-17 Oct).
    In continuous mode every image stays (Post EL: runs of thousands). So
    CONTINUOUS_RUN of a machine's images in a row, by their time, all left by
    the machine - an operator's later filing of one taking it out of the run -
    is the machine running continuous where a person must decide."""
    now = now or clock.now()
    since = (now - datetime.timedelta(hours=CLOCK_WINDOW_H)).isoformat(timespec="seconds")
    cur.execute("SELECT station, unit, line, serial, recapture, file_time, mode "
                "FROM el_capture WHERE station IN (%s, %s) AND seen_at >= %s "
                "ORDER BY file_time, capture_id", NORMAL_ONLY + (since,))
    by = {}
    for r in cur.fetchall():
        by.setdefault((r["station"], r["unit"], r["line"]), []).append(r)
    out = []
    for (station, unit, line), rs in sorted(by.items(), key=str):
        filed = {(r["serial"], r["recapture"], r["file_time"])
                 for r in rs if r["mode"] != "continuous"}
        run, best, start, span, n = 0, 0, None, None, 0
        for r in rs:
            if r["mode"] == "continuous" and \
                    (r["serial"], r["recapture"], r["file_time"]) not in filed:
                n += 1
                run += 1
                start = r["file_time"] if run == 1 else start
                if run > best:
                    best, span = run, (start, r["file_time"])
            elif r["mode"] != "continuous":
                run = 0
        if best >= CONTINUOUS_RUN:
            out.append({"station": station, "unit": unit, "line": line, "images": n,
                        "run": best, "first_at": span[0], "last_at": span[1]})
    return out


def continuous_text(a):
    """What one continuous-mode alert says, in words."""
    def t(s):
        return (s or "")[8:10] + "-" + (s or "")[5:7] + " " + (s or "")[11:16]
    return ("%s%s ran in CONTINUOUS mode: %d images in a row (%s to %s) were passed by "
            "the machine with nobody deciding - %d in the last day. %s must run in normal "
            "mode; switch the machine back. These images are not counted in its figures."
            % (source_label(a["station"], a["unit"]),
               ", Line %s" % a["line"] if a["line"] else "", a["run"], t(a["first_at"]),
               t(a["last_at"]), a["images"], LABEL[a["station"]]))


def clock_text(c):
    """What one machine's clock reading says, in words."""
    if not c:
        return "Clock not measured yet - it is, from the images recorded as they come."
    if c["flag"] == "ahead":
        return ("Clock about %d min AHEAD of the server - its images are put in order by "
                "their time, so fix the EL PC's clock." % max(1, c["minutes"]))
    if c["flag"] == "behind":
        return ("Clock about %d min BEHIND the server (or every image is filed late) - "
                "its images are put in order by their time, so check the EL PC's clock."
                % c["minutes"])
    return "Clock in step with the server (images reach the index within %d min)." % \
        max(1, c["minutes"])


def folder_key(path):
    """One spelling of a folder, for telling whether two settings name the same
    one: case, slash style and a trailing slash ignored. '' when blank."""
    return (path or "").strip().replace("/", "\\").rstrip("\\").lower()


def roots(cfg):
    """(station, unit, line, folder) for every configured EL folder (SOURCES),
    then Final EL's - FQC's own EL folder of each line, as FQC reads it
    (icon_evidence.sources: Line A falls back to the single-line el_root).

    One folder set for the same machine on BOTH lines is one machine serving
    both. It is walked once, and its images carry no line (None): an image's
    line is what the folder says, never guessed from its serial."""
    pairs = []
    for prefix, station, unit, _label in SOURCES:
        pairs.append((station, unit, (cfg.get("%s_a_root" % prefix) or "").strip(),
                      (cfg.get("%s_b_root" % prefix) or "").strip()))
    final = {s["line"]: s["el_root"] for s in ev.sources(cfg) if s.get("el_root")}
    pairs.append(("final_el", 1, final.get("A", ""), final.get("B", "")))
    out = []
    for station, unit, a, b in pairs:
        if a and b and folder_key(a) == folder_key(b):
            out.append((station, unit, None, a))
            continue
        for line, root in (("A", a), ("B", b)):
            if root:
                out.append((station, unit, line, root))
    return out


def source_label(station, unit):
    if station == "final_el":
        return FINAL_LABEL
    return next(lab for _p, st, u, lab in SOURCES if st == station and u == unit)


def _walk(day_dir):
    """(path, mtime, depth) for every file under one date folder, at any depth.
    Depth 0 is a file straight in the date folder, 1 in a shift folder, 2 in a
    verdict folder, 3 in a verdict's own sub-folder (Lead Open\\Cross). A folder
    that cannot be read is skipped, not the walk. DirEntry.stat() costs nothing
    on Windows: the listing carries it."""
    stack = [(day_dir, 0)]
    while stack:
        here, depth = stack.pop()
        try:
            entries = list(os.scandir(here))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append((e.path, depth + 1))
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                mtime = e.stat().st_mtime
            except OSError:
                continue
            yield e.path, mtime, depth


def _filed(path, depth):
    """Has the EL operator filed this image under a verdict yet?

    ev._unfiled() is the FQC screen's rule and it is asked first. It finds the
    date folder by its NAME and knows only the 2026-09-29 spelling, so under a
    folder named 16-09-2026 (the FQC share has one) an image still lying in its
    shift folder would read the shift's name, 早班, as its verdict. The walk
    knows where the date folder is, so the same rule is applied by position as
    well: straight in the date folder is not filed; straight in the folder
    under it is filed only when that folder is OK or a category the defect list
    knows (a tree with no shift level) - _unfiled's own test."""
    if ev._unfiled(path) or depth == 0:
        return False
    if depth == 1:
        key = icon_defects.normalize(os.path.basename(os.path.dirname(path)))
        return key == "ok" or key in icon_defects.FOLDER_MAP
    # a copy of a shift folder somewhere deeper (New folder\晚班\x.jpg) is not
    # filed until its image is under a reason below that shift folder
    return icon_defects.verdict_from(_below_day(path, depth)) is not None


def _below_day(path, depth):
    """The folders between the date folder and the file - `depth` of them."""
    return os.path.normpath(path).split(os.sep)[:-1][-depth:] if depth else []


def verdict_of(path, depth):
    """The reason an image is filed under: the folder it sits in - and, when it
    sits one level deeper, the folders below the shift folder joined with '/'.

    The EL software names a verdict folder from its defect list, and a name
    with a '/' in it ('Lead Open/Cross', 'Cell issue/ribbon bold' - the
    machine's own list, Mukesh's photo, 17 Oct 2026) is written by Windows as a
    folder inside a folder. The leaf alone ('Cross', 'ribbon bold') is half the
    name: 578 + 391 images a week on the Final EL, 108 + 59 on Pre-EL Line B
    were recorded that way. Each part is trimmed (' Cross' is on disk). The shift
    folder is found by its name (icon_defects.verdict_from): a copy of a shift
    folder in a 'New folder' is read below it, not as '晚班/OK'."""
    return icon_defects.verdict_from(_below_day(path, depth)) or "OK"


def _reachable(station, unit, line, root):
    """Is the folder there? An unreachable one is logged when it goes, once,
    and when it comes back - not every minute in between."""
    key = (station, unit, folder_key(root))
    ok = os.path.isdir(root)
    where = "%s%s folder %s" % (source_label(station, unit),
                                " Line %s" % line if line else "", root)
    if not ok and key not in _DOWN:
        _DOWN.add(key)
        log.warning("%s cannot be read - skipped until it answers", where)
    elif ok and key in _DOWN:
        _DOWN.discard(key)
        log.info("%s answers again", where)
    return ok


def _file_time(mtime):
    """The file's modified time - the EL PC's clock - in clock.stamp()'s form."""
    return (datetime.datetime.fromtimestamp(mtime, clock.IST)
            .replace(tzinfo=None).isoformat(timespec="seconds"))


# ---- continuous mode (Mukesh, 17 Oct 2026) -------------------------------------
#
# Every EL machine runs in one of two modes. NORMAL: it waits for the operator's
# decision on each module, and the image is filed under its verdict folder - so
# at most the one image being decided sits in the shift folder (checked on the
# real shares: one, on each normal machine). CONTINUOUS: it does not wait - every
# module is passed by the machine itself, no verdict folder is ever made, and
# every image stays in the shift folder (Post EL, both lines, 17 Oct: about
# 1,000 a shift). So an image still in its shift folder this long after it was
# taken is a continuous-mode capture: recorded as OK, marked 'continuous' - no
# person decided it. Should an operator file it under a verdict later, that
# filing is the image's and stands (images(): same machine, number and time).
CONTINUOUS_AFTER_S = 300


def scan(cfg, now=None):
    """Every image the EL operator has filed under a verdict - and every image a
    machine in continuous mode left in its shift folder - in the newest two date
    folders of each configured Pre-EL, Post EL and Final EL folder, read from the
    shares alone, no database. A folder that cannot be read is skipped; the others are
    still walked."""
    now = time.time() if now is None else now
    out = []
    for station, unit, line, root in roots(cfg):
        if not _reachable(station, unit, line, root):
            continue
        for day in icon_ingest._el_day_dirs(root, DAYS):
            for path, mtime, depth in _walk(day.path):
                if _filed(path, depth):
                    verdict, mode = verdict_of(path, depth), None
                elif (depth == 1 or os.path.basename(os.path.dirname(path)).strip()
                      in icon_defects.SHIFT_FOLDERS) and now - mtime >= CONTINUOUS_AFTER_S:
                    verdict, mode = "OK", "continuous"
                else:
                    continue          # being decided now; a later pass has it
                out.append({
                    "station": station, "unit": unit, "line": line,
                    "path": os.path.normpath(path),
                    "stem": os.path.splitext(os.path.basename(path))[0],
                    "verdict": verdict, "mode": mode,
                    "file_time": _file_time(mtime)})
    return out


def _readings(stem):
    """What serial a file name can mean, as (serial, recapture), best first.

    A re-shot is <serial>_N. An ICON serial never contains '_', but a custom
    one may end in _digits, so the whole name is tried before the _N is taken
    off; an ICON-shaped reading wins outright, needing no lookup."""
    name = (stem or "").strip().upper()
    if not name:
        return []
    out = [(name, 0)]
    head, sep, tail = name.rpartition("_")
    if sep and head.strip() and tail.isdigit():
        out.append((head.strip(), int(tail)))
    shaped = [r for r in out if ev._looks_like_serial(r[0])]
    return shaped[:1] or out


def _in_master(cur, names):
    """Which of these names are serials in the master: one lookup a pass. A
    name found not to be one is remembered for an hour, so the junk a scanner
    leaves on a share ('        2A1522067', '0000') is not asked about every
    minute - and a custom serial loaded later is still found within the hour."""
    now = time.time()
    for k in [k for k, t in _NOT_SERIAL.items() if now - t >= MISS_TTL_S]:
        del _NOT_SERIAL[k]
    ask = sorted({n for n in names if n not in _NOT_SERIAL})
    found = set()
    for i in range(0, len(ask), _CHUNK):
        part = ask[i:i + _CHUNK]
        cur.execute("SELECT DISTINCT serial FROM serial WHERE serial IN (%s)"
                    % ",".join(["%s"] * len(part)), part)
        found.update(r["serial"] for r in cur.fetchall())
    for n in ask:
        if n not in found:
            _NOT_SERIAL[n] = now
    return found


def _recorded(cur, sql, station, keys):
    """The rows of `sql` (... IN (%s)) for one station, asked in chunks."""
    out = []
    keys = sorted(keys)
    for i in range(0, len(keys), _CHUNK):
        part = keys[i:i + _CHUNK]
        cur.execute(sql % ",".join(["%s"] * len(part)), [station] + part)
        out.extend(cur.fetchall())
    return out


def pick_new(cur, files):
    """The files scan() found that are a serial's image and not on record yet.
    Reads only.

    A file counts when its name, less any _N, looks like a serial or is a serial
    in the master (a custom one). One image is one capture however it is
    reached: a file whose station, machine, serial, re-shot number, verdict and
    time are already recorded is that capture again - the folder's spelling
    changed in Settings, or the image was moved to another shift folder under
    the same verdict - and is not recorded twice."""
    out = []
    for station, _label in STATIONS:
        mine = {}
        for f in files:
            if f["station"] == station:
                mine.setdefault(f["path"].lower(), f)  # one folder, two lines: once
        if not mine:
            continue
        known = {r["path"].lower() for r in _recorded(
            cur, "SELECT path FROM el_capture WHERE station=%%s AND path IN (%s)",
            station, [f["path"] for f in mine.values()])}
        fresh = [f for k, f in mine.items() if k not in known]
        if not fresh:
            continue

        ask = {n for f in fresh for n, _r in _readings(f["stem"])
               if not ev._looks_like_serial(n)}
        master = _in_master(cur, ask) if ask else set()
        hits = []
        for f in fresh:
            for serial, n in _readings(f["stem"]):
                if ev._looks_like_serial(serial) or serial in master:
                    hits.append(dict(f, serial=serial, recapture=n))
                    break
        if not hits:
            continue

        same = {(r["unit"], r["serial"], r["recapture"], r["verdict"], r["file_time"])
                for r in _recorded(
                    cur, "SELECT unit, serial, recapture, verdict, file_time FROM "
                         "el_capture WHERE station=%%s AND serial IN (%s)",
                    station, {h["serial"] for h in hits})}
        for h in sorted(hits, key=lambda h: (h["file_time"], h["path"])):
            ident = (h["unit"], h["serial"], h["recapture"], h["verdict"], h["file_time"])
            if ident in same:
                continue
            same.add(ident)
            out.append(h)
    return out


REVIEW_TYPE = "post_el_ng"


def apply(cur, rows):
    """Write what pick_new() found - each row checked absent first, so a pass
    with nothing new writes nothing at all (db.ingest_review_item's rule).

    An NG at Post EL also raises a Needs Review item (Mukesh, 16 Oct 2026):
    after lamination the module cannot be reworked, so it is taken off the line
    and Quality decide. One per module - raw_id is the serial - so a second NG
    image of it raises nothing more, and neither does a later OK.
    Returns {station: rows written, 'post_el_ng': items raised}."""
    import db
    out = {}
    seen = clock.stamp()
    for r in rows:
        cur.execute(
            "INSERT INTO el_capture (station, unit, line, serial, recapture, verdict, "
            "path, file_time, seen_at, mode) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (station, path) DO NOTHING",
            (r["station"], r["unit"], r["line"], r["serial"], r["recapture"],
             r["verdict"], r["path"], r["file_time"], seen, r.get("mode")))
        if not cur.rowcount:
            continue
        out[r["station"]] = out.get(r["station"], 0) + 1
        if r["station"] == "post_el" and not is_pass(r["verdict"]) and \
                db.ingest_review_item(cur, REVIEW_TYPE, r["serial"],
                                      "%s|%s" % (REVIEW_TYPE, r["serial"]),
                                      "el_capture", line=r["line"],
                                      event_at=r["file_time"]):
            out[REVIEW_TYPE] = out.get(REVIEW_TYPE, 0) + 1
    return out


def run(cfg, cur, now=None):
    """One pass on the connection given (tests). The poller uses run_pass(),
    which reads the shares with no connection open."""
    return apply(cur, pick_new(cur, scan(cfg, now)))


LOG_NAMES = 10           # serials named per station in the log line


def named(rows, limit=LOG_NAMES):
    """'Pre-EL: ICON...0201 OK (A), ICON...0131 Cell Crack (A)' - the serials
    a pass recorded, so the log says WHICH, not only how many (Mukesh, 16 Oct:
    "which are those, how can I see it?")."""
    out = []
    for station, label in STATIONS:
        mine = [r for r in rows if r["station"] == station]
        if not mine:
            continue
        def where(r):
            bits = ([r["line"]] if r["line"] else []) + \
                   (["secondary"] if r.get("unit") == 2 else [])
            return " (%s)" % ", ".join(bits) if bits else ""
        shown = ", ".join("%s %s%s%s" % (r["serial"], r["verdict"],
                                         " (continuous)" if r.get("mode") else "", where(r))
                          for r in mine[:limit])
        more = len(mine) - limit
        out.append("%s: %s%s" % (label, shown, " (+%d more)" % more if more > 0 else ""))
    return "; ".join(out)


def run_pass():
    """One pass as the poller runs it: the settings, then the shares with no
    database connection held, then a short write of what is new - logged by
    name."""
    import store, db
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    files = scan(cfg)
    if not files:
        return {}
    with store.conn() as (cx, cur):
        new = pick_new(cur, files)
        counts = apply(cur, new)
    if counts:
        log.info("new images: %s - %s", counts, named(new))
        # Pre-EL and Final EL must run in normal mode: say so in the log the
        # moment a pass records a run of images the machine passed by itself
        machines = {}
        for r in new:
            if r["station"] in NORMAL_ONLY and r.get("mode") == "continuous":
                k = (r["station"], r["unit"], r["line"])
                machines[k] = machines.get(k, 0) + 1
        for (station, unit, line), n in sorted(machines.items(), key=str):
            if n >= CONTINUOUS_RUN:
                log.warning("%s%s: %d images passed by the machine in continuous mode - "
                            "%s must run in normal mode", source_label(station, unit),
                            " Line %s" % line if line else "", n, LABEL[station])
    return counts


def start_background(interval=60):
    """A daemon thread of its own, one pass every `interval` seconds, started
    from serve.py beside icon_ingest's - never from app.py, which also loads
    under the tests. Its own thread so that a Pre-EL or Post EL PC switched off
    (Windows takes 42 s to give up on a host that does not answer, measured)
    never holds up the FQC ingest. A failed pass is logged; the next one, a
    minute later, tries again."""
    def loop():
        while True:
            try:
                run_pass()                     # logs what it recorded, by name
            except Exception:
                log.exception("EL capture pass failed")
            time.sleep(interval)

    t = threading.Thread(target=loop, name="icon-el-capture", daemon=True)
    t.start()
    return t
