"""
One-off (Round 26): give every existing account an explicit permission row
per screen, equal to what its role already grants - so that the moment
Round 27 starts enforcing from user_screen_perm, nobody's access changes.

    python migrate_screen_perms.py            # show what it would do
    python migrate_screen_perms.py --apply    # do it

Targets ICON_DB_FILE, or icontrace.db next to this file.

WHY IT EXISTS
    Accounts created from Round 26 on are seeded by create_operator(),
    create_admin() and create_superadmin() themselves. Accounts that existed
    before have no rows, and get_screen_perms() reads "no row" as "no
    access" on purpose. Enforcing from the table without running this first
    would lock every one of them out of everything.

WHAT IT WILL NOT TOUCH
    An account that already has permission rows is reported and left
    alone. Those rows are either this script's own from an earlier run, or
    something a person set deliberately (Round 28's editor) - and in the
    second case, resetting them to the role's defaults would silently undo
    a decision. Safe to run twice.

SAFETY
    The dry run opens the database READ-ONLY, so "prints what it would do
    and changes nothing" is enforced by SQLite rather than by care.
    --apply refuses to run unless a backup of the database sits beside it:
    an auth_backup_*/ directory holding a copy, or a <name>.bak* file - and,
    since Round 27, unless the newest one is under ten minutes old
    (ICON_BACKUP_MAX_AGE_S overrides, for tests).
"""

import os
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))


def _db_path():
    return os.path.abspath(os.environ.get("ICON_DB_FILE",
                                          os.path.join(BASE, "icontrace.db")))


# A backup older than this is refused (Round 27): one taken last week, or
# before this morning's shift, sits beside the database just as well as one
# taken a minute ago, and restoring it would lose everything since. Ten
# minutes, overridable for tests.
MAX_BACKUP_AGE_S = 600


def _max_backup_age():
    return int(os.environ.get("ICON_BACKUP_MAX_AGE_S", MAX_BACKUP_AGE_S))


def _backup_time(path):
    """When this copy was made. The later of modified and created, because
    Windows' `copy` keeps the SOURCE's modified time - a copy taken a
    moment ago of a database last written an hour ago would otherwise look
    an hour old, and taking it again would never help. Created time is when
    the copy itself came into being; where the platform has none, modified
    time is all there is (and cp without -p sets it to now)."""
    st = os.stat(path)
    return max(st.st_mtime, getattr(st, "st_birthtime", 0) or 0)


def _backup_present(db_path, now=None):
    """(path, age_in_seconds) of the NEWEST backup beside db_path - a
    <name>.bak* file or an auth_backup_*/<name> copy - or None when there
    is none at all. Whether it is fresh enough is the caller's call."""
    here, name = os.path.split(db_path)
    found = []
    for entry in os.listdir(here):
        full = os.path.join(here, entry)
        if entry.startswith(name + ".bak") and os.path.isfile(full):
            found.append(full)
        elif entry.startswith("auth_backup_") and os.path.isfile(os.path.join(full, name)):
            found.append(os.path.join(full, name))
    if not found:
        return None
    newest = max(found, key=_backup_time)
    now = time.time() if now is None else now
    return newest, max(0.0, now - _backup_time(newest))


def _age_words(seconds):
    m = int(seconds // 60)
    if m < 1:
        return "%d seconds" % int(seconds)
    if m < 120:
        return "%d minute%s" % (m, "" if m == 1 else "s")
    h = m // 60
    if h < 48:
        return "%d hours" % h
    return "%d days" % (h // 24)


def _read_state(db_path):
    """Accounts and how many permission rows each already has, read through a
    read-only connection so a dry run cannot write even by accident."""
    cx = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    cx.row_factory = sqlite3.Row
    try:
        users = [dict(r) for r in cx.execute(
            "SELECT user_id, login_id, role FROM app_user ORDER BY user_id")]
        has_table = cx.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='user_screen_perm'").fetchone() is not None
        counts = {}
        if has_table:
            for r in cx.execute("SELECT user_id, COUNT(*) AS n FROM user_screen_perm "
                                "GROUP BY user_id"):
                counts[r["user_id"]] = r["n"]
    finally:
        cx.close()
    return users, counts


def main(argv):
    apply = "--apply" in argv
    db_path = _db_path()
    if not os.path.exists(db_path):
        print("No database at %s" % db_path)
        return 1

    import icon_auth
    users, counts = _read_state(db_path)
    print("Database: %s" % db_path)
    print("%-22s %-20s %s" % ("ACCOUNT", "ROLE", "WOULD DO" if not apply else "PLAN"))
    todo = []
    for u in users:
        if counts.get(u["user_id"]):
            print("%-22s %-20s already has %d row(s) - left alone"
                  % (u["login_id"], u["role"], counts[u["user_id"]]))
            continue
        d = icon_auth.default_perms_for_role(u["role"])
        views = sum(1 for p in d.values() if p["view"])
        writes = sum(1 for p in d.values() if p["write"])
        print("%-22s %-20s seed %d screen(s): %d viewable, %d writable"
              % (u["login_id"], u["role"], len(d), views, writes))
        todo.append(u)

    if not apply:
        print("\nDry run - nothing written. Re-run with --apply to seed %d account(s)."
              % len(todo))
        return 0

    name = os.path.basename(db_path)
    found = _backup_present(db_path)
    if not found:
        print("\nRefusing to run: no backup of %s beside it." % name)
        print("Copy it first, e.g.  copy %s %s.bak" % (name, name))
        return 1
    backup, age = found
    limit = _max_backup_age()
    if age > limit:
        print("\nRefusing to run: the newest backup, %s, is %s old - "
              "older than the %s allowed." % (backup, _age_words(age),
                                              _age_words(limit)))
        print("Take a fresh copy first, e.g.  copy %s %s.bak" % (name, name))
        return 1
    print("\nBackup found: %s (%s old)" % (backup, _age_words(age)))

    import store
    store.DB_PATH = db_path
    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)
        for u in todo:
            icon_auth.set_screen_perms(cur, "cli", u["login_id"],
                                       icon_auth.default_perms_for_role(u["role"]))
    print("Seeded %d account(s)." % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
