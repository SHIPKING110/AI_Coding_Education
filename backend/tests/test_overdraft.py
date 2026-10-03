"""欠费上课：透支上限 + 欠费定价挂应收 + 续费自动抵扣。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_overdraft"


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
    return _register(client, "admin", "od-admin")


def _teacher(client, admin):
    t = _register(client, "teacher", "od-teacher")
    me = client.get("/api/auth/me", headers=t).json()
    return t, me["id"]


def _subject(client, admin, name="Python"):
    r = client.post(
        "/api/business/subjects",
        json={"name": f"{name}-{uuid.uuid4().hex[:4]}", "per_session": 2},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _class(client, admin, teacher_id, subject_name):
    r = client.post(
        "/api/classes",
        json={"name": f"班-{uuid.uuid4().hex[:4]}", "subject": subject_name},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


_sched_counter = {"n": 0}


def _schedule(client, admin, class_id, teacher_id):
    from datetime import datetime, timedelta

    _sched_counter["n"] += 1
    base = datetime.now() - timedelta(days=_sched_counter["n"], hours=2)
    start = base
    end = base + timedelta(hours=1)
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": teacher_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert isinstance(body, dict) and body.get("schedule"), body
    return body["schedule"]


def test_overdraft_consume_repay(client, admin):
    t_headers, teacher_id = _teacher(client, admin)
    pkg = client.post(
        "/api/lesson-packages",
        json={"name": "欠费包", "price": "2000.00", "total_lessons": 10},
        headers=admin,
    ).json()
    subj = _subject(client, admin)
    cls = _class(client, admin, teacher_id, subj["name"])

    # 入学购包 10 节 @200
    stu = client.post(
        "/api/students",
        json={"name": "欠费学员", "package_id": pkg["id"], "class_ids": [cls["id"]]},
        headers=admin,
    )
    assert stu.status_code == 201, stu.text
    sid = stu.json()["id"]

    # 上 5 次课（每次 2 节）→ 余额 0
    for _ in range(5):
        sched = _schedule(client, admin, cls["id"], teacher_id)
        r = client.post(
            f"/api/schedules/{sched['id']}/attendance",
            json={"items": [{"student_id": sid, "status": "attended"}]},
            headers=t_headers,
        )
        assert r.status_code == 200, r.text
        assert not r.json()["errors"], r.json()

    bal = client.get(f"/api/students/{sid}", headers=admin).json()
    assert float(bal["lesson_balance"]) == 0

    # 第 6 次：余额 0 也能考勤 → -2（欠费），按最近购包价 200 记账
    sched2 = _schedule(client, admin, cls["id"], teacher_id)
    r = client.post(
        f"/api/schedules/{sched2['id']}/attendance",
        json={"items": [{"student_id": sid, "status": "attended"}]},
        headers=t_headers,
    )
    assert r.status_code == 200, r.text
    assert not r.json()["errors"], r.json()

    bal = client.get(f"/api/students/{sid}", headers=admin).json()
    assert float(bal["lesson_balance"]) == -2
    assert float(bal["arrears_lessons"]) == 2
    assert bal["arrears_amount"] == "400.00"

    # 账本：欠费行挂应收标记
    stats = client.get("/api/finance/lesson-stats", headers=admin).json()
    assert float(stats["overdraft_lessons"]) == 2
    assert stats["overdraft_revenue"] == "400.00"
    assert stats["receivable"] == "400.00"
    assert stats["debtors"] == 1

    # 透支上限：默认 10，再欠 4 次（8 节）到 -10，第 5 次应被拒绝
    for _ in range(4):
        s = _schedule(client, admin, cls["id"], teacher_id)
        rr = client.post(
            f"/api/schedules/{s['id']}/attendance",
            json={"items": [{"student_id": sid, "status": "attended"}]},
            headers=t_headers,
        )
        assert not rr.json()["errors"], rr.json()
    s = _schedule(client, admin, cls["id"], teacher_id)
    rr = client.post(
        f"/api/schedules/{s['id']}/attendance",
        json={"items": [{"student_id": sid, "status": "attended"}]},
        headers=t_headers,
    )
    assert rr.json()["errors"], "透支超过上限应被拒绝"

    # 续费 20 节：自动先还 10 节欠款
    renew = client.post(
        f"/api/students/{sid}/renew",
        json={"custom_lessons": 20, "custom_amount": 4000},
        headers=admin,
    )
    assert renew.status_code == 200, renew.text
    bal = client.get(f"/api/students/{sid}", headers=admin).json()
    assert float(bal["lesson_balance"]) == 10
    recs = client.get(f"/api/students/{sid}/lesson-records", headers=admin).json()
    assert any("还欠款" in (r["remark"] or "") for r in recs)

    # 还清后应收清零
    stats = client.get("/api/finance/lesson-stats", headers=admin).json()
    assert stats["receivable"] == "0.00"
