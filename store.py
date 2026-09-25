"""
ICON TRACE - store.

SQLite, in ONE FILE next to the app: icontrace.db

Deliberate, and Mukesh's call. While the system is being tested, the data in
it is test data. If that lives in MySQL then either a bad import leaves rows
nobody can find, or the whole schema has to be dropped before production. A
single file is deleted with one command and the next run starts clean.

    del icontrace.db        Windows
    rm icontrace.db         anywhere else

Moving to MySQL later is a connection change, not a rewrite: the SQL here is
plain, the placeholders are normalised, and nothing depends on SQLite.
"""

import os, re, json, sqlite3, datetime, threading

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ICON_DB_FILE", os.path.join(BASE, "icontrace.db"))
SCHEMA = os.path.join(BASE, "schema_sqlite.sql")

_lock = threading.Lock()
_ready = False


def _row_factory(cursor, row):
    return {d[0]: row[i] for i, d in enumerate(cursor.description)}


class _Cur:
    """Accepts MySQL-style %s placeholders so the same SQL works either way."""

    def __init__(self, cur):
        self._c = cur

    def execute(self, sql, args=()):
        self._c.execute(sql.replace("%s", "?"), tuple(args))
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    @property
    def lastrowid(self):
        return self._c.lastrowid


class conn:
    """`with store.conn() as (cx, cur):` - commit on clean exit, rollback on
    exception."""

    def __enter__(self):
        ensure()
        self.cx = sqlite3.connect(DB_PATH, timeout=20,
                                  detect_types=sqlite3.PARSE_DECLTYPES)
        self.cx.row_factory = _row_factory
        self.cx.execute("PRAGMA foreign_keys=ON")
        self.cx.execute("PRAGMA journal_mode=WAL")
        return self.cx, _Cur(self.cx.cursor())

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.cx.rollback()
            else:
                self.cx.commit()
        finally:
            self.cx.close()
        return False


def _table_ddl(text, table):
    """The CREATE statement for one table, out of the schema file itself, so
    a rebuild cannot drift from the definition everything else is built to."""
    m = re.search(r"CREATE TABLE IF NOT EXISTS %s\s*\(.*?\n\)\s*;" % table,
                  text, re.S)
    return m.group(0) if m else None


def _migrate(cx, text):
    """What CREATE TABLE IF NOT EXISTS cannot do.

    It skips a table that already exists, columns and all - so a column added
    to the schema after a database was created is simply absent there, and
    the feature that needs it fails on a file that looks up to date. Adding
    them is idempotent; rebuilding is only for a column whose NULLability
    changed, which SQLite cannot alter in place.
    """
    def cols(t):
        return {r[1]: r for r in cx.execute("PRAGMA table_info(%s)" % t)}

    # pre-shared or post-shared, recorded at allocation
    if cols("allocation") and "alloc_type" not in cols("allocation"):
        cx.execute("ALTER TABLE allocation ADD COLUMN alloc_type TEXT")

    # Edit: a real change replaces a challan row rather than rewriting it -
    # the original is marked superseded and kept intact.
    for name, decl in (("superseded_by", "INTEGER"), ("superseded_at", "TEXT"),
                       ("superseded_by_user", "TEXT")):
        if cols("challan") and name not in cols("challan"):
            cx.execute("ALTER TABLE challan ADD COLUMN %s %s" % (name, decl))

    # Loading Verification: Team 3's own confirmation a pallet was found
    # and put on the vehicle, separate from load_order (only the plan).
    for name, decl in (("loading_status", "TEXT NOT NULL DEFAULT 'pending'"),
                       ("loading_scanned_at", "TEXT"),
                       ("loading_scanned_by", "TEXT")):
        if cols("challan_box") and name not in cols("challan_box"):
            cx.execute("ALTER TABLE challan_box ADD COLUMN %s %s" % (name, decl))

    if not cols("fqc_record"):
        return

    # FQC records pass or reject, and what Quality later made of a reject
    for name, decl in (("outcome", "TEXT"), ("defect", "TEXT"),
                       ("note", "TEXT"), ("quality_grade", "TEXT"),
                       ("quality_note", "TEXT"), ("quality_by", "TEXT"),
                       ("quality_at", "TEXT"),
                       ("superseded_by", "INTEGER"), ("superseded_at", "TEXT"),
                       ("build_instance", "INTEGER")):
        if name not in cols("fqc_record"):
            cx.execute("ALTER TABLE fqc_record ADD COLUMN %s %s" % (name, decl))

    # grade was NOT NULL when FQC still graded. A rejected module has no
    # grade until Quality gives it one, so the column has to accept NULL.
    info = cols("fqc_record").get("grade")
    if info and info[3] == 1:                      # notnull
        ddl = _table_ddl(text, "fqc_record")
        if ddl:
            keep = [c for c in cols("fqc_record")]
            cx.execute("ALTER TABLE fqc_record RENAME TO fqc_record_old")
            cx.executescript(ddl)
            shared = [c for c in keep if c in cols("fqc_record")]
            cx.execute("INSERT INTO fqc_record (%s) SELECT %s FROM fqc_record_old"
                       % (", ".join(shared), ", ".join(shared)))
            cx.execute("DROP TABLE fqc_record_old")
            print("[store] fqc_record rebuilt: grade is nullable until Quality "
                  "decides")
    # gate pass linked to a real challan row (not just a typed string)
    if cols("gatepass") and "challan_id" not in cols("gatepass"):
        cx.execute("ALTER TABLE gatepass ADD COLUMN challan_id INTEGER REFERENCES challan(challan_id)")

    # Production Entry's own double-recording guard, separate from `state` -
    # FQC can legitimately grade a serial before its shift's paperwork is
    # filed, which used to make Production Entry refuse the whole range.
    if cols("serial") and "prod_entry_id" not in cols("serial"):
        cx.execute("ALTER TABLE serial ADD COLUMN prod_entry_id INTEGER "
                   "REFERENCES production_entry(entry_id)")
    cx.commit()


