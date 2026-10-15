"""
ICON TRACE - the Pre-EL and Post EL images, indexed for the module journey.

Unit-2 has three EL stations. FQC's own (Settings: EL image root folder) is
read by icon_evidence when FQC looks a serial up. The other two are never
looked up - nobody types a serial at either:

    Pre-EL     before lamination; it scans the back label
    Post EL    after lamination

so the server finds their images itself, by walking the folders every minute
as icon_ingest does for the FQC EL, and keeps one row per image in el_capture.
Search & Trace reads that table, never the shares.

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

import os, time, logging, datetime, threading

import icon_clock as clock
import icon_defects
import icon_evidence as ev
import icon_ingest

log = logging.getLogger("icontrace.el_capture")

# (station, its name on screen), in process order - the journey's order too
STATIONS = (("pre_el", "Pre-EL"), ("post_el", "Post EL"))
LABEL = dict(STATIONS)

DAYS = 2                 # the newest date folders walked, as icon_ingest's SS skip
MISS_TTL_S = 3600        # a name that is no serial is asked about again after this
_NOT_SERIAL = {}         # name -> time.time() it was found not to be in the master
_DOWN = set()            # (station, folder) unreachable - logged once per outage
_CHUNK = 500             # names per IN (...) list


def folder_key(path):
    """One spelling of a folder, for telling whether two settings name the same
    one: case, slash style and a trailing slash ignored. '' when blank."""
    return (path or "").strip().replace("/", "\\").rstrip("\\").lower()


def roots(cfg):
    """(station, line, folder) for every configured Pre-EL and Post EL folder.

    One folder set for a station on BOTH lines is one machine serving both. It
    is walked once, and its images carry no line (None): an image's line is
    what the folder says, never guessed from its serial."""
    out = []
    for station, _label in STATIONS:
        a = (cfg.get("%s_a_root" % station) or "").strip()
        b = (cfg.get("%s_b_root" % station) or "").strip()
        if a and b and folder_key(a) == folder_key(b):
            out.append((station, None, a))
            continue
        for line, root in (("A", a), ("B", b)):
            if root:
                out.append((station, line, root))
    return out


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
    return True


def _reachable(station, line, root):
    """Is the folder there? An unreachable one is logged when it goes, once,
    and when it comes back - not every minute in between."""
    key = (station, folder_key(root))
    ok = os.path.isdir(root)
    where = "%s%s folder %s" % (LABEL[station], " Line %s" % line if line else "",
                                root)
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


def scan(cfg):
    """Every image the EL operator has filed under a verdict, in the newest two
    date folders of each configured Pre-EL and Post EL folder - read from the
    shares alone, no database. A folder that cannot be read is skipped; the
    others are still walked."""
    out = []
    for station, line, root in roots(cfg):
        if not _reachable(station, line, root):
            continue
        for day in icon_ingest._el_day_dirs(root, DAYS):
            for path, mtime, depth in _walk(day.path):
                if not _filed(path, depth):
                    continue          # filed within minutes; a later pass has it
                out.append({
                    "station": station, "line": line,
                    "path": os.path.normpath(path),
                    "stem": os.path.splitext(os.path.basename(path))[0],
                    # exactly as read_el() reads a verdict
                    "verdict": os.path.basename(os.path.dirname(path)).strip() or "OK",
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
    reached: a file whose station, serial, re-shot number, verdict and time are
    already recorded is that capture again - the folder's spelling changed in
    Settings, or the image was moved to another shift folder under the same
    verdict - and is not recorded twice."""
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

        same = {(r["serial"], r["recapture"], r["verdict"], r["file_time"])
                for r in _recorded(
                    cur, "SELECT serial, recapture, verdict, file_time FROM "
                         "el_capture WHERE station=%%s AND serial IN (%s)",
                    station, {h["serial"] for h in hits})}
        for h in sorted(hits, key=lambda h: (h["file_time"], h["path"])):
            ident = (h["serial"], h["recapture"], h["verdict"], h["file_time"])
            if ident in same:
                continue
            same.add(ident)
            out.append(h)
    return out


def apply(cur, rows):
    """Write what pick_new() found - each row checked absent first, so a pass
    with nothing new writes nothing at all (db.ingest_review_item's rule).
    Returns {station: rows written}."""
    out = {}
    seen = clock.stamp()
    for r in rows:
        cur.execute(
            "INSERT INTO el_capture (station, line, serial, recapture, verdict, "
            "path, file_time, seen_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (station, path) DO NOTHING",
            (r["station"], r["line"], r["serial"], r["recapture"], r["verdict"],
             r["path"], r["file_time"], seen))
        if cur.rowcount:
            out[r["station"]] = out.get(r["station"], 0) + 1
    return out


def run(cfg, cur):
    """One pass on the connection given (tests). The poller uses run_pass(),
    which reads the shares with no connection open."""
    return apply(cur, pick_new(cur, scan(cfg)))


def run_pass():
    """One pass as the poller runs it: the settings, then the shares with no
    database connection held, then a short write of what is new."""
    import store, db
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
    files = scan(cfg)
    if not files:
        return {}
    with store.conn() as (cx, cur):
        return apply(cur, pick_new(cur, files))


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
                counts = run_pass()
                if counts:
                    log.info("new images: %s", counts)
            except Exception:
                log.exception("EL capture pass failed")
            time.sleep(interval)

    t = threading.Thread(target=loop, name="icon-el-capture", daemon=True)
    t.start()
    return t
