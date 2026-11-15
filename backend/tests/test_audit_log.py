"""M-A 0.8 审计日志 + 强制改密端到端回归。

覆盖：代建账号一次性临时密码 → 登录后被拦截其他接口 → 改密后放行；
账号创建/重置/权限/设置变更写入审计；审计查询仅管理员可用、敏感字段脱敏。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.main import app
from app.models.audit import AuditLog

TEST_DB_NAME = "child_code_audit_test"


@pytest.fixture(scope="session")
def test_engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(test_engine):
    from app.api import deps

    TestSession = sessionmaker(bind=test_engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    c = TestClient(app)
    c.test_session_factory = TestSession  # type: ignore[attr-defined]
    yield c
    app.dependency_overrides.clear()


def _register(client, role: str, tag: str, headers: dict | None = None) -> dict:
    username = f"{tag}-{uuid.uuid4().hex[:8]}"
    payload = {"role": role, "username": username, "password": "12345678a", "name": tag}
    if headers is not None:
        payload.pop("password")
    r = client.post("/api/auth/register", json=payload, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin_token(client):
    admin = _register(client, "admin", "adm")
    return _login(client, admin["username"], "12345678a")


def test_temp_password_flow_forces_change(client, admin_token):
    """管理员代建账号（不传密码）→ 一次性临时密码 → 强制改密门禁 → 改密后放行。"""
    parent = _register(client, "parent", "par", headers=admin_token)
    temp = parent["initial_password"]
    assert temp and len(temp) >= 8
    assert parent["must_change_password"] is True

    token = _login(client, parent["username"], temp)

    # 强制改密状态下：/auth/me 可用，业务接口 403 password_change_required
    me = client.get("/api/auth/me", headers=token)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True
    blocked = client.get("/api/students", headers=token)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "password_change_required"

    # 改密后放行且标记清除
    ch = client.post(
        "/api/auth/me/password",
        json={"old_password": temp, "new_password": "NewPass123"},
        headers=token,
    )
    assert ch.status_code == 200, ch.text
    assert ch.json()["must_change_password"] is False
    # 旧 token 仍指向同一用户，门禁按库内标记判断 → 放行
    assert client.get("/api/auth/me", headers=token).status_code == 200

    # 新密码可登录，旧临时密码失效
    _login(client, parent["username"], "NewPass123")
    bad = client.post(
        "/api/auth/login", json={"username": parent["username"], "password": temp}
    )
    assert bad.status_code == 401


def test_register_policy_blocks_anonymous_teacher(client):
    """已登录教师无权代建账号（角色边界；匿名策略见 test_security_hardening 单测）。"""
    teacher = _register(client, "teacher", "tch")
    token = _login(client, teacher["username"], "12345678a")
    r = client.post(
        "/api/auth/register",
        json={
            "role": "parent",
            "username": f"x-{uuid.uuid4().hex[:6]}",
            "password": "12345678a",
            "name": "x",
        },
        headers=token,
    )
    assert r.status_code == 403


def test_audit_rows_written_and_readable(client, admin_token, test_engine):
    """关键操作留痕：建号/重置/权限/设置；管理员可查、教师不可查；敏感字段脱敏。"""
    # 建号（管理员代建，触发 user.create）
    parent = _register(client, "parent", "auditp", headers=admin_token)

    # 重置密码（触发 user.reset_password）
    r = client.patch(
        f"/api/auth/users/{parent['id']}/password",
        json={"new_password": "ResetPass123"},
        headers=admin_token,
    )
    assert r.status_code == 200, r.text

    # 权限更新（触发 permissions.update）
    teacher = _register(client, "teacher", "auditt")
    r = client.put(
        f"/api/permissions/teachers/{teacher['id']}",
        json={"teacher_view": True, "finance_view": True},
        headers=admin_token,
    )
    assert r.status_code == 200, r.text

    # 设置更新（触发 settings.update）
    r = client.put(
        "/api/system-settings",
        json={"login_title": "审计测试标题"},
        headers=admin_token,
    )
    assert r.status_code == 200, r.text

    Session = client.test_session_factory
    db = Session()
    try:
        actions = [row.action for row in db.scalars(select(AuditLog)).all()]
        assert "user.create" in actions
        assert "user.reset_password" in actions
        assert "permissions.update" in actions
        assert "settings.update" in actions
        # 敏感字段不落库
        rows = db.scalars(select(AuditLog)).all()
        blob = str([(r.before, r.after) for r in rows])
        assert "ResetPass123" not in blob and "12345678a" not in blob
    finally:
        db.close()

    # 管理员可查
    logs = client.get("/api/audit/logs", params={"limit": 100}, headers=admin_token)
    assert logs.status_code == 200
    assert logs.json()["total"] >= 4
    assert any(item["action"] == "user.reset_password" for item in logs.json()["items"])

    # 教师不可查
    t_token = _login(client, teacher["username"], "12345678a")
    forbidden = client.get("/api/audit/logs", headers=t_token)
    assert forbidden.status_code == 403
