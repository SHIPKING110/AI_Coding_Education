"""调课时带单价入账本 + 总流水 + 最近购包单价。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_adjust"


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
    return _register(client, "admin", "adj-admin")


def test_priced_adjust_and_global_records(client, admin):
    pkg = client.post(
        "/api/lesson-packages",
        json={"name": "补课包", "price": "2000.00", "total_lessons": 10},
        headers=admin,
    )
    assert pkg.status_code == 201, pkg.text
    pkg = pkg.json()

    stu = client.post(
        "/api/students",
        json={"name": "调账学员", "package_id": pkg["id"], "class_ids": []},
        headers=admin,
    )
    assert stu.status_code == 201, stu.text
    sid = stu.json()["id"]
    assert float(stu.json()["lesson_balance"]) == 10

    # 最近购包单价 200
    lp = client.get(f"/api/students/{sid}/last-price", headers=admin)
    assert lp.status_code == 200, lp.text
    assert float(lp.json()["price"]) == 200

    # 调增 2 课时 @200 → 余额 12，金额 +400
    adj = client.post(
        f"/api/students/{sid}/lesson-records",
        json={"delta": 2, "unit_price": 200, "remark": "扣错回补"},
        headers=admin,
    )
    assert adj.status_code == 201, adj.text
    adj = adj.json()
    assert float(adj["amount"]) == 400
    assert float(adj["unit_price"]) == 200

    # 调减 1 课时 @200 → 余额 11，金额 -200（冲销）
    adj2 = client.post(
        f"/api/students/{sid}/lesson-records",
        json={"delta": -1, "unit_price": 200, "remark": "多送扣回"},
        headers=admin,
    )
    assert adj2.status_code == 201, adj2.text
    assert float(adj2.json()["amount"]) == -200

    # 无单价调整：只调数量，无金额
    adj3 = client.post(
        f"/api/students/{sid}/lesson-records",
        json={"delta": 1, "remark": "纯数量调整"},
        headers=admin,
    )
    assert adj3.status_code == 201, adj3.text
    assert adj3.json()["amount"] is None

    bal = client.get(f"/api/students/{sid}", headers=admin).json()
    assert float(bal["lesson_balance"]) == 12

    # 总流水：按学员筛选，汇总金额 +400-200=+200
    recs = client.get(
        "/api/finance/records",
        params={"keyword": "调账学员", "limit": 50},
        headers=admin,
    )
    assert recs.status_code == 200, recs.text
    body = recs.json()
    assert body["total"] >= 4
    assert body["summary"]["amount_net"] == "200.00"
    assert all(r["student_name"] == "调账学员" for r in body["items"])
