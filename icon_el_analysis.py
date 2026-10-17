"""
ICON TRACE - EL Analysis: what the EL stations' images add up to over a window
(the EL Insight Roadmap, approved by Mukesh on 17 Oct 2026).

Read from el_capture - the poller's index of every EL station's images
(icon_el_capture) - never from the shares. Every figure:

  * counts an image by WHEN IT WAS TAKEN (file_time, the EL PC's clock), on the
    factory day (06:00 to 06:00) and its shifts, as every ICON TRACE figure is;
  * reads an image's reason from its folder through the one defect list
    (defect_folder_map, icon_defects.normalize) when it is read - a folder the
    list does not have is a reason of its own, marked new, never dropped;
  * keeps an image a machine in continuous mode passed by itself APART: nobody
    decided it, so it is in no NG rate (EL Defect Master, Decision 7);
  * shows modules beside images and never adds stations together (Decision 5)
    - one module is imaged at Pre-EL, Post EL and Final EL.

An image re-filed under another verdict (same machine, serial, re-shot number
and time) is one image, its latest filing standing (icon_el_capture.images).

A reason filter narrows the NG side only: the images inspected stay the
denominator, so "Grid Burning" reads as Grid Burning's own rate.
"""

import datetime
import math
import statistics

import icon_clock as clock
import icon_customers as customers
import icon_defects
import icon_el_capture as elcap

STATION_IDS = tuple(s for s, _l in elcap.STATIONS)
SHIFTS = ("A", "B", "C")
ROW_CAP = 3000            # modules a drill-down lists
MAX_RANGE_DAYS = 92
_M = datetime.timedelta(minutes=1)
_H = datetime.timedelta(hours=1)
_D = datetime.timedelta(days=1)

# (name, label) - the window buttons, in the order the screen shows them
WINDOWS = (("1h", "Last 1 hour"), ("8h", "Last 8 hours"), ("shift", "This shift"),
           ("prevshift", "Previous shift"), ("today", "Today"), ("yesterday", "Yesterday"),
           ("7d", "Last 7 days"), ("30d", "Last 30 days"), ("range", "From - to"))
WINDOW_LABEL = dict(WINDOWS)

KINDS = ("ng", "pass", "all", "continuous", "first_pass", "reworked", "still_ng")
# the module journeys across stations a drill-down can list (compare view)
FLOWS = ("pre_ng", "final_ng")
FLOW_SUBS = {"pre_ng": ("", "reworked", "at_final", "final_pass", "final_ng",
                        "final_same", "no_final"),
             "final_ng": ("", "pre_same", "pre_other", "pre_pass", "no_pre")}


class Refused(ValueError):
    """A request the screen should show the reason for (400)."""


# ---- the window ----------------------------------------------------------------

def _day_start(d):
    return datetime.datetime(d.year, d.month, d.day, clock.DAY_STARTS_AT)


def _shift_start(t):
    h = t.hour
    base = t.replace(minute=0, second=0, microsecond=0)
    if 6 <= h < 14:
        return base.replace(hour=6)
    if 14 <= h < 22:
        return base.replace(hour=14)
    if h >= 22:
        return base.replace(hour=22)
    return (base - _D).replace(hour=22)


def _bucket_label(b0, step):
    if step < _H:
        return b0.strftime("%H:%M")
    if step == _H:
        return b0.strftime("%H:00")
    if step == 8 * _H:
        return "%s %s" % (clock.shift_day(b0).strftime("%d-%m"),
                          clock.SHIFT_LETTER[clock.shift_of(b0.hour)])
    return clock.shift_day(b0).strftime("%d-%m")


def _bucket_title(b0, b1, step):
    if step >= _D:
        return "%s (06:00 to 06:00)" % clock.shift_day(b0).strftime("%d-%m-%Y")
    if step == 8 * _H:
        return "%s, %s shift (%s to %s)" % (
            clock.shift_day(b0).strftime("%d-%m-%Y"),
            clock.SHIFT_LETTER[clock.shift_of(b0.hour)], b0.strftime("%H:%M"),
            b1.strftime("%H:%M"))
    return "%s %s to %s" % (b0.strftime("%d-%m-%Y"), b0.strftime("%H:%M"), b1.strftime("%H:%M"))


