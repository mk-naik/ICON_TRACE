"""
ICON TRACE - tests for the Pre-EL and Post EL image index (icon_el_capture.py).

    python test_el_capture.py

THE RULES THIS FILE DEFENDS

  1. Every image filed under a verdict in the newest two date folders of a
     configured Pre-EL or Post EL folder is recorded once: its station, its
     line (none when one folder serves both lines), its serial, its re-shot
     number and its verdict - the folder's name, at any depth, as read_el
     reads it.

  2. An image still waiting in its shift folder is not recorded until the
     EL operator files it.

  3. A file counts when its name, less any _N, looks like a serial or is a
     serial in the master (a custom one). Junk names are not looked up every
     minute.

  4. A pass that finds nothing new writes nothing.

  5. Nothing is deleted or changed when a file or a share disappears, and an
     unreachable folder costs only itself.

  6. One folder is one EL station: Settings refuses a folder set as two of
     FQC EL, Pre-EL and Post EL (any line). The same folder for one station on
     both lines is one machine serving both, and allowed.

  7. The module journey shows the EL steps only where the serial was captured
     - no step at all otherwise - after Produced and before Anomaly / FQC: every
     Pre-EL image, each NG followed by a Rework step until one passes; Post EL
     as one step, an NG there a rejection. Read from el_capture, never from the
     shares.

  8. EL Stations lists every module first imaged at a station in the period,
     with what its images add up to; its dropdowns are dynamic; Production
     Incharge, Admin and Super Admin may open it, others by user permission -
     and the accounts that existed before it are given it once, by role.

  9. An NG at Post EL raises one Needs Review item - the module is kept off
     the line for Quality, who close it with a reason.

 10. Each EL PC's clock is shown against the server's - images are put in
     order by their time - and one that is off is flagged.

Each test names the rule it defends, so a failure says which decision broke.
"""

import datetime, logging, os, shutil, sys, tempfile, traceback

TMP = tempfile.mkdtemp(prefix="icontrace_elcap_")
os.environ["ICON_DB_FILE"] = os.path.join(TMP, "test.db")

import db                                                    # noqa: E402
import store                                                 # noqa: E402
import icon_clock as clock                                   # noqa: E402
import icon_el_capture as elcap                              # noqa: E402
import app as APP                                            # noqa: E402
import auth_test_helper as AUTH                              # noqa: E402

_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


PRE_A = os.path.join(TMP, "pre_a")
PRE_A2 = os.path.join(TMP, "pre_a2")    # Line A's secondary Pre-EL machine
PRE_B = os.path.join(TMP, "pre_b")
POST_B = os.path.join(TMP, "post_b")

S_CRACK = "ICON625R12A1522901"
S_CROSS = "ICON625R12A1522902"
S_OLD = "ICON625R12A1522903"           # in the 16-09-2026 folder
S_STRAY = "ICON625R12A1522904"         # in 'New folder' - never walked
S_POST = "ICON625R12A1522905"
S_WAIT = "ICON625R12A1522906"          # not filed yet
CUSTOM = "AB-CUSTOM-7001"              # a custom serial, in the master
CUSTOM_US = "CUST_12"                  # a custom serial that itself ends in _digits
NOT_PLANNED = "ICON625R12A1522999"     # ICON-shaped, not in the master


def ist(s):
    return datetime.datetime.fromisoformat(s).replace(tzinfo=clock.IST).timestamp()


def put(root, rel, name, at="2026-10-14T09:15:00"):
    """One image on a fake share, with its file time set - the EL PC's clock."""
    d = os.path.join(root, *rel.split("/")) if rel else root
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    open(p, "wb").close()
    os.utime(p, (ist(at), ist(at)))
    return p


def master(cur, serial, seq, fmt=2):
    store.insert(cur, "serial", {
        "serial": serial, "build_instance": 1, "model": "ISEN625-G12R",
        "wattage": 625, "customer": "STOCK", "dcr": "DCR",
        "format_version": fmt, "date_produced": "2026-10-14", "shift": 1,
        "sequence": seq, "state": "planned"})


def fresh(**cfg):
    store.wipe()
    elcap._NOT_SERIAL.clear()
    elcap._DOWN.clear()
    for d in (PRE_A, PRE_A2, PRE_B, POST_B):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    conf = {"el_root": "", "el_a_root": "", "el_b_root": "",
            "pre_el_a_root": PRE_A, "pre_el_b_root": "",
            "pre_el2_a_root": "", "pre_el2_b_root": "",
            "post_el_a_root": "", "post_el_b_root": POST_B}
    conf.update(cfg)
    with store.conn() as (cx, cur):
        db.set_config(cur, conf)
        for i, s in enumerate((S_CRACK, S_CROSS, S_OLD, S_STRAY, S_POST, S_WAIT)):
            master(cur, s, i + 1)
        master(cur, CUSTOM, 50, fmt=0)
        master(cur, CUSTOM_US, 51, fmt=0)


def run():
    with store.conn() as (cx, cur):
        return elcap.run(db.get_config(cur), cur)


def captures(serial=None):
    with store.conn() as (cx, cur):
        if serial:
            return store.rows(cur, "SELECT * FROM el_capture WHERE serial=%s "
                                   "ORDER BY capture_id", (serial,))
        return store.rows(cur, "SELECT * FROM el_capture ORDER BY capture_id")


class _Spy:
    """A cursor that remembers what it was asked - to tell which lookups a
    pass made."""

    def __init__(self, cur):
        self._c, self.sql = cur, []

    def execute(self, sql, args=()):
        self.sql.append(sql)
        self._c.execute(sql, args)
        return self

    def fetchall(self):
        return self._c.fetchall()

    def fetchone(self):
        return self._c.fetchone()

    @property
    def rowcount(self):
        return self._c.rowcount


# --------------------------------------------------------------------------
# 1. what is recorded
# --------------------------------------------------------------------------

@test("each filed image is recorded with its station, line, verdict and re-shot "
      "number - Cell Crack, a nested Lead Open\\Cross, a 16-09-2026 date folder - "
      "and a stray 'New folder' is never walked")
def t_recorded():
    fresh()
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg", "2026-10-14T09:15:00")
    put(PRE_A, "2026-10-14/中班/Lead Open/Cross", S_CROSS + ".jpg", "2026-10-14T15:40:07")
    put(PRE_A, "2026-10-14/中班/Lead Open/Cross", S_CROSS + "_2.jpg", "2026-10-14T15:52:00")
    put(PRE_A, "16-09-2026/晚班/OK", S_OLD + ".jpg", "2026-09-17T01:12:56")
    put(PRE_A, "New folder/Burning", S_STRAY + ".jpg")
    put(POST_B, "2026-10-14/早班/OK", S_POST + ".jpg", "2026-10-14T10:02:00")
    counts = run()
    assert counts == {"pre_el": 4, "post_el": 1}, counts
    got = {(r["station"], r["line"], r["serial"], r["recapture"], r["verdict"],
            r["file_time"]) for r in captures()}
    assert got == {
        ("pre_el", "A", S_CRACK, 0, "Cell Crack", "2026-10-14T09:15:00"),
        ("pre_el", "A", S_CROSS, 0, "Cross", "2026-10-14T15:40:07"),
        ("pre_el", "A", S_CROSS, 2, "Cross", "2026-10-14T15:52:00"),
        ("pre_el", "A", S_OLD, 0, "OK", "2026-09-17T01:12:56"),
        ("post_el", "B", S_POST, 0, "OK", "2026-10-14T10:02:00"),
    }, got
    r = captures(S_CRACK)[0]
    assert r["path"] == os.path.normpath(os.path.join(
        PRE_A, "2026-10-14", "早班", "Cell Crack", S_CRACK + ".jpg")), r["path"]
    # seen_at: when the poller recorded it, in clock.stamp()'s form
    datetime.datetime.strptime(r["seen_at"], "%Y-%m-%dT%H:%M:%S")
    assert not captures(S_STRAY), "a folder that is not a date was walked"


@test("only the newest two date folders are walked - by the date the name means")
def t_newest_two_days():
    fresh()
    put(PRE_A, "2026-10-12/早班/OK", S_CRACK + ".jpg", "2026-10-12T09:00:00")
    put(PRE_A, "2026-10-13/早班/OK", S_CROSS + ".jpg", "2026-10-13T09:00:00")
    put(PRE_A, "14-10-2026/早班/OK", S_OLD + ".jpg", "2026-10-14T09:00:00")
    run()
    assert {r["serial"] for r in captures()} == {S_CROSS, S_OLD}, \
        [dict(r) for r in captures()]


