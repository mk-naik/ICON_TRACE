"""
One-off: move the accounts enrolled in auth_lab/lab.db into the app's own
icontrace.db, so they can sign in to ICON TRACE at :8080.

WHY THIS IS NEEDED
    auth_lab/lab_app.py defaults to auth_lab/lab.db when ICON_DB_FILE is
    unset; the app and icon_auth_cli.py default to icontrace.db. Accounts
    enrolled against the first are invisible to the second.

    The TOTP secret is Fernet-encrypted with the .icon_totp_key that sits
    BESIDE its own database, so copying rows alone would leave secrets that
    the app cannot decrypt. This decrypts each one under the lab's key and
    re-encrypts it under the app's key. Neither key file is modified.

WHAT IT DOES NOT CARRY
    Recovery codes. They are stored as an HMAC keyed with the lab's key and
    cannot be re-derived without the plaintext codes, which nobody has. Any
    Super Admin recovery codes issued by the lab are therefore dead after
    this. Re-issue them when convenient:
        python icon_auth_cli.py reset-totp <login_id>
    then enrol again - enrolment is what mints a fresh set.

    Enrol tokens are dropped too (short-lived; all long expired).

RUN IT
    python migrate_lab_accounts.py            # show what it would do
    python migrate_lab_accounts.py --apply    # do it

Back up icontrace.db first. --apply refuses to run without a backup file
sitting next to it.
"""

import os
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
REAL_DB = os.path.join(BASE, "icontrace.db")
LAB_DB = os.path.join(BASE, "auth_lab", "lab.db")


def _open(path):
    cx = sqlite3.connect(path)
    cx.row_factory = sqlite3.Row
    return cx


def main():
    apply = "--apply" in sys.argv

    for p in (REAL_DB, LAB_DB):
        if not os.path.exists(p):
            print("Missing: %s" % p)
            return 1

    import store
    import icon_auth

    # Decrypt under the LAB key. load_key() reads the key beside whatever
    # store.DB_PATH names, so point it at the lab first.
    store.DB_PATH = LAB_DB
    lab = _open(LAB_DB)
    plain, dead = {}, []
    for u in lab.execute("SELECT login_id, totp_secret_enc FROM app_user"):
        if u["totp_secret_enc"]:
            try:
                plain[u["login_id"]] = icon_auth.decrypt_secret(u["totp_secret_enc"])
            except Exception:
                # Enrolled under an EARLIER key that has since been replaced
                # - the test fixtures delete and recreate auth_lab's key on
                # every run. That secret is unrecoverable by anyone, so the
                # account carries across un-enrolled rather than blocking
                # the ones that are still good.
                dead.append(u["login_id"])

    rows = lab.execute("SELECT * FROM app_user").fetchall()
    print("In %s:" % LAB_DB)
    for u in rows:
        if u["login_id"] in dead:
            state = "enrolled, but under a LOST key - carried across un-enrolled"
        elif u["totp_secret_enc"]:
            state = "enrolled"
        else:
            state = "not enrolled"
        print("   %-18s %-16s %s" % (u["login_id"], u["role"], state))

    real = _open(REAL_DB)
    existing = [dict(r) for r in real.execute(
        "SELECT login_id, role FROM app_user")]
    print("\nIn %s (these are REPLACED):" % REAL_DB)
    for u in existing:
        print("   %-18s %s" % (u["login_id"], u["role"]))
    if not existing:
        print("   (none)")

    if not apply:
        print("\nDry run. Re-run with --apply to carry the accounts across.")
        return 0

    backups = [f for f in os.listdir(BASE)
               if f.startswith("auth_backup_") and os.path.isdir(os.path.join(BASE, f))]
    if not backups:
        print("\nRefusing to run: no auth_backup_* directory found. Make one:")
        print('   mkdir auth_backup_manual; copy icontrace.db auth_backup_manual\\')
        return 1
    print("\nBackup(s) present: %s" % ", ".join(sorted(backups)))

    # Re-encrypt under the APP's key.
    store.DB_PATH = REAL_DB
    reenc = {k: icon_auth.encrypt_secret(v) for k, v in plain.items()}

    cols = [r["name"] for r in real.execute("PRAGMA table_info(app_user)")]
    lab_cols = [r["name"] for r in lab.execute("PRAGMA table_info(app_user)")]
    shared = [c for c in cols if c in lab_cols]

    real.execute("PRAGMA foreign_keys=OFF")
    real.execute("DELETE FROM auth_recovery_code")
    real.execute("DELETE FROM auth_enrol_token")
    real.execute("DELETE FROM app_user")

    q = "INSERT INTO app_user (%s) VALUES (%s)" % (
        ",".join(shared), ",".join("?" * len(shared)))
    for u in rows:
        rec = {c: u[c] for c in shared}
        if u["login_id"] in reenc:
            rec["totp_secret_enc"] = reenc[u["login_id"]]
        else:
            # Never enrolled, or enrolled under a key nobody has any more.
            rec["totp_secret_enc"] = None
            rec["must_reenrol"] = 1
        rec["totp_pending_enc"] = None
        real.execute(q, tuple(rec[c] for c in shared))
    real.commit()

    print("\nNow in %s:" % REAL_DB)
    for r in real.execute("SELECT login_id, role, "
                          "totp_secret_enc IS NOT NULL AS enrolled FROM app_user"):
        print("   %-18s %-16s %s" % (r["login_id"], r["role"],
              "enrolled" if r["enrolled"] else "not enrolled"))
    print("\nRecovery codes were NOT carried across - see this file's header.")
    print("Sign in at the app with the same authenticator entry as before.")
    real.close()
    lab.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
