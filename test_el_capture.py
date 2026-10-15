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

  7. The module journey shows a Pre-EL and a Post EL step only where the
     serial was captured - no step at all otherwise - after Produced and
     before Anomaly / FQC, valued by the latest capture's verdict, never a
     reject; read from el_capture, never from the shares.

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


def step(serial, stage):
    got = [j for j in journey(serial) if j["stage"] == stage]
    assert len(got) == 1, (stage, [j["stage"] for j in journey(serial)])
    return got[0]


@test("a serial with no captures has no Pre-EL or Post EL step at all - not a "
      "dash, not 'pending' - and the journey is otherwise as it was")
def t_journey_none():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg")           # another module's
    run()
    stages = [j["stage"] for j in journey(S_CROSS)]
    assert stages == ["Allocated", "Produced", "FQC", "Packed", "Challan", "Gate pass"], stages


@test("a module re-shot from Cell Crack to OK shows OK, both captures oldest first, "
      "after Produced and before Anomaly and FQC - Post EL after Pre-EL")
def t_journey_reshot():
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
    stages = [j["stage"] for j in journey(S_CRACK)]
    assert stages == ["Allocated", "Produced", "Pre-EL", "Post EL", "Anomaly", "FQC",
                      "Packed", "Challan", "Gate pass"], stages
    pre = step(S_CRACK, "Pre-EL")
    assert pre["value"] == "OK" and pre["done"] is True and pre["tone"] == "t-pass", pre
    assert pre["detail"] == ["Cell Crack · 14-10-2026 13:07",
                             "OK · 14-10-2026 13:10 · re-shot 1", "Line A"], pre["detail"]
    assert pre["tag"] == "14-10-2026 13:10 · shift A", pre["tag"]
    post = step(S_CRACK, "Post EL")
    assert post["value"] == "OK" and post["detail"] == ["OK · 16-10-2026 01:12", "Line B"], post
    assert post["tag"] == "16-10-2026 01:12 · shift C (15-10)", post["tag"]


@test("re-shot under its own name, as the real Pre-EL share does it: the later "
      "file is the latest")
def t_journey_same_name_reshot():
    fresh()
    put(PRE_A, "2026-10-15/早班/Ribbon short", S_CROSS + ".jpg", "2026-10-15T13:07:34")
    put(PRE_A, "2026-10-15/早班/OK", S_CROSS + ".jpg", "2026-10-15T13:10:14")
    run()
    pre = step(S_CROSS, "Pre-EL")
    assert pre["value"] == "OK" and pre["tone"] == "t-pass", pre
    assert pre["detail"] == ["Ribbon short · 15-10-2026 13:07", "OK · 15-10-2026 13:10",
                             "Line A"], pre["detail"]


@test("the highest re-shot number is the latest even against a later file time; "
      "a defect verdict is t-rev, never t-fail")
def t_journey_latest_rule():
    fresh()
    put(PRE_A, "2026-10-14/早班/OK", S_OLD + ".jpg", "2026-10-14T10:00:00")
    put(PRE_A, "2026-10-14/早班/Cell Crack", S_OLD + "_2.jpg", "2026-10-14T09:00:00")
    run()
    pre = step(S_OLD, "Pre-EL")
    assert pre["value"] == "Cell Crack" and pre["tone"] == "t-rev", pre
    assert pre["detail"][-2] == "Cell Crack · 14-10-2026 09:00 · re-shot 2", pre["detail"]
    assert pre["tag"].startswith("14-10-2026 09:00"), pre["tag"]


@test("'Pass' and ' ok ' are clean, as on the FQC screen")
def t_journey_clean_words():
    fresh(post_el_b_root="")
    put(PRE_A, "2026-10-14/早班/Pass", S_OLD + ".jpg")
    put(PRE_A, "2026-10-14/早班/ ok", S_STRAY + ".jpg")
    run()
    assert step(S_OLD, "Pre-EL")["tone"] == "t-pass"
    assert step(S_STRAY, "Pre-EL")["tone"] == "t-pass"
    assert [j["stage"] for j in journey(S_OLD)].count("Post EL") == 0


@test("more than four captures: the four latest are listed, the rest counted first")
def t_journey_many():
    fresh()
    for i in range(6):
        put(PRE_A, "2026-10-14/早班/%s" % ("OK" if i == 5 else "Cell Crack"),
            S_POST + ("_%d.jpg" % i if i else ".jpg"), "2026-10-14T1%d:00:00" % i)
    run()
    pre = step(S_POST, "Pre-EL")
    assert pre["detail"] == ["+2 earlier",
                             "Cell Crack · 14-10-2026 12:00 · re-shot 2",
                             "Cell Crack · 14-10-2026 13:00 · re-shot 3",
                             "Cell Crack · 14-10-2026 14:00 · re-shot 4",
                             "OK · 14-10-2026 15:00 · re-shot 5", "Line A"], pre["detail"]


@test("one folder serving both lines: no line is claimed; captures from two "
      "lines each say which")
def t_journey_lines():
    fresh(pre_el_b_root=PRE_A)
    put(PRE_A, "2026-10-14/早班/OK", S_CRACK + ".jpg", "2026-10-14T09:00:00")
    run()
    assert step(S_CRACK, "Pre-EL")["detail"] == ["OK · 14-10-2026 09:00"]
    with store.conn() as (cx, cur):
        db.set_config(cur, {"pre_el_b_root": PRE_B})
    put(PRE_B, "2026-10-14/中班/Cell Crack", S_CRACK + "_1.jpg", "2026-10-14T15:00:00")
    run()
    assert step(S_CRACK, "Pre-EL")["detail"] == [
        "OK · 14-10-2026 09:00", "Cell Crack · 14-10-2026 15:00 · re-shot 1 · Line B"]


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
        assert step(S_CRACK, "Pre-EL")["value"] == "Cell Crack"
    finally:
        _os.scandir = real


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