@test("the line is the folder's, never the serial's: a Line B folder's image is B")
def t_line_from_folder():
    fresh(pre_el_b_root=PRE_B)
    put(PRE_B, "2026-10-14/早班/OK", S_CRACK + ".jpg")
    run()
    assert [(r["station"], r["line"]) for r in captures(S_CRACK)] == [("pre_el", "B")]


# --------------------------------------------------------------------------
# 2. not filed yet
# --------------------------------------------------------------------------

@test("an image straight under its shift folder is not recorded until the EL "
      "operator files it - and then it is, with that verdict")
def t_unfiled_waits():
    fresh()
    p = put(PRE_A, "2026-10-14/早班", S_WAIT + ".jpg", "2026-10-14T13:59:48")
    put(PRE_A, "2026-10-14", S_CRACK + ".jpg")                  # in the date folder itself
    assert run() == {}, "an unfiled image was recorded"
    assert not captures()
    dest = os.path.join(PRE_A, "2026-10-14", "中班", "OK")
    os.makedirs(dest)
    os.replace(p, os.path.join(dest, S_WAIT + ".jpg"))           # filed, minutes later
    assert run() == {"pre_el": 1}
    rows = captures(S_WAIT)
    assert [(r["verdict"], r["file_time"]) for r in rows] == [("OK", "2026-10-14T13:59:48")], \
        [dict(r) for r in rows]


@test("the same holds under a date folder spelled 16-09-2026: the shift's name "
      "(早班) is never taken for a verdict")
def t_unfiled_waits_ddmmyyyy():
    fresh()
    put(PRE_A, "16-09-2026/早班", S_WAIT + ".jpg", "2026-09-16T10:00:00")
    put(PRE_A, "16-09-2026/早班/Cell Crack", S_CRACK + ".jpg", "2026-09-16T10:01:00")
    run()
    assert [r["serial"] for r in captures()] == [S_CRACK], [dict(r) for r in captures()]


@test("a tree with no shift level still counts: date / OK / serial.jpg is filed")
def t_shallow_tree():
    fresh()
    put(PRE_A, "2026-10-14/OK", S_CRACK + ".jpg")
    put(PRE_A, "2026-10-14/Cell Crack", S_CROSS + ".jpg")
    run()
    assert {(r["serial"], r["verdict"]) for r in captures()} == {
        (S_CRACK, "OK"), (S_CROSS, "Cell Crack")}


# --------------------------------------------------------------------------
# 3. which names count
# --------------------------------------------------------------------------

JUNK = ("        2A1522067.jpg", "ICjN625R12AF522055.jpg", "CON625R12A14221_1.jpg",
        "0000.jpg", "Thumbs.db")                    # all seen on the real share


@test("a junk file name is not recorded; a custom serial in the master is - with "
      "its re-shot number - and an ICON-shaped one not planned yet is kept too")
def t_names():
    fresh()
    for j in JUNK:
        put(PRE_A, "2026-10-14/中班/OK", j)
    put(PRE_A, "2026-10-14/中班/OK", CUSTOM.lower() + ".jpg", "2026-10-14T15:00:00")
    put(PRE_A, "2026-10-14/中班/Cell Crack", CUSTOM + "_1.jpg", "2026-10-14T15:05:00")
    put(PRE_A, "2026-10-14/中班/OK", CUSTOM_US + ".jpg", "2026-10-14T15:10:00")
    put(PRE_A, "2026-10-14/中班/OK", CUSTOM_US + "_3.jpg", "2026-10-14T15:20:00")
    put(PRE_A, "2026-10-14/中班/OK", NOT_PLANNED + ".jpg", "2026-10-14T15:30:00")
    put(PRE_A, "2026-10-14/中班/OK", "ICON625R12A1522907.bmp", "2026-10-14T15:31:00")
    run()
    got = {(r["serial"], r["recapture"], r["verdict"]) for r in captures()}
    assert got == {(CUSTOM, 0, "OK"), (CUSTOM, 1, "Cell Crack"), (CUSTOM_US, 0, "OK"),
                   (CUSTOM_US, 3, "OK"), (NOT_PLANNED, 0, "OK"),
                   ("ICON625R12A1522907", 0, "OK")}, got   # by name, not extension


@test("junk names are looked up in the master once, not every minute - and a "
      "custom serial loaded after its image appeared is found once that hour is up")
def t_misses_remembered():
    fresh()
    for j in JUNK:
        put(PRE_A, "2026-10-14/中班/OK", j)
    late = "LATE-CUSTOM-1"
    put(PRE_A, "2026-10-14/中班/OK", late + ".jpg")
    with store.conn() as (cx, cur):
        spy = _Spy(cur)
        elcap.run(db.get_config(cur), spy)
    asked = [s for s in spy.sql if "FROM serial WHERE serial IN" in s]
    assert len(asked) == 1, "one lookup per pass, not one per name: %s" % asked
    assert late in elcap._NOT_SERIAL and "0000" in elcap._NOT_SERIAL, elcap._NOT_SERIAL
    with store.conn() as (cx, cur):
        master(cur, late, 60, fmt=0)                   # planned now
        spy = _Spy(cur)
        assert elcap.run(db.get_config(cur), spy) == {}
    assert not [s for s in spy.sql if "FROM serial WHERE serial IN" in s], \
        "the remembered misses were looked up again a minute later"
    for k in list(elcap._NOT_SERIAL):                   # an hour on
        elcap._NOT_SERIAL[k] -= elcap.MISS_TTL_S + 1
    assert run() == {"pre_el": 1}
    assert [r["serial"] for r in captures()] == [late]


# --------------------------------------------------------------------------
# 4. quiet
# --------------------------------------------------------------------------

@test("a second pass over unchanged folders writes nothing at all - no row, no "
      "change-feed entry")
def t_second_pass_quiet():
    fresh()
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg")
    put(POST_B, "2026-10-14/早班/OK", S_POST + ".jpg")
    put(PRE_A, "2026-10-14/中班/OK", "0000.jpg")
    assert sum(run().values()) == 2
    with store.conn() as (cx, cur):
        feed = store.one(cur, "SELECT COUNT(*) AS n FROM change_log")["n"]
    with store.conn() as (cx, cur):
        cfg = db.get_config(cur)
        before = cx.total_changes
        assert elcap.run(cfg, cur) == {}
        assert cur.written == set(), "the pass wrote to %s" % cur.written
        assert cx.total_changes == before
    assert elcap.run_pass() == {}                    # the poller's own path, too
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM change_log")["n"] == feed
    assert len(captures()) == 2


@test("the first pass's rows are never in the change feed either: no screen "
      "subscribes to el_capture")
def t_not_in_feed():
    fresh()
    with store.conn() as (cx, cur):
        feed = store.one(cur, "SELECT COUNT(*) AS n FROM change_log")["n"]
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")
    assert elcap.run_pass() == {"pre_el": 1}
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM change_log")["n"] == feed
    assert "el_capture" not in store.TOPIC_OF_TABLE


@test("one folder set for both lines is one machine: one row per image, line NULL "
      "- however the two settings spell it")
def t_one_folder_both_lines():
    fresh(pre_el_b_root=PRE_A.upper() + "\\", post_el_a_root=POST_B.replace("\\", "/"))
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")
    put(POST_B, "2026-10-14/早班/OK", S_POST + ".jpg")
    assert run() == {"pre_el": 1, "post_el": 1}
    assert [(r["serial"], r["line"]) for r in captures()] == [(S_CRACK, None), (S_POST, None)]


@test("re-typing a folder's spelling in Settings does not record its images again")
def t_respelled_root():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")
    run()
    with store.conn() as (cx, cur):
        db.set_config(cur, {"pre_el_a_root": PRE_A.upper().replace("\\", "/") + "/"})
    assert run() == {}
    assert len(captures()) == 1


@test("an image re-filed to another shift folder under the same verdict is the "
      "same capture; re-filed under ANOTHER verdict it is a new reading, and the "
      "first row is kept")
def t_moved_image():
    fresh()
    p = put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T13:07:34")
    run()
    d2 = os.path.join(PRE_A, "2026-10-14", "中班", "OK")
    os.makedirs(d2)
    p2 = os.path.join(d2, S_CRACK + ".jpg")
    os.replace(p, p2)
    assert run() == {}, "the same image was recorded twice"
    d3 = os.path.join(PRE_A, "2026-10-14", "中班", "Ribbon short")
    os.makedirs(d3)
    os.replace(p2, os.path.join(d3, S_CRACK + ".jpg"))
    assert run() == {"pre_el": 1}
    assert [r["verdict"] for r in captures(S_CRACK)] == ["OK", "Ribbon short"]


