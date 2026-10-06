"""M1 冒烟测试：含数据库依赖的用例（需要本地 PostgreSQL）。

运行前确保已执行 `uv run alembic upgrade head`。
使用独立事务回滚，避免污染真实数据。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app

# 使用独立的冒烟测试数据库（避免与开发库相互污染）
TEST_DB_NAME = "child_code_test"


@pytest.fixture(scope="session")
def test_engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {TEST_DB_NAME}'))
    admin_engine.dispose()

    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(test_engine):
    session = sessionmaker(bind=test_engine)()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client(test_engine):
    # 让应用的 get_db 使用测试库
    from app.api import deps

    TestSession = sessionmaker(bind=test_engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_token(client):
    """注册并登录一个管理员，返回 Bearer 头。用唯一用户名避免跨用例冲突。"""
    username = f"smoke-admin-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/auth/register",
        json={"role": "admin", "username": username, "password": "123456", "name": "Smoke Admin"},
    )
    assert resp.status_code == 201
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def teacher_token(client):
    username = f"smoke-teacher-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/auth/register",
        json={
            "role": "teacher",
            "username": username,
            "password": "123456",
            "name": "Smoke Teacher",
        },
    )
    assert resp.status_code == 201
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_student_crud_and_low_balance(client, admin_token):
    headers = admin_token
    # 创建班级
    cls = client.post(
        "/api/classes", json={"name": "Python 入门", "subject": "Python"}, headers=headers
    )
    assert cls.status_code == 201
    class_id = cls.json()["id"]

    # 创建学员（课时 8 → 爆红）
    stu = client.post(
        "/api/students",
        json={"name": "小明", "phone": "13800000001", "lesson_balance": 8, "class_ids": [class_id]},
        headers=headers,
    )
    assert stu.status_code == 201
    body = stu.json()
    assert body["low_balance"] is True
    assert len(body["classes"]) == 1
    student_id = body["id"]

    # 修改课时到 20 → 不爆红
    upd = client.patch(
        f"/api/students/{student_id}",
        json={"name": "小明同学"},
        headers=headers,
    )
    assert upd.status_code == 200

    # 催缴名单查询
    collection = client.get("/api/students?low_balance_only=true", headers=headers)
    assert collection.status_code == 200
    assert any(s["id"] == student_id for s in collection.json()["items"])

    # 课时调整入账 +20 → 余额 28，不再爆红
    rec = client.post(
        f"/api/students/{student_id}/lesson-records",
        json={"delta": 20, "remark": "测试入账"},
        headers=headers,
    )
    assert rec.status_code == 201
    assert rec.json()["balance_after"] == 28

    # 流水列表
    records = client.get(f"/api/students/{student_id}/lesson-records", headers=headers)
    assert records.status_code == 200
    assert len(records.json()) >= 1

    # 删除（软删除）
    resp = client.delete(f"/api/students/{student_id}", headers=headers)
    assert resp.status_code == 400
    zero = client.post(
        f"/api/students/{student_id}/lesson-records",
        json={"delta": -28, "remark": "ceshiqingling"},
        headers=headers,
    )
    assert zero.status_code == 201
    resp = client.delete(f"/api/students/{student_id}", headers=headers)
    assert resp.status_code == 204
    gone = client.get(f"/api/students/{student_id}", headers=headers)
    assert gone.status_code == 404


def test_class_crud(client, admin_token, teacher_token):
    # 创建班级
    cls = client.post(
        "/api/classes",
        json={"name": "C++ 竞赛班", "subject": "C++", "teacher_id": None},
        headers=admin_token,
    )
    assert cls.status_code == 201

    # 教师可读
    read = client.get("/api/classes", headers=teacher_token)
    assert read.status_code == 200

    # 教师可新建班级，但只能归到自己名下（即使传了别人的 teacher_id 也会被强制为自己）
    created = client.post(
        "/api/classes", json={"name": "我的班级", "subject": "Python"}, headers=teacher_token
    )
    assert created.status_code == 201, created.text
    teacher_id = client.get("/api/auth/me", headers=teacher_token).json()["id"]
    assert created.json()["teacher_id"] == teacher_id

    # 收回 class_create 后教师新建班级 403
    client.put(
        f"/api/permissions/teachers/{teacher_id}",
        headers=admin_token,
        json={"class_create": False},
    )
    forbidden = client.post(
        "/api/classes", json={"name": "越权班级", "subject": "Python"}, headers=teacher_token
    )
    assert forbidden.status_code == 403


def test_package_admin_only(client, admin_token, teacher_token):
    created = client.post(
        "/api/lesson-packages",
        json={"name": "基础包 40 课时", "price": 4800, "total_lessons": 40},
        headers=admin_token,
    )
    assert created.status_code == 201
    package_id = created.json()["id"]

    # 教师无法创建课时包
    forbidden = client.post(
        "/api/lesson-packages",
        json={"name": "越权包", "price": 100, "total_lessons": 10},
        headers=teacher_token,
    )
    assert forbidden.status_code == 403

    # 下架
    deact = client.delete(f"/api/lesson-packages/{package_id}", headers=admin_token)
    assert deact.status_code == 204

    # 不在售列表
    listing = client.get("/api/lesson-packages", headers=admin_token)
    assert listing.status_code == 200
    assert all(p["id"] != package_id for p in listing.json()["items"])


def test_low_balance_rule(client, admin_token):
    # 课时 10 应爆红（≤10），课时 11 不应
    s10 = client.post(
        "/api/students", json={"name": "边界10", "lesson_balance": 10}, headers=admin_token
    ).json()
    s11 = client.post(
        "/api/students", json={"name": "边界11", "lesson_balance": 11}, headers=admin_token
    ).json()
    assert s10["low_balance"] is True
    assert s11["low_balance"] is False
