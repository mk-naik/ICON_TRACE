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
    # The running ICON TRACE app serves /enrol itself (Round 25), against the
    # database file it is started with. The token below was written to
    # db_path, so the app must be started on THAT SAME file - an app on another
    # file will call the token invalid through no fault of the token.
    print(f"Enrolment Token: {token}")
    print(f"Enrol URL: {base_url}/enrol?login_id={login_id}&token={token}")
    print()
    print(f"This wrote to: {db_path}")
    print("Open the Enrol URL in a browser on the machine running ICON TRACE,")
    print("with the app started on THAT SAME file. If it is not running yet:")
    # the port is only named when this command was given one - the app's own
    # default (8080) is what the URL above assumes otherwise
    port = os.environ.get("ICON_PORT")
    if os.name == "nt":
        print('  $env:ICON_DB_FILE = "%s";%s python serve.py'
              % (db_path, (' $env:ICON_PORT = "%s";' % port) if port else ""))
    else:
        print('  ICON_DB_FILE="%s"%s python serve.py'
              % (db_path, (' ICON_PORT=%s' % port) if port else ""))
    print("(No ICON_DB_FILE at all means icontrace.db next to serve.py - the")
    print("same default this command used.) The URL above assumes the app is on")
    print(f"{base_url}; set ICON_HOST / ICON_PORT here to match if it is not.")
    print("Scan the QR code with an authenticator app, type the 6-digit code")
    print("it shows, and the account can then sign in at the same address.")

def main():
    if len(sys.argv) < 2:
        usage()

    cmd = sys.argv[1]
    host = os.environ.get("ICON_HOST", "127.0.0.1")
    port = os.environ.get("ICON_PORT", "8080")   # serve.py's own default
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