# --------------------------------------------------------------------------
# 5. nothing deleted; an unreachable folder costs only itself
# --------------------------------------------------------------------------

@test("an unreachable folder: the pass finishes, nothing is deleted, the other "
      "station is still indexed, and the outage is logged once - and its end")
def t_unreachable():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")
    put(POST_B, "2026-10-14/早班/OK", S_POST + ".jpg", "2026-10-14T10:00:00")
    run()
    gone = PRE_A + "_off"
    os.rename(PRE_A, gone)                                  # the Pre-EL PC switched off
    put(POST_B, "2026-10-14/中班/OK", S_CROSS + ".jpg", "2026-10-14T15:00:00")
    seen = []

    class H(logging.Handler):
        def emit(self, rec):
            seen.append((rec.levelname, rec.getMessage()))

    h = H()
    elcap.log.addHandler(h)
    level = elcap.log.level
    elcap.log.setLevel(logging.INFO)          # serve.py logs at INFO; a test has no config
    try:
        assert run() == {"post_el": 1}
        assert run() == {}
        os.rename(gone, PRE_A)
        assert run() == {}
    finally:
        elcap.log.removeHandler(h)
        elcap.log.setLevel(level)
    assert {r["serial"] for r in captures()} == {S_CRACK, S_POST, S_CROSS}
    warns = [m for lvl, m in seen if lvl == "WARNING"]
    assert len(warns) == 1 and PRE_A in warns[0], seen
    assert [m for lvl, m in seen if lvl == "INFO" and "answers again" in m], seen


@test("the poller's log line names the serials it recorded, not only how many - "
      "at most ten a station, then '+N more'")
def t_log_names_serials():
    fresh(pre_el2_a_root=PRE_A2)
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T09:00:00")
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CROSS + ".jpg", "2026-10-14T09:01:00")
    put(PRE_A2, "2026-10-14/早班/OK", S_CROSS + ".jpg", "2026-10-14T11:00:00")
    seen = []

    class H(logging.Handler):
        def emit(self, rec):
            seen.append(rec.getMessage())

    h = H()
    elcap.log.addHandler(h)
    level = elcap.log.level
    elcap.log.setLevel(logging.INFO)
    try:
        assert elcap.run_pass() == {"pre_el": 3}
        for i in range(12):
            put(PRE_A, "2026-10-14/中班/OK", "ICON625R12A15229%02d.jpg" % (40 + i),
                "2026-10-14T15:%02d:00" % i)
        assert elcap.run_pass() == {"pre_el": 12}
    finally:
        elcap.log.removeHandler(h)
        elcap.log.setLevel(level)
    assert len(seen) == 2, seen
    assert "Pre-EL: %s OK (A), %s Cell Crack (A), %s OK (A, secondary)" % (
        S_CRACK, S_CROSS, S_CROSS) in seen[0], seen[0]
    assert "ICON625R12A1522940 OK (A)" in seen[1] and "(+2 more)" in seen[1], seen[1]
    assert "ICON625R12A1522950" not in seen[1], seen[1]


@test("an image deleted from the share keeps its row")
def t_deleted_file_kept():
    fresh()
    p = put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg")
    run()
    os.remove(p)
    shutil.rmtree(os.path.join(PRE_A, "2026-10-14"))
    assert run() == {}
    assert [r["verdict"] for r in captures(S_CRACK)] == ["Cell Crack"]


@test("no folder configured: nothing is scanned, nothing written")
def t_nothing_configured():
    fresh(pre_el_a_root="", post_el_b_root="")
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")
    assert elcap.roots({"pre_el_a_root": "", "pre_el_b_root": " "}) == []
    assert elcap.run_pass() == {}
    assert not captures()


@test("store.ensure() adds el_capture, and its serial index, to an existing "
      "database that has neither")
def t_ensure_adds_table():
    fresh()
    with store.conn() as (cx, cur):
        cur.execute("DROP TABLE el_capture")
        assert not store.rows(cur, "SELECT name FROM sqlite_master WHERE "
                                   "name='el_capture'")
    store._ready = False
    store.ensure()
    with store.conn() as (cx, cur):
        cols = [r["name"] for r in store.rows(cur, "PRAGMA table_info(el_capture)")]
        idx = [r["name"] for r in store.rows(cur, "PRAGMA index_list(el_capture)")]
    assert cols == ["capture_id", "station", "unit", "line", "serial", "recapture",
                    "verdict", "path", "file_time", "seen_at"], cols
    assert "ix_el_capture_serial" in idx, idx


# --------------------------------------------------------------------------
# 6. Settings: one folder is one station
# --------------------------------------------------------------------------

FQC_EL = os.path.join(TMP, "fqc_el")


def signed_in():
    c = APP.app.test_client()
    AUTH.test_login(c)                         # Super Admin: who writes Settings
    return c


def stored(key):
    with store.conn() as (cx, cur):
        return db.get_config(cur)[key]


@test("a save that uses the FQC EL folder as Pre-EL is refused with the reason - "
      "however it is spelled - and nothing of that save is stored")
def t_settings_fqc_as_pre_el():
    fresh(el_b_root=FQC_EL, pre_el_a_root="", post_el_b_root="")
    r = signed_in().post("/api/settings", json={
        "pre_el_b_root": FQC_EL.upper().replace("\\", "/") + "/", "unit": "9"})
    assert r.status_code == 400, r.get_json()
    why = r.get_json()["why"]
    assert "FQC EL folder of Line B" in why and "Pre-EL primary folder of Line B" in why, why
    assert stored("pre_el_b_root") == "" and stored("unit") == "2"


@test("Pre-EL and Post EL may not share a folder either, on any line; nor may "
      "Line A's FQC folder kept in the older el_root setting")
def t_settings_other_clashes():
    fresh(el_root=FQC_EL, el_a_root="", pre_el_a_root="", post_el_b_root="")
    c = signed_in()
    r = c.post("/api/settings", json={"pre_el_a_root": PRE_A, "post_el_b_root": PRE_A})
    assert r.status_code == 400 and "Post EL folder of Line B" in r.get_json()["why"], \
        r.get_json()
    r = c.post("/api/settings", json={"post_el_a_root": FQC_EL + "\\"})
    assert r.status_code == 400 and "FQC EL folder of Line A" in r.get_json()["why"], \
        r.get_json()
    # the primary and the secondary are two machines, so two folders
    r = c.post("/api/settings", json={"pre_el_a_root": PRE_A, "pre_el2_b_root": PRE_A})
    why = r.get_json().get("why", "")
    assert r.status_code == 400 and "Pre-EL primary folder of Line A" in why and \
        "Pre-EL secondary folder of Line B" in why, r.get_json()
    assert stored("pre_el_a_root") == "" and stored("post_el_a_root") == ""
    assert stored("pre_el2_b_root") == ""


@test("the same folder for one station on both lines is allowed: one machine "
      "serving both lines")
def t_settings_one_folder_both_lines():
    fresh(el_a_root=FQC_EL, el_b_root=FQC_EL, pre_el_a_root="", post_el_b_root="")
    r = signed_in().post("/api/settings", json={
        "pre_el_a_root": PRE_A, "pre_el_b_root": PRE_A.lower() + "\\",
        "pre_el2_a_root": PRE_A2, "pre_el2_b_root": PRE_A2,
        "post_el_a_root": POST_B, "post_el_b_root": POST_B})
    assert r.status_code == 200, r.get_json()
    assert stored("pre_el_a_root") == PRE_A and stored("post_el_b_root") == POST_B
    assert stored("pre_el2_b_root") == PRE_A2


@test("the older /settings form is held to the same rule")
def t_settings_form_route():
    fresh(el_b_root=FQC_EL, pre_el_a_root="", post_el_b_root="")
    r = signed_in().post("/settings", data={"pre_el_b_root": FQC_EL})
    assert r.status_code == 400, r.status_code
    assert stored("pre_el_b_root") == ""


@test("a save that names no EL folder is not held up by the folder rule")
def t_settings_unrelated_save():
    fresh(el_b_root=FQC_EL)
    with store.conn() as (cx, cur):          # a clash written behind the screen's back
        db.set_config(cur, {"pre_el_b_root": FQC_EL})
    r = signed_in().post("/api/settings", json={"unit": "2", "pallet_ceiling": "36"})
    assert r.status_code == 200, r.get_json()


