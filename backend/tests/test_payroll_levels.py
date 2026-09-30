"""财务重构回归：教师级别 / 职务工资 / 提成规则 / 薪资核算 / 课时创收口径。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_payroll"


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
    username = f"{tag}-{role}"
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
    return _register(client, "admin", "payroll-admin")


def test_level_crud_and_guards(client, admin):
    # 新增级别 P9 12%
    r = client.post("/api/business/teacher-levels", json={"name": "P9", "ratio": "0.12"}, headers=admin)
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    assert r.json()["ratio_pct"] == "12.00"
    # 重名拒绝
    r = client.post("/api/business/teacher-levels", json={"name": "P9", "ratio": "0.1"}, headers=admin)
    assert r.status_code == 400
    # 改名 + 调比
    r = client.patch(f"/api/business/teacher-levels/{lid}", json={"name": "P9X", "ratio": "0.2"}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "P9X"
    # 新建教师挂级别 + 个人工资
    r = client.post(
        "/api/auth/teachers",
        json={"username": "lv-teacher", "password": "123456", "name": "级别教师",
              "teacher_level_id": lid, "base_salary": "6000"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    assert r.json()["teacher_level_name"] == "P9X"
    assert r.json()["base_salary"] == "6000.00"
    # 使用中不可删
    r = client.delete(f"/api/business/teacher-levels/{lid}", headers=admin)
    assert r.status_code == 400
    # 去掉教师级别后可删
    tid = r.json() if False else None
    teachers = client.get("/api/auth/teachers", headers=admin).json()["items"]
    t = next(x for x in teachers if x["username"] == "lv-teacher")
    r = client.patch(f"/api/auth/teachers/{t['id']}", json={"teacher_level_id": ""}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/business/teacher-levels/{lid}", headers=admin)
    assert r.status_code == 200, r.text


def test_posts_sync_and_payroll(client, admin):
    # 业务侧新建职务 -> 权限职务预设同步可见
    r = client.post("/api/business/posts", json={"name": "教务专员X", "base_salary": "4500"}, headers=admin)
    assert r.status_code == 201, r.text
    assert "hint" in r.json()
    titles = client.get("/api/permissions/job-titles", headers=admin).json()["items"]
    jt = next(x for x in titles if x["name"] == "教务专员X")
    assert jt["permissions"] == {}
    # 权限侧可设工资
    r = client.put(f"/api/permissions/job-titles/{jt['id']}",
                   json={"name": "教务专员X", "permissions": {}, "base_salary": "4800"}, headers=admin)
    assert r.status_code == 200 and r.json()["base_salary"] == "4800.00"
    # 在用职务不可删
    r = client.post("/api/auth/teachers", json={"username": "post-teacher", "password": "123456",
                                                 "name": "职务教师", "title": "教务专员X"}, headers=admin)
    assert r.status_code == 201, r.text
    r = client.delete(f"/api/permissions/job-titles/{jt['id']}", headers=admin)
    assert r.status_code == 400
    # 提成规则可调
    rules = client.get("/api/business/commission-rules", headers=admin).json()["items"]
    assert {x["key"] for x in rules} >= {"invite", "trial", "convert", "renew", "refer", "trial_lesson"}
    r = client.put("/api/business/commission-rules",
                   json=[{**x, "amount": "10"} if x["key"] == "invite" else x for x in rules],
                   headers=admin)
    assert r.status_code == 200
    # 薪资核算：基本工资取职务 4800 + 邀约2人×10 + 转化1单
    teachers = client.get("/api/auth/teachers", headers=admin).json()["items"]
    t = next(x for x in teachers if x["username"] == "post-teacher")
    convert_amt = next(x["amount"] for x in r.json()["items"] if x["key"] == "convert")
    r = client.post("/api/business/payroll/compute",
                    json={"user_id": t["id"], "month": "2026-09", "invite_count": 2,
                          "convert_count": 1, "lesson_commission": "100"},
                    headers=admin)
    assert r.status_code == 200, r.text
    expected = 4800 + 2 * 10 + float(convert_amt) + 100
    assert abs(float(r.json()["total"]) - expected) < 0.01
    # 工作台可见
    wb = client.get("/api/business/workbench", params={"month": "2026-09"}, headers=admin)
    assert wb.status_code == 200
    row = next(x for x in wb.json()["items"] if x["user_id"] == t["id"])
    assert row["has_entry"] is True


def test_order_and_lesson_stats_shape(client, admin):
    r = client.get("/api/finance/order-stats", headers=admin)
    assert r.status_code == 200, r.text
    assert "summary" in r.json()
    s = r.json()["summary"]
    assert {"orders", "paid", "unpaid", "refunded_count", "pay_rate", "paid_amount", "refunds"} <= set(s)
    r = client.get("/api/finance/lesson-stats", headers=admin)
    assert r.status_code == 200, r.text
    assert {"planned_lessons", "consumed_lessons", "consume_rate", "revenue", "commission", "profit"} <= set(r.json())
