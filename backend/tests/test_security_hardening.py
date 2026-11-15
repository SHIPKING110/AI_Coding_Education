"""M-A 安全硬化回归：密码策略 / 媒体签名 / 生产密钥校验 / 注册角色边界 / 限速器。

全部为无 DB 依赖的纯函数级用例，可在 CI 离线执行。
"""

from urllib.parse import parse_qs, urlsplit

import pytest

from app.api.routers import auth as auth_router
from app.core.config import Settings, validate_startup_security
from app.core.media import (
    sign_media_path,
    sign_urls_in_json,
    strip_media_signature,
    verify_media_signature,
)
from app.core.ratelimit import enforce
from app.core.security import generate_temp_password, validate_password_strength
from app.models.user import Role

# ---------- 密码策略 ----------


def test_password_policy_accepts_strong_password():
    assert validate_password_strength("abc12345") == "abc12345"


@pytest.mark.parametrize(
    "weak",
    [
        "123456",      # 历史默认口令
        "1234567890",  # 纯数字
        "abcdefgh",    # 纯字母
    ],
)
def test_password_policy_rejects_weak(weak):
    with pytest.raises(ValueError):
        validate_password_strength(weak)


def test_password_policy_rejects_short_and_repetitive():
    with pytest.raises(ValueError):
        validate_password_strength("a1b2")  # 太短
    with pytest.raises(ValueError):
        validate_password_strength("aaaaaaaaaa1")  # 重复过多
    with pytest.raises(ValueError):
        validate_password_strength("password1")  # 字典弱口令


def test_temp_password_meets_policy():
    for _ in range(20):
        pw = generate_temp_password()
        assert len(pw) == 10
        assert validate_password_strength(pw) == pw


# ---------- 媒体签名 ----------


def test_media_sign_verify_roundtrip(monkeypatch):
    monkeypatch.setattr("app.core.media.time.time", lambda: 1_000_000.0)
    url = sign_media_path("/uploads/feedback/a.jpg")
    assert url.startswith("/uploads/feedback/a.jpg?exp=")
    q = parse_qs(urlsplit(url).query)
    assert verify_media_signature("/uploads/feedback/a.jpg", q["exp"][0], q["sig"][0])
    # 篡改路径 / 签名 / 过期均拒绝
    assert not verify_media_signature("/uploads/feedback/b.jpg", q["exp"][0], q["sig"][0])
    assert not verify_media_signature("/uploads/feedback/a.jpg", q["exp"][0], "deadbeef")
    monkeypatch.setattr("app.core.media.time.time", lambda: 1_000_000.0 + 86400 + 10)
    assert not verify_media_signature("/uploads/feedback/a.jpg", q["exp"][0], q["sig"][0])


def test_unsigned_or_external_url_passthrough():
    assert sign_media_path("https://example.com/x.png") == "https://example.com/x.png"
    assert not verify_media_signature("/uploads/x.jpg", None, None)


def test_strip_media_signature():
    dirty = "/uploads/ppt/a.pptx?exp=123&sig=abc&download=1"
    assert strip_media_signature(dirty) == "/uploads/ppt/a.pptx?download=1"
    assert strip_media_signature("/uploads/ppt/a.pptx?exp=1&sig=2") == "/uploads/ppt/a.pptx"
    assert strip_media_signature("https://example.com/a") == "https://example.com/a"


def test_sign_urls_in_json_recurses(monkeypatch):
    monkeypatch.setattr("app.core.media.time.time", lambda: 1_000_000.0)
    payload = {
        "media_urls": ["/uploads/f/1.jpg", "https://x/y.png"],
        "nested": {"logo": "/uploads/p/logo.png", "n": 1},
        "items": [{"url": "/uploads/f/2.jpg"}],
    }
    signed = sign_urls_in_json(payload)
    assert "sig=" in signed["media_urls"][0]
    assert signed["media_urls"][1] == "https://x/y.png"
    assert "sig=" in signed["nested"]["logo"]
    assert "sig=" in signed["items"][0]["url"]
    assert signed["nested"]["n"] == 1