@test("Evidence Sources shows the Pre-EL primary, Pre-EL secondary and Post EL "
      "folders on each line, with a reachability tag and the hint that the server "
      "reads them")
def t_settings_page():
    fresh(pre_el_b_root=os.path.join(TMP, "switched_off"), pre_el2_a_root=PRE_A2)
    html = " ".join(signed_in().get("/view/settings").get_data(as_text=True).split())
    for ln in ("a", "b"):
        for f in ("pre_el", "pre_el2", "post_el"):
            assert 'id="s_%s_%s"' % (ln, f) in html, (ln, f)
    assert html.count("Pre-EL primary image root folder") == 2
    assert html.count("Pre-EL secondary image root folder") == 2
    assert html.count("Post EL (after lamination) image root folder") == 2
    assert html.count("Read by the server every minute, not by FQC; the account the "
                      "server runs as needs read access to the share.") == 6
    assert "Pre-EL primary OK" in html and "Post EL OK" in html  # A's primary, B's Post EL
    assert "Pre-EL secondary OK" in html and "Pre-EL secondary —" in html   # A's set, B's not
    assert "Pre-EL primary NC" in html and \
        "Unreachable: %s" % os.path.join(TMP, "switched_off") in html
    assert "Pre-EL primary —" not in html and "Post EL —" in html  # A's Post EL is blank
    assert "No Post EL folder configured for this line." in html
    assert "No Pre-EL secondary folder configured for this line." in html
    for k in ("pre_el", "pre_el2", "post_el"):
        assert "body['%s_'+ln+'_root']" % k in html, k


@test("/api/evidence/sources lists Pre-EL and Post EL for each line, with their state")
def t_sources_api():
    fresh(pre_el_b_root=os.path.join(TMP, "switched_off"), pre_el2_a_root=PRE_A2)
    rows = {r["id"]: r for r in signed_in().get("/api/evidence/sources").get_json()}
    assert {"PRE-EL1-A", "PRE-EL1-B", "PRE-EL2-A", "PRE-EL2-B", "POST-EL-A",
            "POST-EL-B"} <= set(rows), sorted(rows)
    assert rows["PRE-EL1-A"]["state"] == "OK" and rows["PRE-EL1-A"]["path"] == PRE_A
    assert rows["PRE-EL1-B"]["state"] == "NC"
    assert rows["PRE-EL2-A"]["state"] == "OK" and rows["PRE-EL2-A"]["type"] == "PRE_EL2_ROOT"
    assert rows["PRE-EL2-B"]["state"] == "—"
    assert rows["POST-EL-A"]["state"] == "—" and rows["POST-EL-B"]["state"] == "OK"
    assert rows["POST-EL-B"]["type"] == "POST_EL_ROOT" and rows["PRE-EL1-A"]["line"] == "A"
    assert "every minute" in rows["PRE-EL1-A"]["rule"]
    assert rows["PRE-EL2-A"]["rule"].startswith("Secondary.")


@test("the reachability probes are asked at once, not one after another - a "
      "switched-off PC costs the page one timeout, not one per folder")
def t_probes_at_once():
    import time

    def slow(path):
        time.sleep(0.4)
        return True

    t = time.time()
    got = APP._reachable_all({i: (slow, "p%d" % i) for i in range(8)})
    took = time.time() - t
    assert got == {i: True for i in range(8)}, got
    assert took < 1.5, "%.2fs for eight 0.4 s probes" % took


# --------------------------------------------------------------------------
# 7. the module journey
# --------------------------------------------------------------------------

def journey(serial):
    r = signed_in().get("/api/trace/serial/" + serial)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["journey"]


@test("a serial with no captures has no Pre-EL or Post EL step at all - not a "
      "dash, not 'pending' - and the journey is otherwise as it was")
def t_journey_none():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")           # another module's
    run()
    stages = [j["stage"] for j in journey(S_CROSS)]
    assert stages == ["Allocated", "Produced", "FQC", "Packed", "Challan", "Gate pass"], stages


def el_part(serial):
    """The journey's EL steps only."""
    return [j for j in journey(serial)
            if j["stage"] in ("Pre-EL", "Rework", "Post EL", "Quality Review")]


@test("NG at Pre-EL is followed by a Rework step and the next Pre-EL image - Cell "
      "Crack, rework, Pass - after Produced, before Anomaly and FQC; Post EL last")
def t_journey_cycle():
    fresh()
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg", "2026-10-14T13:07:34")
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + "_1.jpg", "2026-10-14T13:10:14")
    put(POST_B, "2026-10-15/晚班/OK", S_CRACK + ".jpg", "2026-10-16T01:12:56")
    run()
    # a tester row that never read, so the Anomaly step is there to be ordered against
    ss = os.path.join(TMP, "ftr.csv")
    with open(ss, "w", encoding="utf-8") as fh:
        fh.write(",".join(["2026-10-14 16:00:00", S_CRACK, "0.0055", "nan", "-0.898"]
                          + ["1"] * 10) + "\n")
    with store.conn() as (cx, cur):
        db.set_config(cur, {"ss_a_csv_path": ss})
    j = journey(S_CRACK)
    assert [x["stage"] for x in j] == [
        "Allocated", "Produced", "Pre-EL", "Rework", "Pre-EL", "Post EL", "Anomaly",
        "FQC", "Packed", "Challan", "Gate pass"], [x["stage"] for x in j]
    ng, rw, ok, post = j[2], j[3], j[4], j[5]
    assert (ng["value"], ng["tone"], ng["done"], ng["detail"], ng["tag"]) == \
        ("NG", "t-rev", True, ["Cell Crack", "Line A · primary"], "14-10-2026 13:07 · shift A"), ng
    assert (rw["value"], rw["done"], rw["detail"], rw["tag"]) == \
        ("Rework", True, ["after Cell Crack", "back at Pre-EL 14-10-2026 13:10"],
         "3 min"), rw
    assert (ok["value"], ok["tone"], ok["detail"], ok["tag"]) == \
        ("Pass", "t-pass", ["re-shot 1", "Line A · primary"], "14-10-2026 13:10 · shift A"), ok
    assert (post["value"], post["tone"], post["detail"], post["tag"]) == \
        ("Pass", "t-pass", ["Line B"], "16-10-2026 01:12 · shift C (15-10)"), post


@test("the Full event log lists every EL image - which machine, its folder, when taken "
      "and when found - and a Post EL NG's Needs Review item")
def t_event_log():
    fresh(pre_el2_a_root=PRE_A2)
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg", "2026-10-14T10:00:00")
    put(PRE_A2, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T12:05:00")
    put(POST_B, "2026-10-14/中班/Grid Burning", S_CRACK + ".jpg", "2026-10-14T16:00:00")
    run()
    r = signed_in().get("/api/trace/serial/" + S_CRACK).get_json()
    el = [(e["at"], e["stage"], e["reference"], e["detail"].split(" · found ")[0], e["user"])
          for e in r["events"] if e["stage"].startswith(("Pre-EL", "Post EL", "Needs Review"))]
    assert el[:3] == [
        ("2026-10-14T10:00:00", "Pre-EL · NG", "Line A · primary", "Cell Crack", "—"),
        ("2026-10-14T12:05:00", "Pre-EL · Pass", "Line A · secondary", "OK", "—"),
        ("2026-10-14T16:00:00", "Post EL · NG", "Line B · Post EL", "Grid Burning", "—")], el
    assert el[3][1:] == ("Needs Review · Post EL NG", S_CRACK,
                         "kept off the line for Quality to decide", "system"), el
    found = [e["detail"] for e in r["events"] if e["stage"] == "Pre-EL · NG"][0]
    assert " · found " in found, found
    stamps = [e["at"] for e in r["events"]]
    assert stamps == sorted(stamps), "the log is in time order"


@test("a serial NOT in the master that the EL PCs imaged: Search & Trace still says it is "
      "not in the master - and shows the EL steps and images it does have (EL Stations "
      "links it there); a serial with no images says only that")
def t_not_in_master_el():
    fresh()
    put(PRE_A, "2026-10-14/早班/Cell Crack", NOT_PLANNED + ".jpg", "2026-10-14T10:00:00")
    put(PRE_A, "2026-10-14/中班/OK", NOT_PLANNED + ".jpg", "2026-10-14T15:00:00")
    run()
    c = signed_in()
    r = c.get("/api/trace/serial/" + NOT_PLANNED)
    d = r.get_json()
    assert r.status_code == 404 and d["ok"] is False and "not in the serial master" in d["why"], d
    assert d["serial"] == NOT_PLANNED, d
    assert [(x["stage"], x["value"]) for x in d["el"]["journey"]] == [
        ("Pre-EL", "NG"), ("Rework", "Rework"), ("Pre-EL", "Pass")], d["el"]["journey"]
    assert [(e["stage"], e["reference"]) for e in d["el"]["events"]] == [
        ("Pre-EL · NG", "Line A · primary"), ("Pre-EL · Pass", "Line A · primary")], d["el"]["events"]
    r = c.get("/api/trace/serial/ICON625R12A1522998").get_json()
    assert "el" not in r and "not in the serial master" in r["why"], r


@test("NG, rework, NG, rework, Pass: the loop repeats until the module passes")
def t_journey_loop():
    fresh()
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_OLD + ".jpg", "2026-10-14T09:00:00")
    put(PRE_A, "2026-10-14/早班/Grid Burning", S_OLD + ".jpg", "2026-10-14T09:30:00")
    put(PRE_A, "2026-10-14/中班/OK", S_OLD + ".jpg", "2026-10-14T15:45:00")
    run()
    got = [(x["stage"], x["value"], x["tag"]) for x in el_part(S_OLD)]
    assert got == [("Pre-EL", "NG", "14-10-2026 09:00 · shift A"),
                   ("Rework", "Rework", "30 min"),
                   ("Pre-EL", "NG", "14-10-2026 09:30 · shift A"),
                   ("Rework", "Rework", "6 h 15 min"),
                   ("Pre-EL", "Pass", "14-10-2026 15:45 · shift B")], got
    assert el_part(S_OLD)[3]["detail"] == ["after Grid Burning",
                                           "back at Pre-EL 14-10-2026 15:45"]


