import pytest
import sqlite3, os
import store, icon_auth

def test_admin_promotion_restriction(tmp_path):
    db_path = str(tmp_path / "test.db")
    old_path = store.DB_PATH
    store.DB_PATH = db_path
    # create_admin() issues an enrol token, hashed via icon_auth.hash_token()
    # - HMAC-SHA256 keyed by the Fernet key since Round 19's 4e fix, so a
    # key must exist here too now.
    icon_auth.create_key()

    with store.conn() as (cx, cur):
        icon_auth.ensure_schema(cur)
        # Create superadmin (rank 3)
        icon_auth.create_superadmin(cur, "sa1", "SA One")
        # Create admin (rank 2)
        icon_auth.create_admin(cur, "sa1", "ad1", "Ad One")
        # Create operator (rank 1)
        icon_auth.create_operator(cur, "sa1", "op1", "Op One", "FQC", "TempPass123!")
        
        # Test 1: Admin ad1 tries to promote op1 to Admin (rank 2). Should fail.
        with pytest.raises(icon_auth.AuthError, match="Admins can only grant operator roles"):
            icon_auth.update_user(cur, "ad1", "op1", role="Admin")
            
        # Test 2: Admin ad1 tries to change op1 to another operator role (rank 1). Should succeed.
        icon_auth.update_user(cur, "ad1", "op1", role="Lead")
        op = icon_auth._get_user(cur, "op1")
        assert op["role"] == "Lead"
        
        # Test 3: SuperAdmin sa1 tries to promote op1 to Admin (rank 2). Should succeed.
        icon_auth.update_user(cur, "sa1", "op1", role="Admin")
        op = icon_auth._get_user(cur, "op1")
        assert op["role"] == "Admin"
        
    store.DB_PATH = old_path
