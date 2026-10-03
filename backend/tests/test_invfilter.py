"""邀约筛选（校区/邀约人/体验教师/时间范围）+ 权限新导航键回归。"""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_invfilter"


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


def test_invitation_filters(client):
    admin, _ = _register(client, "admin", "if-admin")
    teacher, teacher_id = _register(client, "teacher", "if-teacher")
    teacher2, teacher2_id = _register(client, "teacher", "if-teacher2")

    inv = client.post(
        "/api/trials/invitations",
        json={"parent_name": "P1", "student_name": "S1"},
        headers=teacher,
    )
    assert inv.status_code == 201, inv.text
    inv_id = inv.json()["id"]

    # 关联体验教师
    upd = client.patch(
        f"/api/trials/invitations/{inv_id}",
        json={"trial_teacher_id": teacher2_id},
        headers=admin,
    )
    assert upd.status_code == 200, upd.text

    base = {"headers": admin}
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    r = client.get("/api/trials/invitations", params={"trial_teacher_id": teacher2_id}, headers=admin)
    assert r.status_code == 200 and r.json()["total"] == 1, r.text
    r = client.get("/api/trials/invitations", params={"trial_teacher_id": teacher_id}, headers=admin)
    assert r.json()["total"] == 0
    r = client.get("/api/trials/invitations", params={"staff_id": teacher_id}, headers=admin)
    assert r.json()["total"] == 1
    r = client.get(
        "/api/trials/invitations",
        params={"date_from": yesterday, "date_to": tomorrow},
        headers=admin,
    )
    assert r.json()["total"] == 1
    assert "staff_campus" in r.json()["items"][0]
    r = client.get(
        "/api/trials/invitations",
        params={"date_from": "2000-01-01", "date_to": "2000-01-02"},
        headers=admin,
    )
    assert r.json()["total"] == 0
    _ = base, today


def test_permission_keys_include_new_navs(client):
    admin, _ = _register(client, "admin", "pk-admin")
    r = client.get("/api/permissions/keys", headers=admin)
    assert r.status_code == 200, r.text
    keys = {k["key"] for k in r.json()["keys"]}
    assert {"nav_invitations", "nav_finance", "nav_settings"} <= keys
