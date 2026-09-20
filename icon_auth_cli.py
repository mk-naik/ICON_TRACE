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
    sys.exit(1)

def main():
    if len(sys.argv) < 2:
        usage()
        
    cmd = sys.argv[1]
    
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
                print(f"Enrolment Token: {token}")
                print(f"Enrol URL: /enrol?login_id={login_id}&token={token}")
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
                print(f"Enrolment Token: {token}")
                print(f"Enrol URL: /enrol?login_id={login_id}&token={token}")
            except Exception as e:
                print(f"Error: {e}")
                
        elif cmd == "reset-totp":
            if len(sys.argv) != 3:
                usage()
            login_id = sys.argv[2]
            try:
                token = icon_auth.reset_totp(cur, "cli", login_id)
                print(f"Reset TOTP for: {login_id}")
                print(f"New Enrolment Token: {token}")
                print(f"Enrol URL: /enrol?login_id={login_id}&token={token}")
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
            print(f"{'ID':<20} | {'Name':<30} | {'Role':<15} | {'Active':<6} | {'Locked Until':<15}")
            print("-" * 95)
            for u in users:
                print(f"{u['login_id']:<20} | {u['display_name']:<30} | {u['role']:<15} | {u['active']:<6} | {u['locked_until']:<15}")
                
        else:
            usage()

if __name__ == "__main__":
    main()
