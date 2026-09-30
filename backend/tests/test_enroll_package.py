"""新生入学选购课时包：生成已确认订单 + 充值流水，FIFO 单价可查。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_enroll_pkg"


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
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return _register(client, "admin", "enroll-admin")


def test_enroll_with_package_creates_confirmed_order(client, admin):
    pkg = client.post(
        "/api/lesson-packages",
        json={"name": "新生包", "price": "3000.00", "total_lessons": 20},
        headers=admin,
    )
    assert pkg.status_code == 201, pkg.text
    pkg = pkg.json()

    # 不选包：余额为手工值（兼容旧行为）
    plain = client.post(
        "/api/students", json={"name": "无包学员", "lesson_balance": 5, "class_ids": []}, headers=admin
    )
    assert plain.status_code == 201, plain.text
    assert float(plain.json()["lesson_balance"]) == 5

    # 选包：忽略手工课时，按课时包充值
    stu = client.post(
        "/api/students",
        json={"name": "新生", "lesson_balance": 99, "package_id": pkg["id"], "class_ids": []},
        headers=admin,
    )
    assert stu.status_code == 201, stu.text
    stu = stu.json()
    assert float(stu["lesson_balance"]) == 20

    # 已确认订单 + 充值流水
    orders = client.get("/api/orders", params={"student_id": stu["id"]}, headers=admin)
    assert orders.status_code == 200, orders.text
    confirmed = [o for o in orders.json()["items"] if o["status"] == "confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0]["package_id"] == pkg["id"]
    recs = client.get(f"/api/students/{stu['id']}/lesson-records", headers=admin)
    assert recs.status_code == 200, recs.text
    recharge = [r for r in recs.json() if r["record_type"] == "recharge" and float(r["delta"]) == 20]
    assert len(recharge) == 1

    # 不存在的包 404
    bad = client.post(
        "/api/students",
        json={"name": "坏包学员", "package_id": str(uuid.uuid4()), "class_ids": []},
        headers=admin,
    )
    assert bad.status_code == 404