@test("still NG at its last image: 'In rework', pending - nothing more is assumed")
def t_journey_in_rework():
    fresh()
    put(PRE_A, "2026-10-15/晚班/Cell Crack", S_CROSS + ".jpg", "2026-10-15T22:02:25")
    run()
    ng, rw = el_part(S_CROSS)
    assert (ng["value"], ng["detail"]) == ("NG", ["Cell Crack", "Line A · primary"]), ng
    assert (rw["stage"], rw["value"], rw["done"], rw["tag"], rw["tone"], rw["detail"]) == \
        ("Rework", "In rework", False, "pending", "t-rev",
         ["after Cell Crack", "no Pre-EL image since"]), rw
    assert [x["stage"] for x in journey(S_CROSS)][-4:] == ["FQC", "Packed", "Challan",
                                                           "Gate pass"]


@test("re-shot under its own name, as the real Pre-EL share does it: Ribbon short "
      "13:07, rework, OK 13:10")
def t_journey_same_name_reshot():
    fresh()
    put(PRE_A, "2026-10-15/早班/Ribbon short", S_CROSS + ".jpg", "2026-10-15T13:07:34")
    put(PRE_A, "2026-10-15/早班/OK", S_CROSS + ".jpg", "2026-10-15T13:10:14")
    run()
    got = [(x["stage"], x["value"]) for x in el_part(S_CROSS)]
    assert got == [("Pre-EL", "NG"), ("Rework", "Rework"), ("Pre-EL", "Pass")], got
    assert el_part(S_CROSS)[0]["detail"] == ["Ribbon short", "Line A · primary"]


@test("an image re-filed under another verdict is ONE image: its latest filing "
      "stands - not a Pass and then an NG")
def t_journey_refiled():
    fresh()
    p = put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T13:07:34")
    run()
    d = os.path.join(PRE_A, "2026-10-14", "早班", "Cell Crack")
    os.makedirs(d)
    os.replace(p, os.path.join(d, S_CRACK + ".jpg"))         # the operator re-files it
    assert run() == {"pre_el": 1}                            # both filings are on record
    got = [(x["stage"], x["value"]) for x in el_part(S_CRACK)]
    assert got == [("Pre-EL", "NG"), ("Rework", "In rework")], got


@test("time orders the images, not the re-shot number: each machine numbers its "
      "own re-shots (Mukesh: 'here time is crucial')")
def t_journey_order_rule():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_OLD + ".jpg", "2026-10-14T10:00:00")
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_OLD + "_2.jpg", "2026-10-14T09:00:00")
    run()
    got = [(x["stage"], x["value"]) for x in el_part(S_OLD)]
    assert got == [("Pre-EL", "NG"), ("Rework", "Rework"), ("Pre-EL", "Pass")], got
    assert el_part(S_OLD)[0]["detail"] == ["Cell Crack", "re-shot 2", "Line A · primary"]


@test("an NG at the primary Pre-EL, reworked, comes back through the SECONDARY: "
      "both machines are read, their images put in order by time - one cycle")
