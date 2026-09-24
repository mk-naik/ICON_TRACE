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
    an auth_backup_*/ directory holding a copy, or a <name>.bak* file.
"""

import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def _db_path():
    return os.path.abspath(os.environ.get("ICON_DB_FILE",
                                          os.path.join(BASE, "icontrace.db")))


def _backup_present(db_path):
    here, name = os.path.split(db_path)
    for entry in os.listdir(here):
        full = os.path.join(here, entry)
        if entry.startswith(name + ".bak") and os.path.isfile(full):
            return full
        if entry.startswith("auth_backup_") and os.path.isfile(os.path.join(full, name)):
            return os.path.join(full, name)
    return None


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

    backup = _backup_present(db_path)
    if not backup:
        print("\nRefusing to run: no backup of %s beside it." % os.path.basename(db_path))
        print("Copy it first, e.g.  copy %s %s.bak"
              % (os.path.basename(db_path), os.path.basename(db_path)))
        return 1
    print("\nBackup found: %s" % backup)

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
