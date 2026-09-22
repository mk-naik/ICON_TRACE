import pytest
import icon_auth
import store
import tempfile
import os
import hmac
import hashlib

def test_recovery_hmac_sha256(tmp_path):
    # Isolated from whatever db_path another test in this session left
    # store.DB_PATH pointing at (see test_security_4c.py for the same
    # issue) - give this test its own key, deterministically.
    store.DB_PATH = str(tmp_path / "isolated.db")
    key_path = os.path.join(str(tmp_path), ".icon_totp_key")
    if not os.path.exists(key_path):
        icon_auth.create_key()

    token = "TEST-TOKEN"
    try:
        key = icon_auth.load_key()
    except icon_auth.KeyMissing:
        key = b"fallback-key-for-tests-without-key"
    
    # We want to ensure that it's NOT just plain sha256
    plain_sha256 = hashlib.sha256(token.encode('utf-8')).hexdigest()
    actual_hash = icon_auth.hash_token(token)
    
    assert actual_hash != plain_sha256, "hash_token is still using plain SHA256!"
    
    # We want to ensure it matches HMAC-SHA256 with the key
    expected_hmac = hmac.new(key, token.encode('utf-8'), hashlib.sha256).hexdigest()
    assert actual_hash == expected_hmac, "hash_token does not match HMAC-SHA256"
