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
    for d in (PRE_A, PRE_B, POST_B):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    conf = {"el_root": "", "el_a_root": "", "el_b_root": "",
            "pre_el_a_root": PRE_A, "pre_el_b_root": "",
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
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T09:00:00")
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_CROSS + ".jpg", "2026-10-14T09:01:00")
    seen = []

    class H(logging.Handler):
        def emit(self, rec):
            seen.append(rec.getMessage())

    h = H()
    elcap.log.addHandler(h)
    level = elcap.log.level
    elcap.log.setLevel(logging.INFO)
    try:
        assert elcap.run_pass() == {"pre_el": 2}
        for i in range(12):
            put(PRE_A, "2026-10-14/中班/OK", "ICON625R12A15229%02d.jpg" % (40 + i),
                "2026-10-14T15:%02d:00" % i)
        assert elcap.run_pass() == {"pre_el": 12}
    finally:
        elcap.log.removeHandler(h)
        elcap.log.setLevel(level)
    assert len(seen) == 2, seen
    assert "Pre-EL: %s OK (A), %s Cell Crack (A)" % (S_CRACK, S_CROSS) in seen[0], seen[0]
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
    assert cols == ["capture_id", "station", "line", "serial", "recapture", "verdict",
                    "path", "file_time", "seen_at"], cols
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
    assert "FQC EL folder of Line B" in why and "Pre-EL folder of Line B" in why, why
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
    assert stored("pre_el_a_root") == "" and stored("post_el_a_root") == ""


@test("the same folder for one station on both lines is allowed: one machine "
      "serving both lines")
def t_settings_one_folder_both_lines():
    fresh(el_a_root=FQC_EL, el_b_root=FQC_EL, pre_el_a_root="", post_el_b_root="")
    r = signed_in().post("/api/settings", json={
        "pre_el_a_root": PRE_A, "pre_el_b_root": PRE_A.lower() + "\\",
        "post_el_a_root": POST_B, "post_el_b_root": POST_B})
    assert r.status_code == 200, r.get_json()
    assert stored("pre_el_a_root") == PRE_A and stored("post_el_b_root") == POST_B


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


@test("Evidence Sources shows both new folders on each line, with a reachability "
      "tag and the hint that the server reads them")
def t_settings_page():
    fresh(pre_el_b_root=os.path.join(TMP, "switched_off"))
    html = " ".join(signed_in().get("/view/settings").get_data(as_text=True).split())
    for ln in ("a", "b"):
        assert 'id="s_%s_pre_el"' % ln in html and 'id="s_%s_post_el"' % ln in html, ln
    assert html.count("Pre-EL image root folder") == 2, html.count("Pre-EL image root folder")
    assert html.count("Post EL (after lamination) image root folder") == 2
    assert html.count("Read by the server every minute, not by FQC; the account the "
                      "server runs as needs read access to the share.") == 4
    assert "Pre-EL OK" in html and "Post EL OK" in html          # A's Pre-EL, B's Post EL
    assert "Pre-EL NC" in html and "Unreachable: %s" % os.path.join(TMP, "switched_off") in html
    assert "Pre-EL —" not in html and "Post EL —" in html        # A's Post EL is blank
    assert "No Post EL folder configured for this line." in html
    assert "body['pre_el_'+ln+'_root']" in html and "body['post_el_'+ln+'_root']" in html


@test("/api/evidence/sources lists Pre-EL and Post EL for each line, with their state")
def t_sources_api():
    fresh(pre_el_b_root=os.path.join(TMP, "switched_off"))
    rows = {r["id"]: r for r in signed_in().get("/api/evidence/sources").get_json()}
    assert {"PRE-EL-A", "PRE-EL-B", "POST-EL-A", "POST-EL-B"} <= set(rows), sorted(rows)
    assert rows["PRE-EL-A"]["state"] == "OK" and rows["PRE-EL-A"]["path"] == PRE_A
    assert rows["PRE-EL-B"]["state"] == "NC"
    assert rows["POST-EL-A"]["state"] == "—" and rows["POST-EL-B"]["state"] == "OK"
    assert rows["POST-EL-B"]["type"] == "POST_EL_ROOT" and rows["PRE-EL-A"]["line"] == "A"
    assert "every minute" in rows["PRE-EL-A"]["rule"]


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
    return [j for j in journey(serial) if j["stage"] in ("Pre-EL", "Rework", "Post EL")]


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
        ("NG", "t-rev", True, ["Cell Crack", "Line A"], "14-10-2026 13:07 · shift A"), ng
    assert (rw["value"], rw["done"], rw["detail"], rw["tag"]) == \
        ("Rework", True, ["after Cell Crack", "back at Pre-EL 14-10-2026 13:10"],
         "3 min"), rw
    assert (ok["value"], ok["tone"], ok["detail"], ok["tag"]) == \
        ("Pass", "t-pass", ["re-shot 1", "Line A"], "14-10-2026 13:10 · shift A"), ok
    assert (post["value"], post["tone"], post["detail"], post["tag"]) == \
        ("Pass", "t-pass", ["Line B"], "16-10-2026 01:12 · shift C (15-10)"), post


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
    assert (ng["value"], ng["detail"]) == ("NG", ["Cell Crack", "Line A"]), ng
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
    assert el_part(S_CROSS)[0]["detail"] == ["Ribbon short", "Line A"]


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