def t_two_machines_one_cycle():
    fresh(pre_el2_a_root=PRE_A2)
    # each machine names the module its own way - both files are <serial>.jpg
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg", "2026-10-14T10:00:00")
    put(PRE_A2, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T12:05:00")
    assert run() == {"pre_el": 2}
    rows = captures(S_CRACK)
    assert [(r["unit"], r["verdict"], r["line"]) for r in rows] == \
        [(1, "Cell Crack", "A"), (2, "OK", "A")], [dict(r) for r in rows]
    got = [(x["stage"], x["value"], x["detail"]) for x in el_part(S_CRACK)]
    assert got == [("Pre-EL", "NG", ["Cell Crack", "Line A · primary"]),
                   ("Rework", "Rework", ["after Cell Crack", "back at Pre-EL 14-10-2026 12:05"]),
                   ("Pre-EL", "Pass", ["Line A · secondary"])], got
    s = elcap.summary("pre_el", rows)
    assert (s["status"], s["units"]) == ("reworked", [1, 2]), s


@test("the secondary's own NG goes back through the primary just the same")
def t_two_machines_other_way():
    fresh(pre_el2_a_root=PRE_A2)
    put(PRE_A2, "2026-10-14/中班/Grid Burning", S_OLD + ".jpg", "2026-10-14T15:00:00")
    put(PRE_A, "2026-10-14/中班/Cross", S_OLD + ".jpg", "2026-10-14T16:00:00")
    put(PRE_A2, "2026-10-14/中班/OK", S_OLD + "_1.jpg", "2026-10-14T17:30:00")
    run()
    got = [(x["stage"], x["value"], x["detail"][-1]) for x in el_part(S_OLD)]
    assert got == [("Pre-EL", "NG", "Line A · secondary"),
                   ("Rework", "Rework", "back at Pre-EL 14-10-2026 16:00"),
                   ("Pre-EL", "NG", "Line A · primary"),
                   ("Rework", "Rework", "back at Pre-EL 14-10-2026 17:30"),
                   ("Pre-EL", "Pass", "Line A · secondary")], got


@test("a database whose el_capture predates the secondary machine gets the unit "
      "column, and its rows are the primary's")
def t_unit_migration():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")
    run()
    with store.conn() as (cx, cur):          # the table exactly as it was on 15 Oct
        cur.execute("CREATE TABLE el_old (capture_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "station TEXT NOT NULL, line TEXT NULL, serial TEXT NOT NULL, "
                    "recapture INTEGER NOT NULL DEFAULT 0, verdict TEXT NOT NULL, "
                    "path TEXT NOT NULL COLLATE NOCASE, file_time TEXT NOT NULL, "
                    "seen_at TEXT NOT NULL, UNIQUE (station, path))")
        cur.execute("INSERT INTO el_old SELECT capture_id, station, line, serial, recapture, "
                    "verdict, path, file_time, seen_at FROM el_capture")
        cur.execute("DROP TABLE el_capture")
        cur.execute("ALTER TABLE el_old RENAME TO el_capture")
    store._ready = False
    store.ensure()
    assert [(r["unit"], r["serial"]) for r in captures()] == [(1, S_CRACK)]
    assert run() == {}, "the migrated rows must still be recognised"
    with store.conn() as (cx, cur):
        db.set_config(cur, {"pre_el2_a_root": PRE_A2})
    put(PRE_A2, "2026-10-14/中班/OK", S_CROSS + ".jpg")
    assert run() == {"pre_el": 1}
    assert [(r["unit"], r["serial"]) for r in captures()] == [(1, S_CRACK), (2, S_CROSS)]


@test("Post EL NG is a rejection: one step, NG in red with its reason, no Rework - "
      "and a later OK image does not undo it")
def t_journey_post_el_ng():
    fresh()
    put(POST_B, "2026-10-14/中班/Cell Crack", S_POST + ".jpg", "2026-10-14T16:00:00")
    put(POST_B, "2026-10-14/中班/OK", S_POST + "_1.jpg", "2026-10-14T16:30:00")
    run()
    got = el_part(S_POST)
    assert [x["stage"] for x in got] == ["Post EL", "Quality Review"], [x["stage"] for x in got]
    post, q = got
    assert (post["value"], post["tone"], post["tag"]) == \
        ("NG", "t-fail", "14-10-2026 16:00 · shift B"), post
    assert post["detail"] == ["Cell Crack", "Cell Crack · 14-10-2026 16:00",
                              "OK · 14-10-2026 16:30", "Line B"], post["detail"]
    # NG at Post EL is Quality's to decide - never "rejected" (Mukesh, 16 Oct)
    assert not any("rejected" in d for d in post["detail"]), post["detail"]
    assert (q["value"], q["done"], q["tag"], q["tone"], q["detail"]) == \
        ("—", False, "pending", "t-rev",
         ["awaiting Quality", "kept off the line (Needs Review)"]), q


@test("Post EL with more than four images lists the four latest, the rest counted")
def t_journey_post_many():
    fresh()
    for i in range(6):
        put(POST_B, "2026-10-14/早班/OK", S_POST + ("_%d.jpg" % i if i else ".jpg"),
            "2026-10-14T1%d:00:00" % i)
    run()
    post = el_part(S_POST)[0]
    assert post["value"] == "Pass" and post["detail"] == [
        "+2 earlier", "OK · 14-10-2026 12:00", "OK · 14-10-2026 13:00",
        "OK · 14-10-2026 14:00", "OK · 14-10-2026 15:00", "Line B"], post


@test("'Pass' and ' ok ' are Pass, as on the FQC screen; no Post EL image, no step")
def t_journey_clean_words():
    fresh(post_el_b_root="")
    put(PRE_A, "2026-10-14/早班/Pass", S_OLD + ".jpg")
    put(PRE_A, "2026-10-14/早班/ ok", S_STRAY + ".jpg")
    run()
    for s in (S_OLD, S_STRAY):
        assert [(x["stage"], x["value"], x["tone"]) for x in el_part(s)] == \
            [("Pre-EL", "Pass", "t-pass")], el_part(s)


@test("one folder serving both lines claims no line; a step from a Line B folder says B")
def t_journey_lines():
    fresh(pre_el_b_root=PRE_A)
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T09:00:00")
    run()
    assert el_part(S_CRACK)[0]["detail"] == ["primary"]
    with store.conn() as (cx, cur):
        db.set_config(cur, {"pre_el_b_root": PRE_B})
    put(PRE_B, "2026-10-14/中班/Cell Crack", S_CRACK + "_1.jpg", "2026-10-14T15:00:00")
    run()
    assert el_part(S_CRACK)[1]["detail"] == ["Cell Crack", "re-shot 1", "Line B · primary"]


@test("what a module's images add up to, per station: Pass first time, Pass after "
      "rework, In rework; at Post EL Pass, or NG - Quality's to decide - once any "
      "image is NG")
def t_summary():
    def rows(*vs):
        return [{"capture_id": i, "recapture": 0, "file_time": "2026-10-14T1%d:00:00" % i,
                 "seen_at": "x", "verdict": v, "line": "B"} for i, v in enumerate(vs)]
    s = elcap.summary
    assert s("pre_el", []) is None
    assert s("pre_el", rows("OK"))["status"] == "pass"
    r = s("pre_el", rows("Cell Crack", "Cross", "OK"))
    assert (r["status"], r["label"], r["reworks"], r["reason"], r["images"]) == \
        ("reworked", "Pass after rework", 2, "Cross", 3), r
    r = s("pre_el", rows("OK", "Cell Crack"))
    assert (r["status"], r["label"], r["reason"]) == ("in_rework", "In rework", "Cell Crack")
    assert r["first_at"] == "2026-10-14T10:00:00" and r["lines"] == ["B"]
    r = s("post_el", rows("Cell Crack", "OK"))
    assert (r["status"], r["label"], r["reason"], r["reworks"]) == \
        ("ng", "NG", "Cell Crack", 0), r
    assert s("post_el", rows("OK", " pass "))["status"] == "pass"


@test("the journey reads el_capture, never the shares: a share gone, the steps stay")
def t_journey_reads_table_only():
    fresh()
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg")
    run()
    shutil.rmtree(PRE_A)
    import os as _os
    real = _os.scandir

    def no_share(path="."):
        raise AssertionError("the journey read a folder: %s" % path)

    _os.scandir = no_share
    try:
        assert [x["value"] for x in el_part(S_CRACK)] == ["NG", "In rework"]
    finally:
        _os.scandir = real


# --------------------------------------------------------------------------
# 8. the EL Stations screen
# --------------------------------------------------------------------------

def seed_day():
    """The 14th: a module reworked and passed (then Post EL OK), one passed
    first time, one still in rework (C shift), one NG at Post EL (Quality's to
    decide), one the master does not have - and one first imaged on the 13th."""
    fresh()
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg", "2026-10-14T09:00:00")
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + "_1.jpg", "2026-10-14T09:30:00")
    put(POST_B, "2026-10-14/中班/OK", S_CRACK + ".jpg", "2026-10-14T14:10:00")
    put(PRE_A, "2026-10-14/早班/OK", S_CROSS + ".jpg", "2026-10-14T10:00:00")
    put(PRE_A, "2026-10-14/晚班/Cell Crack", S_OLD + ".jpg", "2026-10-14T23:30:00")
    put(POST_B, "2026-10-14/中班/Cell Crack", S_POST + ".jpg", "2026-10-14T16:00:00")
    put(PRE_A, "2026-10-14/中班/OK", NOT_PLANNED + ".jpg", "2026-10-14T15:00:00")
    put(PRE_A, "2026-10-13/中班/Grid Burning", S_STRAY + ".jpg", "2026-10-13T20:00:00")
    put(PRE_A, "2026-10-14/早班/OK", S_STRAY + ".jpg", "2026-10-14T08:00:00")
    run()


def el_api(c=None, **q):
    c = c or signed_in()
    r = c.get("/api/el/stations", query_string=q)
    return r.status_code, r.get_json()


@test("EL Stations: the period's modules by their first image - KPIs, one row a "
      "module with both stations' story, a module the master lacks included")
def t_screen_api():
    seed_day()
    code, d = el_api(**{"from": "2026-10-14", "to": "2026-10-14"})
    assert code == 200 and d["ok"], d
    assert d["kpi"] == {"pre_el": {"scanned": 4, "pass": 2, "reworked": 1, "in_rework": 1,
                                   "rework": 2, "fpy": 50.0},
                        "post_el": {"scanned": 2, "pass": 1, "ng": 1, "awaiting": 1}}, d["kpi"]
    rows = {r["serial"]: r for r in d["rows"]}
    assert set(rows) == {S_CRACK, S_CROSS, S_OLD, S_POST, NOT_PLANNED}, sorted(rows)
    c = rows[S_CRACK]
    assert (c["pre"]["label"], c["pre"]["reworks"], c["pre"]["reason"], c["pre"]["images"]) == \
        ("Pass after rework", 1, "Cell Crack", 2), c["pre"]
    assert c["post"]["label"] == "Pass" and c["model"] == "ISEN625-G12R" and c["lines"] == ["A", "B"]
    p = rows[S_POST]
    assert p["pre"] is None and (p["post"]["label"], p["post"]["reason"],
                                 p["post_review"]) == ("NG", "Cell Crack", "awaiting"), p
    assert c["post_review"] is None, c
    assert rows[S_OLD]["pre"]["label"] == "In rework"
    assert rows[NOT_PLANNED]["in_master"] is False and rows[NOT_PLANNED]["model"] is None
    assert [r["serial"] for r in d["rows"]][0] == S_OLD, "newest activity first"
    assert d["facets"] == {"shift": ["A", "B", "C"], "station": ["pre_el", "post_el"],
                           "line": ["A", "B"],
                           "result": ["Pre-EL: Pass", "Pre-EL: Pass after rework",
                                      "Pre-EL: In rework", "Post EL: Pass",
                                      "Post EL: NG"]}, d["facets"]
    assert d["configured"] == {"pre_el": True, "post_el": True}
    # the 13th's module is the 13th's, its image on the 14th notwithstanding
    code, d13 = el_api(**{"from": "2026-10-13", "to": "2026-10-13"})
    assert [r["serial"] for r in d13["rows"]] == [S_STRAY], d13["rows"]
    assert d13["rows"][0]["pre"]["label"] == "Pass after rework"


