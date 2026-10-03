"""体验课链路：邀约 → 体验学员 → 免费考勤 → 报名/薪资统计。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_trial"


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
    tok = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=tok).json()
    return tok, me["id"]


def test_trial_pipeline(client):
    admin, _ = _register(client, "admin", "trial-admin")
    teacher, teacher_id = _register(client, "teacher", "trial-teacher")

    subj = client.post(
        "/api/business/subjects",
        json={"name": f"体验-{uuid.uuid4().hex[:4]}", "per_session": 2},
        headers=admin,
    )
    assert subj.status_code == 201, subj.text
    subj = subj.json()

    # 1. 邀约记录
    inv = client.post(
        "/api/trials/invitations",
        json={
            "parent_name": "王家长",
            "parent_phone": "13800001111",
            "student_name": "小王",
            "subject_id": subj["id"],
            "remark": "有意向",
        },
        headers=teacher,
    )
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    assert inv["status"] == "invited"

    # 2. 建体验学员
    ts = client.post(f"/api/trials/invitations/{inv['id']}/trial-student", headers=teacher)
    assert ts.status_code == 201, ts.text
    sid = ts.json()["id"]
    assert ts.json()["trial_status"] == "trial"

    # 3. 排体验课（正式班级 + 体验标记）
    cls = client.post(
        "/api/classes", json={"name": f"班-{uuid.uuid4().hex[:4]}", "subject": subj["name"]}, headers=admin
    )
    assert cls.status_code == 201, cls.text
    from datetime import datetime, timedelta

    start = datetime.now() - timedelta(hours=2)
    sched = client.post(
        "/api/schedules",
        json={
            "class_id": cls.json()["id"],
            "teacher_id": teacher_id,
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(hours=1)).isoformat(),
            "is_trial": True,
        },
        headers=admin,
    )
    assert sched.status_code == 201, sched.text
    sched = sched.json()["schedule"]
    assert sched["is_trial"] is True

    # 4. 关联排课 + 通知教师
    upd = client.patch(
        f"/api/trials/invitations/{inv['id']}",
        json={
            "status": "scheduled",
            "trial_schedule_id": sched["id"],
            "trial_class_id": cls.json()["id"],
            "trial_teacher_id": teacher_id,
        },
        headers=teacher,
    )
    assert upd.status_code == 200, upd.text
    notifs = client.get("/api/notifications", headers=teacher).json()
    items = notifs["items"] if isinstance(notifs, dict) else notifs
    assert any("体验课" in (n.get("title") or "") for n in items)

    # 5. 体验考勤：免费，不扣课时不计创收
    att = client.post(
        f"/api/schedules/{sched['id']}/attendance",
        json={"items": [{"student_id": sid, "status": "attended"}]},
        headers=teacher,
    )
    assert att.status_code == 200, att.text
    assert not att.json()["errors"], att.json()
    rec = att.json()["lesson_records"][0]
    assert rec["delta"] == 0 and rec.get("is_trial") is True
    bal = client.get(f"/api/students/{sid}", headers=admin).json()
    assert float(bal["lesson_balance"]) == 0

    # 6. 报名成功：转正式 + 口碑标记
    done = client.patch(
        f"/api/trials/students/{sid}/trial-status",
        json={"trial_status": "signed", "source": "referral", "referrer": "李家长"},
        headers=admin,
    )
    assert done.status_code == 200, done.text
    assert done.json()["trial_status"] == "signed"
    assert done.json()["source"] == "referral"

    # 7. 薪资统计自动带出
    stats = client.get("/api/trials/payroll-stats", params={"user_id": teacher_id}, headers=admin)
    assert stats.status_code == 200, stats.text
    stats = stats.json()
    assert stats["trial_lesson_count"] == 1
    assert stats["convert_count"] == 1
    assert stats["refer_count"] == 1
    sstats = client.get("/api/trials/payroll-stats", headers=teacher)
    assert sstats.status_code == 200, sstats.text
    assert sstats.json()["invite_count"] == 1
    assert sstats.json()["trial_count"] == 1


def test_classless_trial_and_class_conflict(client):
    admin, _ = _register(client, "admin", "trial2-admin")
    teacher, teacher_id = _register(client, "teacher", "trial2-teacher")
    teacher2, teacher2_id = _register(client, "teacher", "trial2-teacher2")
    cls = client.post(
        "/api/classes", json={"name": f"班-{uuid.uuid4().hex[:4]}", "subject": "Python"}, headers=admin
    )
    assert cls.status_code == 201, cls.text
    from datetime import datetime, timedelta

    base = datetime.now().replace(microsecond=0) - timedelta(days=1)
    payload = {
        "class_id": cls.json()["id"],
        "teacher_id": teacher_id,
        "start_time": base.isoformat(),
        "end_time": (base + timedelta(hours=1)).isoformat(),
    }
    r1 = client.post("/api/schedules", json=payload, headers=admin)
    assert r1.status_code == 201 and r1.json()["created"], r1.text

    # 同班同时段换教师 → 冲突（不再允许）
    payload2 = dict(payload, teacher_id=teacher2_id)
    r2 = client.post("/api/schedules", json=payload2, headers=admin)
    assert r2.status_code == 201, r2.text
    assert r2.json()["created"] is False
    assert r2.json()["conflicts"], "同班同时段应判冲突"

    # 无班级体验课：只排教师空余时段
    payload3 = {
        "class_id": None,
        "teacher_id": teacher2_id,
        "start_time": (base + timedelta(hours=2)).isoformat(),
        "end_time": (base + timedelta(hours=3)).isoformat(),
        "is_trial": True,
    }
    r3 = client.post("/api/schedules", json=payload3, headers=admin)
    assert r3.status_code == 201, r3.text
    assert r3.json()["created"] is True
    assert r3.json()["schedule"]["class_id"] is None
    assert r3.json()["schedule"]["is_trial"] is True