# What SQLite's CURRENT_TIMESTAMP writes: '2026-09-25 05:07:24', UTC, with a
# space. Everything the application writes itself is IST with a 'T'
# (icon_clock.stamp()), so the space is what tells a default apart.
_UTC_DEFAULT_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:*"


def _ist_timestamps(cx):
    """Every column whose default is CURRENT_TIMESTAMP holds IST, like the
    rest of the database.

    SQLite's CURRENT_TIMESTAMP is UTC, and SQLite cannot change an existing
    column's default in place. So each such column gets an AFTER INSERT
    trigger that turns the UTC default into IST the moment it is written -
    which covers every INSERT in the codebase, store.insert() or raw SQL,
    without any of them having to remember. Rows written before the trigger
    existed are moved once, flagged in app_config so a restart does not
    scan the tables again.

    Nothing in the application writes a space-separated time into these
    columns itself (it writes icon_clock.stamp()), which is what makes the
    space a reliable sign of a UTC default. Keep it that way.
    """
    tables = [r[0] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]
    targets = []
    for t in tables:
        for c in cx.execute("PRAGMA table_info(%s)" % t):
            if str(c[4] or "").upper() == "CURRENT_TIMESTAMP":
                targets.append((t, c[1]))
    for t, col in targets:
        cx.execute(
            "CREATE TRIGGER IF NOT EXISTS ist_%s_%s AFTER INSERT ON %s "
            "WHEN NEW.%s GLOB '%s' BEGIN "
            "UPDATE %s SET %s = strftime('%%Y-%%m-%%dT%%H:%%M:%%S', NEW.%s, "
            "'+330 minutes') WHERE rowid = NEW.rowid; END"
            % (t, col, t, col, _UTC_DEFAULT_GLOB, t, col, col))
    has_config = "app_config" in tables
    if has_config and cx.execute(
            "SELECT 1 FROM app_config WHERE k='clock.ist_backfill'").fetchone():
        cx.commit()
        return
    for t, col in targets:
        cx.execute(
            "UPDATE %s SET %s = strftime('%%Y-%%m-%%dT%%H:%%M:%%S', %s, "
            "'+330 minutes') WHERE %s GLOB '%s'"
            % (t, col, col, col, _UTC_DEFAULT_GLOB))
    if has_config:
        cx.execute("INSERT OR REPLACE INTO app_config (k, v) "
                   "VALUES ('clock.ist_backfill', '1')")
    cx.commit()