@test("EL Stations filters: Shift, Station and Line ask of the first image, Result "
      "of what the images add up to - each dropdown offered under the OTHERS")
def t_screen_filters():
    seed_day()
    day = {"from": "2026-10-14", "to": "2026-10-14"}
    _c, d = el_api(shift="C", **day)
    assert [r["serial"] for r in d["rows"]] == [S_OLD], d["rows"]
    assert d["facets"]["shift"] == ["A", "B", "C"], "its own pick must not hide its siblings"
    assert d["facets"]["station"] == ["pre_el"], d["facets"]
    assert d["kpi"]["pre_el"]["scanned"] == 1 and d["kpi"]["post_el"]["scanned"] == 0
    _c, d = el_api(result="Post EL: NG", **day)
    assert [r["serial"] for r in d["rows"]] == [S_POST], d["rows"]
    _c, d = el_api(station="post_el", **day)
    assert {r["serial"] for r in d["rows"]} == {S_CRACK, S_POST}, d["rows"]
    assert d["facets"]["shift"] == ["B"], d["facets"]
    _c, d = el_api(line="A", **day)
    assert S_POST not in {r["serial"] for r in d["rows"]} and len(d["rows"]) == 4, d["rows"]
    code, d = el_api(station="nowhere", **day)
    assert code == 400


@test("EL Stations: no dates means today's factory day; a date that is not one is refused")
def t_screen_dates():
    fresh()
    code, d = el_api()
    assert code == 200 and d["from"] == d["to"] == clock.shift_day().isoformat(), d
    assert d["rows"] == [] and d["kpi"]["pre_el"]["scanned"] == 0
    assert d["configured"] == {"pre_el": True, "post_el": True}
    code, d = el_api(**{"from": "14-10-2026"})
    assert code == 400, d


@test("EL Stations: a station with no folder set says so, rather than a plain 0")
def t_screen_unconfigured():
    fresh(post_el_b_root="")
    _c, d = el_api()
    assert d["configured"] == {"pre_el": True, "post_el": False}, d["configured"]


@test("EL Stations: more modules than the cap - the newest are sent, the total said")
def t_screen_cap():
    seed_day()
    cap = APP._EL_ROW_CAP
    APP._EL_ROW_CAP = 2
    try:
        _c, d = el_api(**{"from": "2026-10-14", "to": "2026-10-14"})
    finally:
        APP._EL_ROW_CAP = cap
    assert len(d["rows"]) == 2 and d["total"] == 5 and d["cap"] == 2, d


@test("EL Stations opens for Production Incharge, Admin and Super Admin; another role "
      "is refused - by the API and by the screen's own markup")
def t_screen_gate():
    fresh()
    for role, want in (("Production Incharge", 200), ("Admin", 200), ("Super Admin", 200),
                       ("Quality", 403), ("FQC Operator", 403)):
        c = APP.app.test_client()
        AUTH.test_login(c, role=role)
        assert c.get("/api/el/stations").status_code == want, role
        assert c.get("/view/el-stations").status_code == want, role
    c = APP.app.test_client()
    assert c.get("/api/el/stations").status_code == 401


@test("accounts made before EL Stations existed are given it once, by role - and an "
      "Admin's later choice is never undone")
def t_grant_later_screens():
    import icon_auth
    fresh()
    who = {}
    for role in ("Production Incharge", "Admin", "Super Admin", "Quality", "FQC Operator"):
        who[role] = AUTH.make_user(role)["login_id"]
    with store.conn() as (cx, cur):                # as if made before the screen
        cur.execute("DELETE FROM user_screen_perm WHERE screen_id='elst'")
        assert all(not icon_auth.get_screen_perms(cur, l)["elst"]["view"] for l in who.values())
        got = icon_auth.grant_later_screens(cur)
    assert got == {who["Production Incharge"]: ["elst"], who["Admin"]: ["elst"],
                   who["Super Admin"]: ["elst"]}, got
    with store.conn() as (cx, cur):
        perms = {r: icon_auth.get_screen_perms(cur, l)["elst"] for r, l in who.items()}
        logged = store.rows(cur, "SELECT login_id, detail FROM auth_event WHERE "
                                 "event='screen_perms_set' AND detail LIKE 'by system:%'")
        rows = store.one(cur, "SELECT COUNT(*) AS n FROM user_screen_perm "
                              "WHERE screen_id='elst'")["n"]
    assert perms["Production Incharge"] == {"view": True, "write": False}, perms
    assert perms["Quality"] == {"view": False, "write": False}, perms
    assert rows == 5, "every account gets an explicit row"
    assert sorted(r["login_id"] for r in logged) == sorted(
        who[r] for r in ("Production Incharge", "Admin", "Super Admin")), logged
    assert all("elst" in r["detail"] and "role's default" in r["detail"] for r in logged), logged
    # an Admin takes it away from the incharge, and gives it to Quality
    with store.conn() as (cx, cur):
        icon_auth.set_screen_perms(cur, who["Super Admin"], who["Production Incharge"],
                                   {"elst": {"view": False, "write": False}})
        icon_auth.set_screen_perms(cur, who["Super Admin"], who["Quality"],
                                   {"elst": {"view": True, "write": False}})
        assert icon_auth.grant_later_screens(cur) == {}
        assert icon_auth.get_screen_perms(cur, who["Production Incharge"])["elst"]["view"] is False
        assert icon_auth.get_screen_perms(cur, who["Quality"])["elst"]["view"] is True


@test("the dashboards' EL figures (/api/prod/dashboard): the same counts as EL "
      "Stations, under the dashboard's own period, shift, customer, model and wattage")
def t_dashboard_el():
    seed_day()
    c = signed_in()

    def el(**q):
        r = c.get("/api/prod/dashboard", query_string=dict(
            {"from": "2026-10-14", "to": "2026-10-14"}, **q))
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    d = el()
    _c, screen = el_api(c, **{"from": "2026-10-14", "to": "2026-10-14"})
    assert d["el"] == screen["kpi"], (d["el"], screen["kpi"])
    assert d["el_configured"] == {"pre_el": True, "post_el": True}
    # a model (or customer, or wattage) narrows to modules the master has
    m = el(model="ISEN625-G12R")["el"]
    assert m["pre_el"]["scanned"] == 3 and m["post_el"]["scanned"] == 2, m
    assert el(model="ISEN600-G2X")["el"]["pre_el"]["scanned"] == 0
    assert el(customer="STOCK")["el"]["pre_el"]["scanned"] == 3
    assert el(wattage="625")["el"]["pre_el"]["scanned"] == 3
    s = el(shift="C")["el"]
    assert (s["pre_el"]["scanned"], s["pre_el"]["in_rework"], s["post_el"]["scanned"]) == \
        (1, 1, 0), s


# --------------------------------------------------------------------------
# 9. a Post EL rejection goes to Needs Review
# --------------------------------------------------------------------------

@test("an NG at Post EL raises one Needs Review item for Quality - once a module, and "
      "quietly; an OK, or an NG at Pre-EL, raises none")
def t_post_el_review_raised():
    fresh()
    put(POST_B, "2026-10-14/中班/Cell Crack", S_POST + ".jpg", "2026-10-14T16:00:00")
    put(POST_B, "2026-10-14/中班/OK", S_CROSS + ".jpg", "2026-10-14T16:05:00")
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CRACK + ".jpg")
    assert run() == {"pre_el": 1, "post_el": 2, "post_el_ng": 1}
    with store.conn() as (cx, cur):
        items = store.rows(cur, "SELECT * FROM review_item WHERE type='post_el_ng'")
    assert [(i["serial"], i["status"], i["source"], i["line"], i["event_at"], i["raw_id"],
             i["created_by"]) for i in items] == \
        [(S_POST, "open", "el_capture", "B", "2026-10-14T16:00:00", "post_el_ng|" + S_POST,
          "system")], [dict(i) for i in items]
    # another NG image of it, and a later OK: nothing more - the rejection stands
    put(POST_B, "2026-10-14/中班/Grid Burning", S_POST + "_1.jpg", "2026-10-14T16:30:00")
    put(POST_B, "2026-10-14/晚班/OK", S_POST + "_2.jpg", "2026-10-14T22:30:00")
    assert run() == {"post_el": 2}
    with store.conn() as (cx, cur):
        assert store.one(cur, "SELECT COUNT(*) AS n FROM review_item WHERE "
                              "type='post_el_ng'")["n"] == 1
        before = cx.total_changes
        assert elcap.run(db.get_config(cur), cur) == {}
        assert cx.total_changes == before and cur.written == set()


