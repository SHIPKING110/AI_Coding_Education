"""薪资自动核算 + 锁定语义 + 溯源明细。"""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_autopay"


@pytest.fixture()
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


def test_auto_compute_and_lock(client):
    admin, _ = _register(client, "admin", "ap-admin")
    teacher, teacher_id = _register(client, "teacher", "ap-teacher")
    mon = datetime.now().strftime("%Y-%m")

    # 邀约一条（计邀约数）
    inv = client.post(
        "/api/trials/invitations",
        json={"parent_name": "P", "student_name": "S"},
        headers=teacher,
    )
    assert inv.status_code == 201, inv.text

    # 自动核算：应生成 entry（auto=true）
    r = client.post("/api/business/payroll/auto-compute", params={"month": mon}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["computed"] >= 1
    entries = client.get("/api/business/payroll", params={"month": mon}, headers=admin).json()["items"]
    mine = [e for e in entries if e["user_id"] == teacher_id]
    assert mine and mine[0]["auto"] is True
    assert mine[0]["invite_count"] == 1

    # 溯源明细：邀约名单
    ev = client.get(
        "/api/trials/payroll-evidence",
        params={"kind": "invite", "month": mon, "user_id": teacher_id},
        headers=admin,
    )
    assert ev.status_code == 200, ev.text
    assert ev.json()["count"] == 1
    assert ev.json()["items"][0]["student_name"] == "S"

    # 手工锁定（compute 不带 auto → auto=false）
    lock = client.post(
        "/api/business/payroll/compute",
        json={"user_id": teacher_id, "month": mon, "invite_count": 5},
        headers=admin,
    )
    assert lock.status_code == 200, lock.text
    assert lock.json()["auto"] is False

    # 再次自动核算：锁定过的应跳过，invite_count 保持手工值 5
    r2 = client.post("/api/business/payroll/auto-compute", params={"month": mon}, headers=admin)
    assert r2.json()["skipped"] >= 1
    entries2 = client.get("/api/business/payroll", params={"month": mon}, headers=admin).json()["items"]
    mine2 = [e for e in entries2 if e["user_id"] == teacher_id][0]
    assert mine2["invite_count"] == 5
