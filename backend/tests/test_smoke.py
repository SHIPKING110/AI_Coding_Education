"""M0 冒烟测试：不含数据库依赖的用例。"""

import jwt as pyjwt
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_password_hash_roundtrip():
    hashed = hash_password("secret-123")
    assert hashed != "secret-123"
    assert verify_password("secret-123", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    token = create_access_token("user-id")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "user-id"


def test_refresh_token_rejects_access_type():
    token = create_access_token("user-id")
    try:
        decode_token(token, expected_type="refresh")
        assert False, "refresh-type check should reject an access token"
    except pyjwt.InvalidTokenError:
        pass


def test_me_requires_auth():
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_openapi_served():
    resp = client.get(get_settings().API_PREFIX + "/openapi.json")
    assert resp.status_code == 200
    assert "/api/auth/login" in resp.json()["paths"]