@test("Needs Review lists a Post EL NG under Quality with its folder; Quality decide - "
      "close it as reviewed, with a reason - an Incharge may not; the badge counts it; "
      "the journey's Quality Review step says who and why")
def t_post_el_review_flow():
    fresh()
    put(POST_B, "2026-10-14/中班/Cell Crack", S_POST + ".jpg", "2026-10-14T16:00:00")
    run()
    q = APP.app.test_client()
    who = AUTH.test_login(q, role="Quality")
    pi = APP.app.test_client()
    AUTH.test_login(pi, role="Production Incharge")
    mine = [i for i in q.get("/api/review").get_json() if i["type"] == "post_el_ng"]
    assert len(mine) == 1, mine
    it = mine[0]
    assert (it["serial"], it["flag"], it["stage"], it["locked"], it["model"]) == \
        (S_POST, "Post EL NG", "Post EL · Line B", False, "ISEN625-G12R"), it
    assert it["detail"].startswith("Cell Crack at Post EL") and "kept off the line" in \
        it["detail"] and "Quality to decide" in it["detail"], it["detail"]
    assert "rejected" not in it["detail"] + it["flag"], it
    assert [i for i in pi.get("/api/review").get_json()
            if i["type"] == "post_el_ng"][0]["locked"] is True
    with store.conn() as (cx, cur):
        counts = db.review_open_counts(cur)
    assert counts["total"] == 1, counts          # the badge counts it

    r = pi.post("/api/review/resolve", json={"type": "post_el_ng", "id": it["id"],
                                            "reason": "looked at it"})
    assert r.status_code == 403, r.get_json()
    r = q.post("/api/review/resolve", json={"type": "post_el_ng", "id": it["id"],
                                           "reason": "  "})
    assert r.status_code == 400, r.get_json()
    r = q.post("/api/review/resolve", json={"type": "post_el_ng", "id": it["id"],
                                           "reason": "crack confirmed - scrapped"})
    assert r.status_code == 200 and r.get_json()["resolution"] == "reviewed", r.get_json()
    assert not [i for i in q.get("/api/review").get_json() if i["type"] == "post_el_ng"]
    with store.conn() as (cx, cur):
        assert db.review_open_counts(cur)["total"] == counts["total"] - 1
        row = store.one(cur, "SELECT * FROM review_item WHERE type='post_el_ng'")
    assert (row["status"], row["resolution"], row["reason"], row["resolved_by"]) == \
        ("resolved", "reviewed", "crack confirmed - scrapped", who["name"]), dict(row)
    r = q.post("/api/review/resolve", json={"type": "post_el_ng", "id": it["id"],
                                           "reason": "again"})
    assert r.status_code == 400 and "already resolved" in r.get_json()["why"]
    post, q = el_part(S_POST)
    assert post["detail"] == ["Cell Crack", "Line B"], post["detail"]
    assert (q["stage"], q["value"], q["done"], q["tone"], q["detail"]) == \
        ("Quality Review", "Reviewed", True, "t-mute",
         ["crack confirmed - scrapped", "Quality: " + who["name"]]), q
    assert q["tag"].startswith(clock.now().strftime("%d-%m-%Y")), q["tag"]


# --------------------------------------------------------------------------
# 10. the EL PCs' clocks
# --------------------------------------------------------------------------

def seed_clocks():
    """Four machines, as the poller would have recorded them: (unit, line,
    file_time, seen_at) - each machine's first pass three hours ago (a backlog),
    then images recorded as they came."""
    now = clock.now()
    h = datetime.timedelta
    iso = lambda t: t.isoformat(timespec="seconds")
    first = now - h(hours=3)
    rows = [
        # Line B primary: its clock 3 min AHEAD - an image "taken" after it was seen
        (1, "B", iso(first - h(days=1)), iso(first)),
        (1, "B", iso(now - h(minutes=60) + h(minutes=3)), iso(now - h(minutes=60) + h(seconds=20))),
        # Line B secondary: 22 min BEHIND (and one image filed late, 40 min)
        (2, "B", iso(first - h(days=2)), iso(first)),
        (2, "B", iso(now - h(minutes=52)), iso(now - h(minutes=30))),
        (2, "B", iso(now - h(minutes=50)), iso(now - h(minutes=10))),
        # Line A primary: in step - seen 30 s after it was taken
        (1, "A", iso(first - h(hours=5)), iso(first)),
        (1, "A", iso(now - h(minutes=5, seconds=30)), iso(now - h(minutes=5))),
        # Line A secondary: only its first pass so far - two days of old images
        (2, "A", iso(now - h(days=2)), iso(now - h(minutes=1))),
        (2, "A", iso(now - h(hours=7)), iso(now - h(minutes=1))),
    ]
    with store.conn() as (cx, cur):
        for i, (unit, line, ft, seen) in enumerate(rows):
            cur.execute("INSERT INTO el_capture (station, unit, line, serial, recapture, "
                        "verdict, path, file_time, seen_at) VALUES ('pre_el', %s, %s, %s, "
                        "0, 'OK', %s, %s, %s)", (unit, line, "ICON625R12A16%05d" % i,
                                                 "c:/clk/%d.jpg" % i, ft, seen))


@test("each EL PC's clock against the server's, from the images recorded as they came: "
      "ahead, 22 min behind, in step - and a machine with only its first pass's "
      "backlog is not measured, so not flagged")
def t_clocks():
    fresh()
    seed_clocks()
    with store.conn() as (cx, cur):
        c = elcap.clocks(cur)
    assert (c[("pre_el", 1, "B")]["flag"], c[("pre_el", 1, "B")]["minutes"]) == ("ahead", 3), c
    assert (c[("pre_el", 2, "B")]["flag"], c[("pre_el", 2, "B")]["minutes"],
            c[("pre_el", 2, "B")]["n"]) == ("behind", 22, 2), c
    assert c[("pre_el", 1, "A")]["flag"] is None, c
    assert ("pre_el", 2, "A") not in c, "a first pass's backlog is not a clock reading"
    assert "3 min AHEAD" in elcap.clock_text(c[("pre_el", 1, "B")])
    assert "22 min BEHIND" in elcap.clock_text(c[("pre_el", 2, "B")])
    assert elcap.clock_text(c[("pre_el", 1, "A")]).startswith("Clock in step")
    assert elcap.clock_text(None).startswith("Clock not measured yet")


@test("Evidence Sources shows each configured machine's clock under its folder, a "
      "flagged one in the warning colour; EL Stations names the flagged machines")
def t_clocks_shown():
    fresh(pre_el_b_root=PRE_B, pre_el2_b_root=PRE_A2, pre_el2_a_root=PRE_A2.upper())
    seed_clocks()
    raw = signed_in().get("/view/settings").get_data(as_text=True)
    html = " ".join(raw.split())
    assert "Clock about 22 min BEHIND the server" in html, "no clock for B's secondary"
    assert "Clock about 3 min AHEAD of the server" in html
    assert "Clock in step with the server" in html                  # A's primary
    assert "Clock not measured yet" in html                         # A's secondary
    assert html.count('class="hint el-clock" style="color:var(--review);font-weight:600"') == 2
    _c, d = el_api()
    assert d["clock_warnings"] == [
        "Pre-EL primary, Line B: Clock about 3 min AHEAD of the server - its images are put "
        "in order by their time, so fix the EL PC's clock.",
        "Pre-EL secondary, Line B: Clock about 22 min BEHIND the server (or every image is "
        "filed late) - its images are put in order by their time, so check the EL PC's "
        "clock."], d["clock_warnings"]


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")   # a FAIL naming a folder like
    # 早班 must print on a cp1252 console, not crash the run
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    try:
        for name, fn in _results:
            try:
                fn()
                print("  PASS  %s" % name)
                passed += 1
            except Exception as e:
                print("  FAIL  %s  %s" % (name, e))
                if "-v" in sys.argv:
                    traceback.print_exc()
                failed += 1
        print("\n%d passed, %d failed" % (passed, failed))
    finally:
        try:
            store.wipe()
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