@test("the re-shot number orders the images before the time does")
def t_journey_order_rule():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_OLD + ".jpg", "2026-10-14T10:00:00")
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_OLD + "_2.jpg", "2026-10-14T09:00:00")
    run()
    got = [(x["stage"], x["value"]) for x in el_part(S_OLD)]
    assert got == [("Pre-EL", "Pass"), ("Pre-EL", "NG"), ("Rework", "In rework")], got
    assert el_part(S_OLD)[1]["detail"] == ["Cell Crack", "re-shot 2", "Line A"]


@test("Post EL NG is a rejection: one step, NG in red with its reason, no Rework - "
      "and a later OK image does not undo it")
def t_journey_post_el_ng():
    fresh()
    put(POST_B, "2026-10-14/中班/Cell Crack", S_POST + ".jpg", "2026-10-14T16:00:00")
    put(POST_B, "2026-10-14/中班/OK", S_POST + "_1.jpg", "2026-10-14T16:30:00")
    run()
    got = el_part(S_POST)
    assert [x["stage"] for x in got] == ["Post EL"], [x["stage"] for x in got]
    post = got[0]
    assert (post["value"], post["tone"], post["tag"]) == \
        ("NG", "t-fail", "14-10-2026 16:00 · shift B"), post
    assert post["detail"] == ["Cell Crack", "rejected - no rework after lamination",
                              "Cell Crack · 14-10-2026 16:00", "OK · 14-10-2026 16:30",
                              "Line B"], post["detail"]


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
    assert el_part(S_CRACK)[0]["detail"] == []
    with store.conn() as (cx, cur):
        db.set_config(cur, {"pre_el_b_root": PRE_B})
    put(PRE_B, "2026-10-14/中班/Cell Crack", S_CRACK + "_1.jpg", "2026-10-14T15:00:00")
    run()
    assert el_part(S_CRACK)[1]["detail"] == ["Cell Crack", "re-shot 1", "Line B"]


@test("what a module's images add up to, per station: Pass first time, Pass after "
      "rework, In rework; at Post EL Pass, or NG - rejected - once any image is NG")
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
        ("ng", "NG - rejected", "Cell Crack", 0), r
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
    first time, one still in rework (C shift), one rejected at Post EL, one the
    master does not have - and one first imaged on the 13th."""
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
                        "post_el": {"scanned": 2, "pass": 1, "ng": 1}}, d["kpi"]
    rows = {r["serial"]: r for r in d["rows"]}
    assert set(rows) == {S_CRACK, S_CROSS, S_OLD, S_POST, NOT_PLANNED}, sorted(rows)
    c = rows[S_CRACK]
    assert (c["pre"]["label"], c["pre"]["reworks"], c["pre"]["reason"], c["pre"]["images"]) == \
        ("Pass after rework", 1, "Cell Crack", 2), c["pre"]
    assert c["post"]["label"] == "Pass" and c["model"] == "ISEN625-G12R" and c["lines"] == ["A", "B"]
    p = rows[S_POST]
    assert p["pre"] is None and (p["post"]["label"], p["post"]["reason"]) == \
        ("NG - rejected", "Cell Crack"), p
    assert rows[S_OLD]["pre"]["label"] == "In rework"
    assert rows[NOT_PLANNED]["in_master"] is False and rows[NOT_PLANNED]["model"] is None
    assert [r["serial"] for r in d["rows"]][0] == S_OLD, "newest activity first"
    assert d["facets"] == {"shift": ["A", "B", "C"], "station": ["pre_el", "post_el"],
                           "line": ["A", "B"],
                           "result": ["Pre-EL: Pass", "Pre-EL: Pass after rework",
                                      "Pre-EL: In rework", "Post EL: Pass",
                                      "Post EL: NG - rejected"]}, d["facets"]
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
    _c, d = el_api(result="Post EL: NG - rejected", **day)
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


if __name__ == "__main__":
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