def _stamps_from_created(cx):
    """Once: the date and shift a record carries are the calendar date and
    the shift it was CREATED in - never the date or shift printed in a
    serial, and never what a form happened to show.

    Before 25 Sep an allocation took its shift from the first serial's
    barcode and its date from the day it was keyed; a production entry and
    a downtime event took both from the form (Production Entry opened on
    v4's demo 21-08-2026, Loss on shift B whatever the time). Each is
    re-stamped from its own created_at, which _ist_timestamps() has already
    put in IST.

    Challans get issued_at - when one became 'issued', which is when its
    modules were dispatched. Its challan_date is the date printed on the
    document and is left alone; dispatch is counted by issued_at."""
    def cols(t):
        return {r[1] for r in cx.execute("PRAGMA table_info(%s)" % t)}
    if cols("challan") and "issued_at" not in cols("challan"):
        cx.execute("ALTER TABLE challan ADD COLUMN issued_at TEXT")
    if "k" not in cols("app_config"):
        return
    if cx.execute("SELECT 1 FROM app_config "
                  "WHERE k='clock.stamps_from_created'").fetchone():
        cx.commit()
        return
    hour = "CAST(substr(created_at, 12, 2) AS INTEGER)"
    num = ("(CASE WHEN %s >= 6 AND %s < 14 THEN 1 WHEN %s >= 14 AND %s < 22 "
           "THEN 2 ELSE 3 END)" % (hour, hour, hour, hour))
    letter = ("(CASE WHEN %s >= 6 AND %s < 14 THEN 'A' WHEN %s >= 14 AND %s < 22 "
              "THEN 'B' ELSE 'C' END)" % (hour, hour, hour, hour))
    if cols("allocation"):
        cx.execute("UPDATE allocation SET date_produced = substr(created_at, 1, 10), "
                   "shift = %s WHERE created_at IS NOT NULL" % num)
    if cols("production_entry"):
        cx.execute("UPDATE production_entry SET prod_date = substr(created_at, 1, 10), "
                   "shift = %s WHERE created_at IS NOT NULL" % letter)
    if cols("loss_event"):
        cx.execute("UPDATE loss_event SET event_date = substr(created_at, 1, 10), "
                   "shift = %s WHERE created_at IS NOT NULL" % letter)
    if cols("challan"):
        # the audit line written when it was issued, else when it was made
        cx.execute("""UPDATE challan SET issued_at = COALESCE(
                        (SELECT MIN(a.at) FROM dispatch_audit a
                         WHERE a.entity = 'challan'
                           AND a.entity_id = CAST(challan.challan_id AS TEXT)
                           AND a.action IN ('challan.issued', 'challan.submit')),
                        created_at)
                      WHERE status = 'issued' AND issued_at IS NULL""")
    cx.execute("INSERT OR REPLACE INTO app_config (k, v) "
               "VALUES ('clock.stamps_from_created', '1')")
    cx.commit()


def ensure():
    """Create the file and the schema on first use."""
    global _ready
    if _ready and os.path.exists(DB_PATH):
        return
    with _lock:
        fresh = not os.path.exists(DB_PATH)
        cx = sqlite3.connect(DB_PATH, timeout=20)
        try:
            if os.path.exists(SCHEMA):
                text = open(SCHEMA, encoding="utf-8").read()
                # Views hold no data, and CREATE VIEW IF NOT EXISTS leaves an
                # old definition in place for ever. Dropping them first keeps
                # every view in step with this file - v_indent_progress had
                # an INNER JOIN long after the file said LEFT.
                for name in re.findall(r"CREATE VIEW IF NOT EXISTS (\w+)", text):
                    cx.execute("DROP VIEW IF EXISTS %s" % name)
                cx.executescript(text)
                cx.commit()
                _migrate(cx, text)
                _ist_timestamps(cx)
                _stamps_from_created(cx)
        finally:
            cx.close()
        _ready = True
        if fresh:
            print("[store] created %s" % DB_PATH)


def wipe():
    """Delete the database. Used by the Reset control, and by hand between
    test rounds."""
    global _ready
    with _lock:
        _ready = False
        for suffix in ("", "-wal", "-shm"):
            p = DB_PATH + suffix
            if os.path.exists(p):
                os.remove(p)
    ensure()


def stats():
    out = {}
    with conn() as (cx, cur):
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")
        for r in cur.fetchall():
            t = r["name"]
            cur.execute("SELECT COUNT(*) AS n FROM %s" % t)
            out[t] = cur.fetchone()["n"]
    out["_file"] = DB_PATH
    out["_bytes"] = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    return out


# --------------------------------------------------------------------------
# small helpers used across the API
# --------------------------------------------------------------------------

