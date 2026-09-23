import sys
import os
import store
import icon_auth

def usage():
    print("Usage:")
    print("  python icon_auth_cli.py init-key")
    print("  python icon_auth_cli.py create-superadmin <login_id> \"<name>\"")
    print("  python icon_auth_cli.py create-admin <login_id> \"<name>\"")
    print("  python icon_auth_cli.py reset-totp <login_id>")
    print("  python icon_auth_cli.py unlock <login_id>")
    print("  python icon_auth_cli.py list")
    print()
    print("Every command reads/writes ICON_DB_FILE (icontrace.db next to this")
    print("file, unless that variable is set) - see the note printed after")
    print("create-superadmin/create-admin/reset-totp about enrolling against it.")
    sys.exit(1)

def _enrol_note(login_id, token, base_url, db_path):
    # auth_lab/lab_app.py is the only thing that serves /enrol - app.py does
    # not have that route yet (Round 24). Left to its own default, the lab
    # opens auth_lab/lab.db, a SEPARATE file from the one this command just
    # wrote to, and the token below would be "invalid" there through no
    # fault of the token: enrolling is impossible until something serves
    # /enrol against THIS SAME database.
    print(f"Enrolment Token: {token}")
    print(f"Enrol URL: {base_url}/enrol?login_id={login_id}&token={token}")
    print()
    print(f"This wrote to: {db_path}")
    print("The lab must be pointed at that SAME file to serve this token -")
    print("left to its own default it opens auth_lab/lab.db instead, a")
    print("different, normally-empty database, and the token above will look")
    print("expired or invalid there through no fault of its own. Start it with:")
    if os.name == "nt":
        print(f'  $env:ICON_DB_FILE = "{db_path}"; python auth_lab\\lab_app.py')
    else:
        print(f'  ICON_DB_FILE="{db_path}" python auth_lab/lab_app.py')
    print("then open the Enrol URL above. Once TOTP is set up there, the")
    print(f"account signs in normally at the real app - this database is the")
    print("one it reads too.")

def main():
    if len(sys.argv) < 2:
        usage()

    cmd = sys.argv[1]
    host = os.environ.get("ICON_HOST", "127.0.0.1")
    port = os.environ.get("ICON_PORT", "8091")
    base_url = f"http://{host}:{port}"

    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)

        if cmd == "init-key":
            try:
                icon_auth.create_key()
                print("Key initialized.")
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == "create-superadmin":
            if len(sys.argv) != 4:
                usage()
            login_id = sys.argv[2]
            name = sys.argv[3]
            try:
                token = icon_auth.create_superadmin(cur, login_id, name)
                print(f"Created Super Admin: {login_id}")
                _enrol_note(login_id, token, base_url, store.DB_PATH)
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == "create-admin":
            if len(sys.argv) != 4:
                usage()
            login_id = sys.argv[2]
            name = sys.argv[3]
            try:
                token = icon_auth.create_admin(cur, "cli", login_id, name)
                print(f"Created Admin: {login_id}")
                _enrol_note(login_id, token, base_url, store.DB_PATH)
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == "reset-totp":
            if len(sys.argv) != 3:
                usage()
            login_id = sys.argv[2]
            try:
                token = icon_auth.reset_totp(cur, "cli", login_id)
                print(f"Reset TOTP for: {login_id}")
                _enrol_note(login_id, token, base_url, store.DB_PATH)
            except Exception as e:
                print(f"Error: {e}")
                
        elif cmd == "unlock":
            if len(sys.argv) != 3:
                usage()
            login_id = sys.argv[2]
            try:
                icon_auth.unlock_user(cur, "cli", login_id)
                print(f"Unlocked user: {login_id}")
            except Exception as e:
                print(f"Error: {e}")
                
        elif cmd == "list":
            users = icon_auth.list_users(cur, "cli")
            print(f"Reading: {store.DB_PATH}")
            print(f"{'ID':<20} | {'Name':<30} | {'Role':<15} | {'Active':<6} | {'Locked Until':<15}")
            print("-" * 95)
            for u in users:
                print(f"{u['login_id']:<20} | {u['display_name']:<30} | {u['role']:<15} | {u['active']:<6} | {u['locked_until']:<15}")
                
        else:
            usage()

if __name__ == "__main__":
    main()
