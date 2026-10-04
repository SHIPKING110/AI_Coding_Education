"""时区回归：前端提交无时区本地时间，后端应按业务时区（Asia/Shanghai）解释并原样回读。

背景：容器默认 UTC 时会把 09:00 当作 09:00 UTC 存，回读成 17:00（+8 偏移）。
本用例锁定：会话时区 = BUSINESS_TIMEZONE，且存入/取出的小时不变。
"""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_tz"


@pytest.fixture()
def test_engine():
    base = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(
        base + f"/{TEST_DB_NAME}",
        connect_args={"options": f"-c timezone={get_settings().BUSINESS_TIMEZONE}"},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(test_engine):
    TestingSession = sessionmaker(bind=test_engine)

    def override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _register(client, role, tag):
    username = f"{tag}-{role}-{uuid.uuid4().hex[:5]}"
    r = client.post(
        "/api/auth/register",
        json={"role": role, "username": username, "password": "123456", "name": tag},
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    tok = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=tok).json()
    return tok, me["id"]


def test_db_session_timezone_is_business_tz(test_engine):
    with test_engine.connect() as conn:
        tz = conn.execute(text("SHOW timezone")).scalar()
    assert tz == get_settings().BUSINESS_TIMEZONE


def test_app_engine_uses_business_tz():
    """应用自身引擎必须固定会话时区，否则容器(UTC)下排课会 +8 偏移。"""
    from app.core.database import engine as app_engine

    with app_engine.connect() as conn:
        tz = conn.execute(text("SHOW timezone")).scalar()
    assert tz == get_settings().BUSINESS_TIMEZONE


def test_naive_local_time_roundtrip_keeps_hour(client):
    admin, admin_id = _register(client, "admin", "tz-admin")
    # 未来某天，提交无时区本地串 09:00（模拟前端 datetime-local）
    future = (datetime.now() + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0)
    naive = future.strftime("%Y-%m-%dT%H:%M:%S")
    r = client.post(
        "/api/schedules",
        json={
            "class_id": None,
            "teacher_id": admin_id,
            "start_time": naive,
            "end_time": future.replace(hour=10, minute=30).strftime("%Y-%m-%dT%H:%M:%S"),
        },
        headers=admin,
    )
    assert r.status_code in (200, 201), r.text
    out = r.json()["schedule"]["start_time"]
    # 回读应为 09:00（偏移 +08:00），而不是被当成 UTC 后变成 17:00
    assert "09:00" in out, out
    assert "T17:00" not in out, out