def window_of(name, now, frm=None, to=None):
    """The window a button means, at `now` (IST, naive): its start and end (the
    end is now for a window still running), the bars it is drawn in, and the
    window of the same length just before it, for a reason's change."""
    now = now.replace(microsecond=0)
    today = _day_start(clock.shift_day(now))
    if name == "1h":
        step = 5 * _M
        start = now.replace(minute=now.minute - now.minute % 5, second=0) - 11 * step
        end, period = now, _H
    elif name == "8h":
        step = _H
        start = now.replace(minute=0, second=0) - 7 * _H
        end, period = now, 8 * _H
    elif name == "shift":
        step, start, end, period = _H, _shift_start(now), now, 8 * _H
    elif name == "prevshift":
        step, end = _H, _shift_start(now)
        start, period = end - 8 * _H, 8 * _H
    elif name == "today":
        step, start, end, period = _H, today, now, _D
    elif name == "yesterday":
        step, start, end, period = _H, today - _D, today, _D
    elif name == "7d":
        step, start, end, period = 8 * _H, today - 6 * _D, now, 7 * _D
    elif name == "30d":
        step, start, end, period = _D, today - 29 * _D, now, 30 * _D
    elif name == "range":
        try:
            f = datetime.date.fromisoformat(frm or "")
            t = datetime.date.fromisoformat(to or frm or "")
        except ValueError:
            raise Refused("Pick a From date (and a To date) for a range - YYYY-MM-DD.")
        if t < f:
            raise Refused("The To date is before the From date.")
        days = (t - f).days + 1
        if days > MAX_RANGE_DAYS:
            raise Refused("A range is at most %d days; this one is %d." % (MAX_RANGE_DAYS, days))
        start = _day_start(f)
        end = min(_day_start(t) + _D, now)
        if end <= start:
            raise Refused("That range starts after now.")
        step = _H if days == 1 else 8 * _H if days <= 10 else _D
        period = days * _D
    else:
        raise Refused("No such window: %s." % name)
    span, st_s = (end - start).total_seconds(), step.total_seconds()
    n = max(1, int(math.ceil(span / st_s)))
    if end >= now:
        n = max(n, int(span // st_s) + 1)      # a running window shows the bar it is in
    buckets = []
    for i in range(n):
        b0 = start + i * step
        b1 = min(b0 + step, end) if end > b0 else b0 + step
        buckets.append({"label": _bucket_label(b0, step), "title": _bucket_title(b0, b0 + step, step),
                        "start": b0.isoformat(), "end": b1.isoformat()})
    return {"name": name, "label": WINDOW_LABEL[name], "start": start, "end": end,
            "prev_start": start - period, "prev_end": end - period, "step": step,
            "period": period, "buckets": buckets, "running": end >= now}


# ---- what an image is ------------------------------------------------------------

def reasons(cur):
    """verdict -> (reason key, label, new?) through the one defect list. A folder
    the list does not know is its own reason - its key 'new:<folder>', its label
    the folder as filed - so it is counted and shown, never dropped or guessed."""
    cur.execute("SELECT folder_key, defect_code FROM defect_folder_map")
    fmap = {r["folder_key"]: r["defect_code"] for r in cur.fetchall()}
    cur.execute("SELECT code, label FROM defect_master")
    labels = {r["code"]: r["label"] for r in cur.fetchall()}
    cache = {}

    def of(verdict):
        r = cache.get(verdict)
        if r is None:
            k = icon_defects.normalize(verdict)
            code = fmap.get(k)
            r = ((code, labels.get(code, code), False) if code else
                 ("new:" + k, (verdict or "").strip() or "(no name)", True))
            cache[verdict] = r
        return r
    return of


def machine_key(station, unit, line):
    return "%s|%s|%s" % (station, unit, line or "")


def machine_label(station, unit, line):
    return "%s · %s" % (elcap.source_label(station, unit),
                        "Line %s" % line if line else "both lines")


class Img(object):
    __slots__ = ("station", "unit", "line", "serial", "verdict", "t", "b", "shift",
                 "machine", "ng", "rkey", "rlabel", "rnew", "model", "customer")


def _master(cur, stations, start, end):
    """serial -> (model, customer) for the modules imaged in the window that the
    master has (its first build instance)."""
    cur.execute("SELECT DISTINCT e.serial, s.model, s.customer FROM el_capture e "
                "JOIN serial s ON s.serial = e.serial AND s.build_instance = 1 "
                "WHERE e.file_time >= %%s AND e.file_time < %%s AND e.station IN (%s)"
                % ",".join(["%s"] * len(stations)),
                (start.isoformat(), end.isoformat()) + tuple(stations))
    return {r["serial"]: (r["model"], r["customer"]) for r in cur.fetchall()}


def _decided(cx, stations, start, end, w, reason_of, master):
    """The images a person decided (mode NULL) at these stations, taken in
    [start, end), one per image however often it was re-filed."""
    c = cx.cursor()
    c.row_factory = None
    c.execute("SELECT station, unit, line, serial, recapture, verdict, file_time "
              "FROM el_capture WHERE mode IS NULL AND file_time >= ? AND file_time < ? "
              "AND station IN (%s) ORDER BY seen_at, capture_id"
              % ",".join("?" * len(stations)),
              (start.isoformat(), end.isoformat()) + tuple(stations))
    keep = {}
    for r in c.fetchall():
        keep[(r[0], r[1], r[3], r[4], r[6])] = r
    step = w["step"].total_seconds()
    w0 = w["start"]
    out = []
    for st, unit, line, serial, _rc, verdict, ft in keep.values():
        i = Img()
        i.station, i.unit, i.line, i.serial, i.verdict = st, unit, line, serial, verdict
        i.t = datetime.datetime.fromisoformat(ft)
        i.b = int((i.t - w0).total_seconds() // step)
        i.shift = clock.SHIFT_LETTER[clock.shift_of(i.t.hour)]
        i.machine = machine_key(st, unit, line)
        i.ng = not elcap.is_pass(verdict)
        if i.ng:
            i.rkey, i.rlabel, i.rnew = reason_of(verdict)
        else:
            i.rkey = i.rlabel = None
            i.rnew = False
        i.model, i.customer = master.get(serial, (None, None))
        out.append(i)
    out.sort(key=lambda i: i.t)
    return out


def _sql_filters(p, col=""):
    """Line, shift, machine, model and customer as SQL on el_capture, for the
    figures read as counts (the window before, continuous-mode images)."""
    w, a = [], []
    if p["line"]:
        w.append(col + "line = %s"); a.append(p["line"])
    if p["shift"]:
        h = "CAST(strftime('%%H', %sfile_time) AS INTEGER)" % col
        w.append({"A": h + " BETWEEN 6 AND 13", "B": h + " BETWEEN 14 AND 21",
                  "C": "(" + h + " >= 22 OR " + h + " < 6)"}[p["shift"]])
    if p["machine"]:
        st, unit, line = p["machine"].split("|")
        w.append(col + "station = %s AND " + col + "unit = %s"); a.extend([st, int(unit)])
        if line:
            w.append(col + "line = %s"); a.append(line)
        else:
            w.append(col + "line IS NULL")
    if p["model"] or p["customer"]:
        m, ma = ["build_instance = 1"], []
        if p["model"]:
            m.append("model = %s"); ma.append(p["model"])
        if p["customer"]:
            m.append("customer = %s"); ma.append(p["customer"])
        w.append(col + "serial IN (SELECT serial FROM serial WHERE %s)" % " AND ".join(m))
        a.extend(ma)
    return w, a


def _continuous(cur, stations, w, p):
    """Images a machine in continuous mode passed by itself, counted apart:
    {station: {"images", "modules", "by_bucket": {i: n}}}. One an operator filed
    later is that filing's, not counted here."""
    out = {st: {"images": 0, "modules": 0, "by_bucket": {}} for st in stations}
    if p["reason"]:
        return out                     # a reason is an NG; these are passes
    fw, fa = _sql_filters(p, "e.")
    where = ("e.mode = 'continuous' AND e.file_time >= %%s AND e.file_time < %%s "
             "AND e.station IN (%s) AND NOT EXISTS (SELECT 1 FROM el_capture f WHERE "
             "f.serial = e.serial AND f.station = e.station AND f.unit = e.unit AND "
             "f.recapture = e.recapture AND f.file_time = e.file_time AND f.mode IS NULL)"
             % ",".join(["%s"] * len(stations)))
    where += "".join(" AND " + x for x in fw)
    args = (w["start"].isoformat(), w["end"].isoformat()) + tuple(stations) + tuple(fa)
    step = int(w["step"].total_seconds())
    cur.execute("SELECT e.station AS st, CAST(((julianday(e.file_time) - julianday(%%s)) * 86400 "
                "+ 0.5) / %d AS INTEGER) AS b, COUNT(*) AS n FROM el_capture e WHERE %s "
                "GROUP BY e.station, b" % (step, where),
                (w["start"].isoformat(),) + args)
    for r in cur.fetchall():
        o = out[r["st"]]
        o["images"] += r["n"]
        o["by_bucket"][r["b"]] = o["by_bucket"].get(r["b"], 0) + r["n"]
    cur.execute("SELECT e.station AS st, COUNT(DISTINCT e.serial) AS m FROM el_capture e "
                "WHERE %s GROUP BY e.station" % where, args)
    for r in cur.fetchall():
        out[r["st"]]["modules"] = r["m"]
    return out


def _previous(cur, stations, w, p, reason_of):
    """The window before, as counts: {station: {"decided", "ng_all", "ng",
    "reasons": {key: n}}} - one per image, its latest filing standing."""
    out = {st: {"decided": 0, "ng_all": 0, "ng": 0, "reasons": {}, "labels": {}}
           for st in stations}
    fw, fa = _sql_filters(p)
    cur.execute(
        "SELECT station, verdict, COUNT(*) AS n FROM (SELECT station, verdict, "
        "ROW_NUMBER() OVER (PARTITION BY station, unit, serial, recapture, file_time "
        "ORDER BY seen_at DESC, capture_id DESC) AS rn FROM el_capture WHERE mode IS NULL "
        "AND file_time >= %%s AND file_time < %%s AND station IN (%s)%s) "
        "WHERE rn = 1 GROUP BY station, verdict"
        % (",".join(["%s"] * len(stations)), "".join(" AND " + x for x in fw)),
        (w["prev_start"].isoformat(), w["prev_end"].isoformat()) + tuple(stations) + tuple(fa))
    for r in cur.fetchall():
        o = out[r["station"]]
        o["decided"] += r["n"]
        if elcap.is_pass(r["verdict"]):
            continue
        o["ng_all"] += r["n"]
        key, label, _new = reason_of(r["verdict"])
        if p["reason"] and key != p["reason"]:
            continue
        o["ng"] += r["n"]
        o["reasons"][key] = o["reasons"].get(key, 0) + r["n"]
        o["labels"][key] = label
    return out


def _coverage(cur):
    """{station: the first image the index holds} - a window that starts before
    it has no data for that part, and the screen says so."""
    cur.execute("SELECT station, MIN(file_time) AS t FROM el_capture GROUP BY station")
    return {r["station"]: r["t"] for r in cur.fetchall()}


def _seen_before(cur, station, w):
    """The modules imaged in the window that the station had decided an image of
    BEFORE it - not new to the station in the window."""
    cur.execute("SELECT DISTINCT serial FROM el_capture WHERE station = %s AND mode IS NULL "
                "AND file_time < %s AND serial IN (SELECT serial FROM el_capture WHERE "
                "station = %s AND mode IS NULL AND file_time >= %s AND file_time < %s)",
                (station, w["start"].isoformat(), station, w["start"].isoformat(),
                 w["end"].isoformat()))
    return {r["serial"] for r in cur.fetchall()}


def _firsts(imgs):
    """{(station, serial): its first decided image in the window, unfiltered}."""
    out = {}
    for i in imgs:                       # in time order
        out.setdefault((i.station, i.serial), i.t)
    return out


def _pct(a, b):
    return round(a * 100.0 / b, 1) if b else None


# ---- filters ---------------------------------------------------------------------

_DIMS = ("line", "shift", "machine", "model", "customer")


def _ok(i, p, skip=None):
    """Does an image pass the page's filters (but `skip`, for its own dropdown)?
    The reason filter is not here: it narrows the NG side only."""
    return ((skip == "line" or not p["line"] or i.line == p["line"]) and
            (skip == "shift" or not p["shift"] or i.shift == p["shift"]) and
            (skip == "machine" or not p["machine"] or i.machine == p["machine"]) and
            (skip == "model" or not p["model"] or i.model == p["model"]) and
            (skip == "customer" or not p["customer"] or i.customer == p["customer"]))


def _customer_label(code):
    try:
        c = customers.get(code)
    except Exception:
        c = None
    return (c or {}).get("name") or code


def _facets(imgs, p):
    """Each dropdown offers what the images hold under every OTHER filter, and
    never drops the value already picked (DECISIONS 8)."""
    f = {"line": set(), "shift": set(), "machine": {}, "model": set(), "customer": set(),
         "reason": {}}
    for i in imgs:
        if _ok(i, p, "line") and i.line:
            f["line"].add(i.line)
        if _ok(i, p, "shift"):
            f["shift"].add(i.shift)
        if _ok(i, p, "machine"):
            f["machine"][i.machine] = machine_label(i.station, i.unit, i.line)
        if _ok(i, p, "model") and i.model:
            f["model"].add(i.model)
        if _ok(i, p, "customer") and i.customer:
            f["customer"].add(i.customer)
        if i.ng and _ok(i, p):
            f["reason"][i.rkey] = (i.rlabel, i.rnew)
    for k in ("line", "shift", "model", "customer"):
        if p[k]:
            f[k].add(p[k])
    if p["machine"] and p["machine"] not in f["machine"]:
        st, unit, line = p["machine"].split("|")
        f["machine"][p["machine"]] = machine_label(st, int(unit), line or None)
    return {"line": sorted(f["line"]), "shift": sorted(f["shift"]),
            "machine": [{"key": k, "label": v} for k, v in sorted(f["machine"].items(),
                                                                   key=lambda x: x[1])],
            "model": sorted(f["model"]),
            "customer": [{"key": c, "label": _customer_label(c)} for c in sorted(f["customer"])],
            "reason": [{"key": k, "label": v[0], "new": v[1]}
                       for k, v in sorted(f["reason"].items(), key=lambda x: x[1][0].lower())]}


# ---- one station ------------------------------------------------------------------

def _new_modules(cur, st, dec, w, firsts):
    """The modules whose FIRST decided image at the station ever recorded was taken
    in the window: {serial: 'first_pass' | 'reworked' | 'still_ng'} - passed at
    the first image, NG then passed later in the window, or still NG at its end.
    A module whose first image a filter leaves out is not judged on a later one."""
    by = {}
    for i in dec:
        if i.station == st:
            by.setdefault(i.serial, []).append(i)
    if not by:
        return {}
    before = _seen_before(cur, st, w)
    out = {}
    for serial, imgs in by.items():
        if serial in before or imgs[0].t != firsts.get((st, serial)):
            continue                    # imaged before the window, or its first image filtered out
        if not imgs[0].ng:
            out[serial] = "first_pass"
        else:
            out[serial] = "reworked" if any(not i.ng for i in imgs[1:]) else "still_ng"
    return out


def _block(cur, st, base, p, w, cont, prev, coverage, cfg_lines, firsts):
    dec = [i for i in base if i.station == st]
    ng_all = [i for i in dec if i.ng]
    ng = [i for i in ng_all if not p["reason"] or i.rkey == p["reason"]]
    mods = {i.serial for i in dec}
    ngmods = {i.serial for i in ng}
    pv = prev.get(st) or {}
    cov = coverage.get(st)
    prev_complete = bool(cov) and cov <= w["prev_start"].isoformat()

    # the Pareto: every reason, busiest first, with its change on the window before
    by = {}
    for i in ng:
        r = by.get(i.rkey)
        if r is None:
            r = by[i.rkey] = {"key": i.rkey, "label": i.rlabel, "new": i.rnew,
                              "images": 0, "mods": set()}
        r["images"] += 1
        r["mods"].add(i.serial)
    reasons, cum = [], 0
    for r in sorted(by.values(), key=lambda r: (-r["images"], r["label"].lower())):
        cum += r["images"]
        before = (pv.get("reasons") or {}).get(r["key"], 0) if prev_complete else None
        reasons.append({"key": r["key"], "label": r["label"], "new": r["new"],
                        "images": r["images"], "modules": len(r["mods"]),
                        "share": _pct(r["images"], len(ng)), "cum": _pct(cum, len(ng)),
                        "prev": before,
                        "change": None if before is None else r["images"] - before})
    # a reason that was there before and is gone now is a change too
    gone = []
    if prev_complete:
        for key, n in sorted((pv.get("reasons") or {}).items(), key=lambda x: -x[1]):
            if key not in by and n:
                gone.append({"key": key, "label": (pv.get("labels") or {}).get(key, key),
                             "prev": n})
    riser = max((r for r in reasons if r["change"] and r["change"] > 0),
                key=lambda r: (r["change"], r["images"]), default=None)

    nb = len(w["buckets"])
    trend = [{"decided": 0, "ng": 0, "ng_all": 0, "cont": 0, "r": {}} for _ in range(nb)]
    for i in dec:
        if 0 <= i.b < nb:
            trend[i.b]["decided"] += 1
            if i.ng:
                trend[i.b]["ng_all"] += 1
    for i in ng:
        if 0 <= i.b < nb:
            t = trend[i.b]
            t["ng"] += 1
            t["r"][i.rkey] = t["r"].get(i.rkey, 0) + 1
    for b, n in ((cont.get(st) or {}).get("by_bucket") or {}).items():
        if 0 <= b < nb:
            trend[b]["cont"] += n
    for t in trend:
        t["rate"] = _pct(t["ng"], t["decided"])

    def split(key_of, keys=None):
        cells = {}
        for i in dec:
            k = key_of(i)
            c = cells.get(k)
            if c is None:
                c = cells[k] = {"decided": 0, "ng": 0, "ng_all": 0, "mods": set(),
                                "ngmods": set(), "r": {}}
            c["decided"] += 1
            c["mods"].add(i.serial)
            if i.ng:
                c["ng_all"] += 1
                if not p["reason"] or i.rkey == p["reason"]:
                    c["ng"] += 1
                    c["ngmods"].add(i.serial)
                    c["r"][i.rkey] = c["r"].get(i.rkey, 0) + 1
        out = []
        for k in (keys if keys is not None else sorted(cells, key=lambda x: x or "")):
            c = cells.get(k) or {"decided": 0, "ng": 0, "ng_all": 0, "mods": set(),
                                 "ngmods": set(), "r": {}}
            out.append({"key": k, "decided": c["decided"], "ng": c["ng"], "ng_all": c["ng_all"],
                        "modules": len(c["mods"]), "ng_modules": len(c["ngmods"]),
                        "rate": _pct(c["ng"], c["decided"]), "r": c["r"]})
        return out

    shifts = split(lambda i: i.shift, list(SHIFTS))
    machines = split(lambda i: i.machine)
    for m in machines:
        s_, u_, l_ = m["key"].split("|")
        m["label"] = machine_label(s_, int(u_), l_ or None)
    lines = split(lambda i: i.line or "")
    seen_lines = {l["key"] for l in lines}
    for ln in ("A", "B"):
        if ln not in seen_lines:
            lines.append({"key": ln, "decided": 0, "ng": 0, "ng_all": 0, "modules": 0,
                          "ng_modules": 0, "rate": None, "r": {}})
    for l in lines:
        l["label"] = "Line %s" % l["key"] if l["key"] else "Both lines (one folder)"
        l["configured"] = bool(l["key"]) and (st, l["key"]) in cfg_lines or \
            (st, None) in cfg_lines
    lines.sort(key=lambda l: l["key"] or "~")

    newm = _new_modules(cur, st, dec, w, firsts)
    fp = sum(1 for v in newm.values() if v == "first_pass")
    rw = sum(1 for v in newm.values() if v == "reworked")
    sn = sum(1 for v in newm.values() if v == "still_ng")
    other = sum(1 for i in ng_all if i.rkey == "DF-OTHER")
    c = cont.get(st) or {"images": 0, "modules": 0}
    tiles = {
        "decided": len(dec), "modules": len(mods), "pass": len(dec) - len(ng_all),
        "ng_all": len(ng_all), "ng": len(ng), "ng_modules": len(ngmods),
        "ng_rate": _pct(len(ng), len(dec)), "ng_rate_modules": _pct(len(ngmods), len(mods)),
        "continuous": c["images"], "continuous_modules": c["modules"],
        "new_modules": len(newm), "first_pass": fp, "reworked": rw, "still_ng": sn,
        "fpy": _pct(fp, len(newm)),
        "top": reasons[0] if reasons else None,
        "other": other, "other_share": None if p["reason"] else _pct(other, len(ng_all)),
        "riser": riser,
        "prev": {"decided": pv.get("decided", 0), "ng": pv.get("ng", 0),
                 "ng_rate": _pct(pv.get("ng", 0), pv.get("decided", 0)),
                 "complete": prev_complete},
    }
    return {"station": st, "label": elcap.LABEL[st], "tiles": tiles, "reasons": reasons,
            "gone": gone, "trend": trend, "shifts": shifts, "machines": machines,
            "lines": lines, "coverage": cov}


# ---- across stations ---------------------------------------------------------------

def _journeys(cx, serials, reason_of):
    """{serial: {station: [images, by time]}} - every image ever recorded of these
    modules, one per image (latest filing), continuous ones marked."""
    out, serials = {}, sorted(serials)
    c = cx.cursor()
    c.row_factory = None
    for k in range(0, len(serials), 500):
        part = serials[k:k + 500]
        c.execute("SELECT station, unit, line, serial, recapture, verdict, file_time, mode "
                  "FROM el_capture WHERE serial IN (%s) ORDER BY seen_at, capture_id"
                  % ",".join("?" * len(part)), part)
        keep = {}
        for r in c.fetchall():
            ident = (r[0], r[1], r[3], r[4], r[6])
            if r[7] == "continuous" and ident in keep and keep[ident][7] is None:
                continue                # a filing stands over the machine's pass
            keep[ident] = r
        for st, unit, line, serial, rc, verdict, ft, mode in keep.values():
            ng = mode != "continuous" and not elcap.is_pass(verdict)
            out.setdefault(serial, {}).setdefault(st, []).append({
                "t": ft, "verdict": verdict, "ng": ng, "cont": mode == "continuous",
                "line": line, "unit": unit,
                "rkey": reason_of(verdict)[0] if ng else None,
                "rlabel": reason_of(verdict)[1] if ng else None})
    for s in out.values():
        for imgs in s.values():
            imgs.sort(key=lambda x: x["t"])
    return out


def _mins(a, b):
    try:
        return int(round((datetime.datetime.fromisoformat(b) -
                          datetime.datetime.fromisoformat(a)).total_seconds() / 60.0))
    except (TypeError, ValueError):
        return None


def _flows(cx, base, p, reason_of):
    """What happened at the other stations to the modules NG at Pre-EL in the
    window - reworked, how long it took, what Final EL then saw - and where the
    modules NG at Final EL in the window had been at Pre-EL: NG there too (same
    reason or another), passed it first time (an escape), or never imaged there
    (Line A's Pre-EL is not on the LAN). Module by module, never images summed."""
    pre_ng, fin_ng = {}, {}
    for i in base:
        if not i.ng or (p["reason"] and i.rkey != p["reason"]):
            continue
        if i.station == "pre_el" and i.serial not in pre_ng:
            pre_ng[i.serial] = i                       # its first NG in the window
        if i.station == "final_el":
            fin_ng[i.serial] = i                       # its newest NG in the window
    js = _journeys(cx, set(pre_ng) | set(fin_ng), reason_of)
    pre_rows, fin_rows = {}, {}
    per_module = {}
    for serial, first in pre_ng.items():
        j = js.get(serial, {})
        pre = [x for x in j.get("pre_el", []) if not x["cont"]]
        t0 = first.t.isoformat()
        nxt = next((x for x in pre if x["t"] > t0 and not x["ng"]), None)
        fin = [x for x in j.get("final_el", []) if not x["cont"]]
        post = j.get("post_el", [])
        last_fin = fin[-1] if fin else None
        fstate = (None if not last_fin else "final_ng" if last_fin["ng"] else "final_pass")
        rec = {"reason": first.rkey, "label": first.rlabel,
               "reworked": bool(nxt), "minutes": _mins(t0, nxt["t"]) if nxt else None,
               "final": fstate,
               "final_same": bool(last_fin and last_fin["ng"] and last_fin["rkey"] == first.rkey),
               "post": ("ng" if any(x["ng"] for x in post) else
                        "pass" if any(not x["cont"] for x in post) else
                        "machine" if post else None)}
        per_module[("pre_ng", serial)] = rec
        r = pre_rows.setdefault(first.rkey, {"key": first.rkey, "label": first.rlabel,
                                             "new": first.rnew, "modules": 0, "reworked": 0,
                                             "minutes": [], "at_final": 0, "final_pass": 0,
                                             "final_ng": 0, "final_same": 0, "no_final": 0})
        r["modules"] += 1
        if rec["reworked"]:
            r["reworked"] += 1
            if rec["minutes"] is not None:
                r["minutes"].append(rec["minutes"])
        if fstate:
            r["at_final"] += 1
            r[fstate] += 1
            if rec["final_same"]:
                r["final_same"] += 1
        else:
            r["no_final"] += 1
    for serial, last in fin_ng.items():
        j = js.get(serial, {})
        t1 = last.t.isoformat()
        pre = [x for x in j.get("pre_el", []) if not x["cont"] and x["t"] <= t1]
        pre_ngs = [x for x in pre if x["ng"]]
        state = ("no_pre" if not pre else
                 "pre_same" if any(x["rkey"] == last.rkey for x in pre_ngs) else
                 "pre_other" if pre_ngs else "pre_pass")
        per_module[("final_ng", serial)] = {"reason": last.rkey, "label": last.rlabel,
                                            "state": state, "line": last.line}
        r = fin_rows.setdefault(last.rkey, {"key": last.rkey, "label": last.rlabel,
                                            "new": last.rnew, "modules": 0, "pre_same": 0,
                                            "pre_other": 0, "pre_pass": 0, "no_pre": 0,
                                            "no_pre_lines": {}})
        r["modules"] += 1
        r[state] += 1
        if state == "no_pre":
            ln = last.line or "—"
            r["no_pre_lines"][ln] = r["no_pre_lines"].get(ln, 0) + 1

    def total(rows, keys):
        t = {k: sum(r[k] for r in rows) for k in keys}
        return t

    pre_list = sorted(pre_rows.values(), key=lambda r: (-r["modules"], r["label"].lower()))
    for r in pre_list:
        r["median_minutes"] = int(statistics.median(r["minutes"])) if r["minutes"] else None
        del r["minutes"]
    fin_list = sorted(fin_rows.values(), key=lambda r: (-r["modules"], r["label"].lower()))
    pre_keys = ("modules", "reworked", "at_final", "final_pass", "final_ng", "final_same",
                "no_final")
    fin_keys = ("modules", "pre_same", "pre_other", "pre_pass", "no_pre")
    all_minutes = [rec["minutes"] for (f, _s), rec in per_module.items()
                   if f == "pre_ng" and rec["minutes"] is not None]
    pre_total = total(pre_list, pre_keys)
    pre_total["median_minutes"] = int(statistics.median(all_minutes)) if all_minutes else None
    return ({"pre_ng": {"rows": pre_list, "total": pre_total},
             "final_ng": {"rows": fin_list, "total": total(fin_list, fin_keys)}},
            per_module, js)


# ---- the request -------------------------------------------------------------------

def params(args):
    """The page's query, checked - each refusal says which value and why."""
    g = lambda k: (args.get(k) or "").strip()
    p = {"station": g("station"), "window": g("window") or "today",
         "from": g("from"), "to": g("to"), "line": g("line").upper(),
         "shift": g("shift").upper(), "machine": g("machine"), "reason": g("reason"),
         "model": g("model"), "customer": g("customer"),
         "kind": g("kind") or "ng", "flow": g("flow"), "sub": g("sub"), "bucket": g("bucket")}
    if p["station"] and p["station"] not in STATION_IDS:
        raise Refused("No such EL station: %s." % p["station"])
    if p["window"] not in WINDOW_LABEL:
        raise Refused("No such window: %s." % p["window"])
    if p["line"] not in ("", "A", "B"):
        raise Refused("Line is A or B.")
    if p["shift"] not in ("", "A", "B", "C"):
        raise Refused("Shift is A, B or C.")
    if p["machine"]:
        parts = p["machine"].split("|")
        if len(parts) != 3 or parts[0] not in STATION_IDS or not parts[1].isdigit() or \
                parts[2] not in ("", "A", "B"):
            raise Refused("No such EL machine: %s." % p["machine"])
    for k, n in (("reason", 160), ("model", 80), ("customer", 80)):
        if len(p[k]) > n:
            raise Refused("That %s is too long." % k)
    if p["kind"] not in KINDS:
        raise Refused("No such list: %s." % p["kind"])
    if p["flow"] and p["flow"] not in FLOWS:
        raise Refused("No such journey: %s." % p["flow"])
    if p["flow"] and p["sub"] not in FLOW_SUBS[p["flow"]]:
        raise Refused("No such part of that journey: %s." % p["sub"])
    if p["bucket"]:
        if not p["bucket"].isdigit():
            raise Refused("A bar is a number.")
        p["bucket"] = int(p["bucket"])
    else:
        p["bucket"] = None
    return p


def _scope(cx, cur, p, now, cfg):
    w = window_of(p["window"], now, p["from"], p["to"])
    stations = [p["station"]] if p["station"] else list(STATION_IDS)
    if p["machine"]:
        mst = p["machine"].split("|")[0]
        if mst not in stations:
            raise Refused("That machine is not at the station shown.")
    reason_of = reasons(cur)
    master = _master(cur, stations, w["start"], w["end"])
    imgs = _decided(cx, stations, w["start"], w["end"], w, reason_of, master)
    return w, stations, reason_of, master, imgs


def analyse(cx, cur, p, now, cfg):
    """Everything the EL Analysis screen draws for one window: per station its
    tiles, Pareto, trend, shifts, machines and lines; with all three stations,
    the modules' journeys across them too."""
    w, stations, reason_of, master, imgs = _scope(cx, cur, p, now, cfg)
    base = [i for i in imgs if _ok(i, p)]
    cont = _continuous(cur, stations, w, p)
    prev = _previous(cur, stations, w, p, reason_of)
    coverage = _coverage(cur)
    roots = elcap.roots(cfg)
    cfg_lines = {(st, ln) for st, _u, ln, _r in roots}
    configured = {st: any(r[0] == st for r in roots) for st in STATION_IDS}
    firsts = _firsts(imgs)
    blocks = {st: _block(cur, st, base, p, w, cont, prev, coverage, cfg_lines, firsts)
              for st in stations}
    out = {
        "ok": True, "generated_at": now.replace(microsecond=0).isoformat(),
        "window": {"name": w["name"], "label": w["label"], "start": w["start"].isoformat(),
                   "end": w["end"].isoformat(), "prev_start": w["prev_start"].isoformat(),
                   "prev_end": w["prev_end"].isoformat(), "running": w["running"],
                   "step_minutes": int(w["step"].total_seconds() // 60),
                   "buckets": w["buckets"]},
        "station": p["station"],
        "stations": [{"id": st, "label": elcap.LABEL[st], "configured": configured[st],
                      "lines": sorted({ln or "" for s2, ln in cfg_lines if s2 == st})}
                     for st in STATION_IDS],
        "filters": {k: p[k] for k in ("line", "shift", "machine", "reason", "model",
                                      "customer")},
        "facets": _facets(imgs, p),
        "blocks": blocks,
        "coverage": coverage,
    }
    if not p["station"]:
        out["flows"] = _flows(cx, base, p, reason_of)[0]
    return out


def _when(t):
    return t.strftime("%d-%m-%Y %H:%M:%S") if isinstance(t, datetime.datetime) else \
        (t or "").replace("T", " ")


def _module_rows(sel, master, cont_rows=None):
    """One row a module: what the selected images say about it."""
    by = {}
    for i in sel:
        m = by.get(i.serial)
        if m is None:
            m = by[i.serial] = {"serial": i.serial, "stations": set(), "machines": set(),
                                "lines": set(), "images": 0, "ng": 0, "reasons": [],
                                "first": i.t, "last": i.t}
        m["stations"].add(elcap.LABEL[i.station])
        m["machines"].add(machine_label(i.station, i.unit, i.line))
        if i.line:
            m["lines"].add(i.line)
        m["images"] += 1
        if i.ng:
            m["ng"] += 1
            if i.rlabel not in m["reasons"]:
                m["reasons"].append(i.rlabel)
        m["first"] = min(m["first"], i.t)
        m["last"] = max(m["last"], i.t)
    rows = []
    for m in sorted(by.values(), key=lambda m: m["last"], reverse=True):
        model, customer = master.get(m["serial"], (None, None))
        rows.append([m["serial"], model or "not in the master",
                     ", ".join(sorted(m["stations"])), ", ".join(sorted(m["machines"])),
                     ", ".join(sorted(m["lines"])) or "—", m["images"], m["ng"],
                     ", ".join(m["reasons"]) or "—", _when(m["first"]), _when(m["last"])])
    return rows


MODULE_COLUMNS = ["Serial", "Model", "Station", "Machine", "Line", "Images", "NG images",
                  "Reasons", "First image", "Last image"]


def drill(cx, cur, p, now, cfg):
    """The modules behind one figure on the screen - a bar, a slice, a cell, a
    row - one row a module, newest first, each opening its journey."""
    w, stations, reason_of, master, imgs = _scope(cx, cur, p, now, cfg)
    base = [i for i in imgs if _ok(i, p)]
    nb = len(w["buckets"])
    if p["bucket"] is not None and p["bucket"] >= nb:
        raise Refused("That bar is not in this window any more - refresh.")
    if p["flow"]:
        _f, per, js = _flows(cx, base, p, reason_of)
        rows = []
        for (flow, serial), rec in per.items():
            if flow != p["flow"]:
                continue
            if p["flow"] == "pre_ng":
                sub = p["sub"]
                if sub == "reworked" and not rec["reworked"]:
                    continue
                if sub == "at_final" and not rec["final"]:
                    continue
                if sub in ("final_pass", "final_ng") and rec["final"] != sub:
                    continue
                if sub == "final_same" and not rec["final_same"]:
                    continue
                if sub == "no_final" and rec["final"]:
                    continue
            elif p["sub"] and rec["state"] != p["sub"]:
                continue
            j = js.get(serial, {})

            def say(st):
                xs = j.get(st, [])
                if not xs:
                    return "—"
                return " → ".join(("NG " + x["rlabel"]) if x["ng"] else
                                  ("Pass (machine)" if x["cont"] else "Pass")
                                  for x in xs[-6:]) + \
                    " (last %s)" % _when(xs[-1]["t"])
            last = max((x["t"] for xs in j.values() for x in xs), default="")
            lines = sorted({x["line"] for xs in j.values() for x in xs if x["line"]})
            model = master.get(serial, (None, None))[0]
            rows.append((last, [serial, model or "not in the master", ", ".join(lines) or "—",
                                rec["label"],
                                ("%d min" % rec["minutes"]) if rec.get("minutes") is not None
                                else ("not yet" if p["flow"] == "pre_ng" else "—"),
                                say("pre_el"), say("post_el"), say("final_el")]))
        rows.sort(key=lambda x: x[0], reverse=True)
        rows = [r for _l, r in rows]
        columns = ["Serial", "Model", "Line",
                   "Pre-EL reason" if p["flow"] == "pre_ng" else "Final EL reason",
                   "Rework took", "Pre-EL images", "Post EL images", "Final EL images"]
        if p["flow"] == "final_ng":
            columns[4] = "—"
            rows = [r[:4] + r[5:] for r in rows]
            columns = columns[:4] + columns[5:]
        title = _flow_title(p)
    elif p["kind"] == "continuous":
        rows, title = _continuous_rows(cur, stations, w, p, master), "Passed by the machine (continuous mode)"
        columns = MODULE_COLUMNS
    else:
        sel = base
        if p["bucket"] is not None:
            sel = [i for i in sel if i.b == p["bucket"]]
        kind = p["kind"]
        if kind == "ng":
            sel = [i for i in sel if i.ng and (not p["reason"] or i.rkey == p["reason"])]
        elif kind == "pass":
            sel = [i for i in sel if not i.ng]
        elif kind in ("first_pass", "reworked", "still_ng"):
            keep, firsts = set(), _firsts(imgs)
            for st in stations:
                keep |= {s for s, v in _new_modules(cur, st, base, w, firsts).items()
                         if v == kind}
            sel = [i for i in sel if i.serial in keep]
        rows = _module_rows(sel, master)
        columns = MODULE_COLUMNS
        title = {"ng": "NG", "pass": "Passed", "all": "Inspected", "first_pass": "Passed first time",
                 "reworked": "NG, then passed after rework", "still_ng": "NG, not passed yet"}[kind]
    total = len(rows)
    return {"ok": True, "title": title, "columns": columns, "rows": rows[:ROW_CAP],
            "total": total, "cap": ROW_CAP,
            "window": {"label": w["label"], "start": w["start"].isoformat(),
                       "end": w["end"].isoformat(),
                       "bucket": w["buckets"][p["bucket"]]["title"] if p["bucket"] is not None else None}}


def _flow_title(p):
    return {("pre_ng", ""): "NG at Pre-EL in the window",
            ("pre_ng", "reworked"): "NG at Pre-EL, passed it after rework",
            ("pre_ng", "at_final"): "NG at Pre-EL, since imaged at Final EL",
            ("pre_ng", "final_pass"): "NG at Pre-EL, Final EL passed",
            ("pre_ng", "final_ng"): "NG at Pre-EL, Final EL NG too",
            ("pre_ng", "final_same"): "NG at Pre-EL, Final EL NG for the same reason",
            ("pre_ng", "no_final"): "NG at Pre-EL, not at Final EL yet",
            ("final_ng", ""): "NG at Final EL in the window",
            ("final_ng", "pre_same"): "NG at Final EL, NG at Pre-EL for the same reason",
            ("final_ng", "pre_other"): "NG at Final EL, NG at Pre-EL for another reason",
            ("final_ng", "pre_pass"): "NG at Final EL, passed Pre-EL first time",
            ("final_ng", "no_pre"): "NG at Final EL, never imaged at Pre-EL"}[(p["flow"], p["sub"])]


def _continuous_rows(cur, stations, w, p, master):
    fw, fa = _sql_filters(p, "e.")
    where = ("e.mode = 'continuous' AND e.file_time >= %%s AND e.file_time < %%s "
             "AND e.station IN (%s) AND NOT EXISTS (SELECT 1 FROM el_capture f WHERE "
             "f.serial = e.serial AND f.station = e.station AND f.unit = e.unit AND "
             "f.recapture = e.recapture AND f.file_time = e.file_time AND f.mode IS NULL)"
             % ",".join(["%s"] * len(stations)))
    where += "".join(" AND " + x for x in fw)
    args = [w["start"].isoformat(), w["end"].isoformat()] + list(stations) + list(fa)
    if p["bucket"] is not None:
        b0 = w["start"] + p["bucket"] * w["step"]
        where += " AND e.file_time >= %s AND e.file_time < %s"
        args += [b0.isoformat(), (b0 + w["step"]).isoformat()]
    cur.execute("SELECT e.station, e.unit, e.line, e.serial, e.verdict, e.file_time FROM "
                "el_capture e WHERE %s" % where, args)
    sel = []
    for r in cur.fetchall():
        i = Img()
        i.station, i.unit, i.line, i.serial, i.verdict = (r["station"], r["unit"], r["line"],
                                                          r["serial"], r["verdict"])
        i.t = datetime.datetime.fromisoformat(r["file_time"])
        i.ng, i.rlabel = False, None
        sel.append(i)
    return _module_rows(sel, master)