def insert(cur, table, data):
    cols = [k for k in data if data[k] is not None or True]
    cur.execute("INSERT INTO %s (%s) VALUES (%s)"
                % (table, ", ".join(cols), ", ".join(["%s"] * len(cols))),
                [data[c] for c in cols])
    return cur.lastrowid


def rows(cur, sql, args=(), limit=None):
    cur.execute(sql + ("" if limit is None else " LIMIT %d" % limit), args)
    return cur.fetchall()


def one(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchone()


def next_seq(cur, table, key_col, key, seq_col="next_seq"):
    """Draw a counter value. SQLite serialises writers, so the read-modify-
    write inside one transaction is atomic - the same guarantee the MySQL
    row lock gives."""
    cur.execute("SELECT %s AS n FROM %s WHERE %s=%%s"
                % (seq_col, table, key_col), (key,))
    r = cur.fetchone()
    if r is None:
        cur.execute("INSERT INTO %s (%s, %s) VALUES (%%s, 2)"
                    % (table, key_col, seq_col), (key,))
        return 1
    n = r["n"]
    cur.execute("UPDATE %s SET %s=%%s WHERE %s=%%s"
                % (table, seq_col, key_col), (n + 1, key))
    return n


# --------------------------------------------------------------------------
# Boxes - persisted from the first scan.
#
# They were held in memory, so a browser refresh at 18 of 36 lost the pallet
# and the operator had to rescan. A pallet being packed is real work in
# progress; it belongs in the database from the first module, not at close.
# --------------------------------------------------------------------------

def open_box(cur, pack_date, grade, model, customer_code, capacity,
             shift=None, bin_no=None, actor="operator"):
    seq = next_seq(cur, "box_counter", "pack_date", pack_date)
    bid = insert(cur, "box", {
        "pack_date": pack_date, "seq": seq, "grade": grade,
        "code_map_version": 1, "model": model, "customer": customer_code,
        "capacity": capacity, "bin_no": bin_no, "pack_shift": shift,
        "state": "open", "qty": 0, "is_partial": 0, "origin": "system",
        "created_by": actor})
    return bid, seq


def box_row(cur, box_id):
    return one(cur, "SELECT * FROM box WHERE box_id=%s", (box_id,))


def open_boxes(cur):
    return rows(cur, "SELECT * FROM box WHERE state='open' ORDER BY box_id DESC")


def boxes_by_state(cur, state=None, limit=200):
    if state:
        return rows(cur, "SELECT * FROM box WHERE state=%s ORDER BY box_id DESC",
                    (state,), limit)
    return rows(cur, "SELECT * FROM box ORDER BY box_id DESC", (), limit)


def box_serials(cur, box_id):
    return [r["serial"] for r in rows(
        cur, "SELECT serial FROM box_serial WHERE box_id=%s ORDER BY added_at",
        (box_id,))]


def add_to_box(cur, box_id, serial, actor="operator"):
    insert(cur, "box_serial", {"box_id": box_id, "serial": serial,
                               "build_instance": 1, "added_by": actor})
    cur.execute("UPDATE box SET qty=(SELECT COUNT(*) FROM box_serial "
                "WHERE box_id=%s) WHERE box_id=%s", (box_id, box_id))


def remove_from_box(cur, box_id, serial):
    cur.execute("DELETE FROM box_serial WHERE box_id=%s AND serial=%s",
                (box_id, serial))
    cur.execute("UPDATE box SET qty=(SELECT COUNT(*) FROM box_serial "
                "WHERE box_id=%s) WHERE box_id=%s", (box_id, box_id))


def close_box(cur, box_id):
    """The caller has already made sure qty matches capacity - closing
    short of it is refused before this is ever reached, so is_partial is
    never set true here. The column stays, read-only now, because
    historical boxes closed under the old rule still carry it."""
    cur.execute("UPDATE box SET state='closed' WHERE box_id=%s", (box_id,))


def serial_in_live_box(cur, serial):
    """A module must sit in one live box only. Checked before the insert.

    Selects enough to NAME the box it is already in - grade and map version
    included, because the number on the label is derived from them. "Already
    in box ISPL260909/K001" sends the operator to it; "already in box 1"
    does not.
    """
    return one(cur, "SELECT b.box_id, b.seq, b.pack_date, b.grade, "
                    "b.code_map_version, b.state FROM box_serial bs "
                    "JOIN box b ON b.box_id=bs.box_id "
                    "WHERE bs.serial=%s AND b.state<>'retired'", (serial,))