# ---------- 生产配置校验 ----------


def test_startup_security_blocks_default_key_in_prod():
    cfg = Settings(APP_ENV="prod", SECRET_KEY="change-me-in-production")
    with pytest.raises(RuntimeError):
        validate_startup_security(cfg)


def test_startup_security_blocks_short_key_in_prod():
    cfg = Settings(APP_ENV="prod", SECRET_KEY="short-key")
    with pytest.raises(RuntimeError):
        validate_startup_security(cfg)


def test_startup_security_passes_with_strong_key_and_warns_in_dev():
    good = Settings(APP_ENV="prod", SECRET_KEY="x" * 48)
    assert validate_startup_security(good) == []
    dev = Settings(APP_ENV="dev", SECRET_KEY="change-me-in-production")
    assert validate_startup_security(dev)  # dev 仅告警不阻断


# ---------- 注册角色边界（纯函数） ----------


class _FakeUser:
    def __init__(self, role: Role):
        self.role = role.value


def test_admin_can_create_any_role():
    for role in Role:
        auth_router._assert_can_create_account(_FakeUser(Role.ADMIN), role)  # 不抛异常即通过


def test_staff_can_only_create_parent_and_student():
    staff = _FakeUser(Role.STAFF)
    auth_router._assert_can_create_account(staff, Role.PARENT)
    auth_router._assert_can_create_account(staff, Role.STUDENT)
    for role in (Role.ADMIN, Role.TEACHER, Role.STAFF):
        with pytest.raises(Exception):
            auth_router._assert_can_create_account(staff, role)


def test_teacher_cannot_create_accounts():
    with pytest.raises(Exception):
        auth_router._assert_can_create_account(_FakeUser(Role.TEACHER), Role.PARENT)


def test_anonymous_registration_closed_by_default(monkeypatch):
    monkeypatch.setattr(auth_router, "_in_pytest", lambda: False)

    class _DB:
        def scalar(self, *_a, **_k):  # 已有管理员
            return 1

    db = _DB()
    monkeypatch.setattr(auth_router, "get_settings", lambda: Settings(ALLOW_SELF_REGISTRATION=False))
    for role in (Role.ADMIN, Role.TEACHER, Role.PARENT, Role.STUDENT):
        assert not auth_router._anonymous_registration_allowed(db, role)


def test_anonymous_registration_self_service_only_parent_student(monkeypatch):
    monkeypatch.setattr(auth_router, "_in_pytest", lambda: False)

    class _DB:
        def scalar(self, *_a, **_k):
            return 1

    monkeypatch.setattr(auth_router, "get_settings", lambda: Settings(ALLOW_SELF_REGISTRATION=True))
    db = _DB()
    assert auth_router._anonymous_registration_allowed(db, Role.PARENT)
    assert auth_router._anonymous_registration_allowed(db, Role.STUDENT)
    assert not auth_router._anonymous_registration_allowed(db, Role.ADMIN)
    assert not auth_router._anonymous_registration_allowed(db, Role.TEACHER)


def test_anonymous_registration_bootstrap_admin_when_empty(monkeypatch):
    monkeypatch.setattr(auth_router, "_in_pytest", lambda: False)

    class _EmptyDB:
        def scalar(self, *_a, **_k):
            return 0

    monkeypatch.setattr(auth_router, "get_settings", lambda: Settings(ALLOW_SELF_REGISTRATION=False))
    assert auth_router._anonymous_registration_allowed(_EmptyDB(), Role.ADMIN)
    assert not auth_router._anonymous_registration_allowed(_EmptyDB(), Role.TEACHER)


# ---------- 限速器 ----------


def test_rate_limiter_blocks_after_limit():
    from fastapi import HTTPException

    key = "test:login:128.0.0.1"
    for _ in range(3):
        enforce(key, limit=3, window=60)
    with pytest.raises(HTTPException) as exc:
        enforce(key, limit=3, window=60)
    assert exc.value.status_code == 429
