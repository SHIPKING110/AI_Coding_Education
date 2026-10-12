"""教师权限：默认全开；管理员可逐项关闭；硬性规则（本人班级/空班删除）始终生效。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models.enrollment import Class, Student
from app.models.user import User

TEST_DB_NAME = "child_code_test_perm"


def _engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client():
    import app.core.security as sec

    engine = _engine()
    Session = sessionmaker(bind=engine)
    with Session() as s:
        admin = User(id=uuid.uuid4(), role="admin", username=f"a{uuid.uuid4().hex[:5]}", name="管", password_hash="x")
        t1 = User(id=uuid.uuid4(), role="teacher", username=f"t1{uuid.uuid4().hex[:5]}", name="王", password_hash="x")
        t2 = User(id=uuid.uuid4(), role="teacher", username=f"t2{uuid.uuid4().hex[:5]}", name="李", password_hash="x")
        s.add_all([admin, t1, t2])
        s.flush()
        c1 = Class(id=uuid.uuid4(), name="王班", subject="Python", teacher_id=t1.id)
        cb = Class(id=uuid.uuid4(), name="李班", subject="Scratch", teacher_id=t2.id)
        s.add_all([c1, cb])
        s.flush()
        stu = Student(id=uuid.uuid4(), name="小明", lesson_balance=0, status="active")
        s.add(stu)
        s.commit()
        ids = {"admin": admin.id, "t1": t1.id, "t2": t2.id, "c1": c1.id, "cb": cb.id, "stu": stu.id}

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    tokens = {k: sec.create_access_token(str(v)) for k, v in ids.items() if k in ("admin", "t1", "t2")}
    try:
        yield TestClient(app), ids, tokens
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _h(tokens, who):
    return {"Authorization": f"Bearer {tokens[who]}"}


def test_default_all_open(client):
    c, ids, tokens = client
    # 教师默认可新建学员、可调班级
    r = c.post("/api/students", headers=_h(tokens, "t1"), json={"name": "小红"})
    assert r.status_code == 201, r.text
    r = c.patch(f"/api/students/{ids['stu']}/classes", headers=_h(tokens, "t1"), json={"class_ids": [str(ids["c1"])]})
    assert r.status_code == 200, r.text


def test_admin_can_revoke_and_teacher_blocked(client):
    c, ids, tokens = client
    r = c.put(
        f"/api/permissions/teachers/{ids['t1']}",
        headers=_h(tokens, "admin"),
        json={"student_create": False, "class_unenroll": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["permissions"]["student_create"] is False
    # 被收权后教师新建学员/调班均 403
    r = c.post("/api/students", headers=_h(tokens, "t1"), json={"name": "小黑"})
    assert r.status_code == 403, r.text
    r = c.patch(f"/api/students/{ids['stu']}/classes", headers=_h(tokens, "t1"), json={"class_ids": []})
    assert r.status_code == 403, r.text
    # mine 接口如实返回
    r = c.get("/api/permissions/mine", headers=_h(tokens, "t1"))
    assert r.json()["permissions"]["student_create"] is False


def test_expanded_keys_enforced(client):
    c, ids, tokens = client
    # 默认：教师不可删学员、不可见订单（保持现有行为）；排课查看与新建保持开放
    r = c.delete(f"/api/students/{ids['stu']}", headers=_h(tokens, "t1"))
    assert r.status_code == 403, r.text
    r = c.get("/api/orders", headers=_h(tokens, "t1"))
    assert r.status_code == 403, r.text
    r = c.get("/api/schedules", headers=_h(tokens, "t1"))
    assert r.status_code == 200, r.text
    # 管理员收权后排课不可见，重新开通后恢复
    c.put(f"/api/permissions/teachers/{ids['t1']}", headers=_h(tokens, "admin"),
          json={"schedule_create": False})
    r = c.get("/api/schedules", headers=_h(tokens, "t1"))
    assert r.status_code == 403, r.text
    # 管理员逐项开通后放行
    r = c.put(
        f"/api/permissions/teachers/{ids['t1']}",
        headers=_h(tokens, "admin"),
        json={"student_delete": True, "order_visible": True, "schedule_create": True},
    )
    assert r.status_code == 200, r.text
    r = c.get("/api/orders", headers=_h(tokens, "t1"))
    assert r.status_code == 200, r.text
    r = c.get("/api/schedules", headers=_h(tokens, "t1"))
    assert r.status_code == 200, r.text
    r = c.delete(f"/api/students/{ids['stu']}", headers=_h(tokens, "t1"))
    assert r.status_code == 204, r.text


def test_teacher_crud_gated(client):
    c, ids, tokens = client
    # 默认：教师不可新增/编辑/删除教师，但可查看
    r = c.get("/api/auth/teachers", headers=_h(tokens, "t1"))
    assert r.status_code == 200, r.text
    r = c.post(
        "/api/auth/teachers",
        headers=_h(tokens, "t1"),
        json={"username": f"nt{ids['t1'].hex[:4]}", "password": "123456", "name": "新教师"},
    )
    assert r.status_code == 403, r.text
    # 开通新增后可建，且职务预设自动套用
    r = c.post("/api/permissions/job-titles", headers=_h(tokens, "admin"),
               json={"name": "助教", "permissions": {"student_create": False}})
    assert r.status_code == 201, r.text
    c.put(f"/api/permissions/teachers/{ids['t1']}", headers=_h(tokens, "admin"),
          json={"teacher_add": True})
    r = c.post(
        "/api/auth/teachers",
        headers=_h(tokens, "t1"),
        json={"username": f"nt{ids['t1'].hex[:4]}", "password": "123456", "name": "新教师", "title": "助教"},
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    r = c.get("/api/permissions/teachers", headers=_h(tokens, "admin"))
    row = next(x for x in r.json()["items"] if x["teacher_id"] == new_id)
    assert row["permissions"]["student_create"] is False


def test_teacher_cannot_touch_other_teachers_class(client):
    c, ids, tokens = client
    # 王老师改李老师的班 → 403
    r = c.patch(f"/api/classes/{ids['cb']}", headers=_h(tokens, "t1"), json={"name": "改名"})
    assert r.status_code == 403, r.text
    # 王老师删李老师的班 → 403
    r = c.delete(f"/api/classes/{ids['cb']}", headers=_h(tokens, "t1"))
    assert r.status_code == 403, r.text


def test_system_settings_public_read_admin_write(client):
    c, ids, tokens = client
    # 公开读（未登录也可，用于登录页渲染）
    r = c.get("/api/system-settings")
    assert r.status_code == 200, r.text
    assert r.json()["ui_theme"] == "default"
    # 教师不可写
    r = c.put("/api/system-settings", headers=_h(tokens, "t1"), json={"ui_theme": "fresh"})
    assert r.status_code == 403, r.text
    # 管理员可写；非法值 400
    r = c.put("/api/system-settings", headers=_h(tokens, "admin"), json={"ui_theme": "nope"})
    assert r.status_code == 400, r.text
    r = c.put(
        "/api/system-settings",
        headers=_h(tokens, "admin"),
        json={"ui_theme": "calm", "login_theme": "light", "desktop_bg": "#ecfdf5"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ui_theme"] == "calm"
    r = c.get("/api/system-settings")
    assert r.json()["desktop_bg"] == "#ecfdf5"


def test_teacher_only_own_schedules(client):
    c, ids, tokens = client
    # t1 新建排课指定别的教师 → 实际排给自己
    other = ids["t2"]
    r = c.post(
        "/api/schedules",
        headers=_h(tokens, "t1"),
        json={
            "class_id": str(ids["c1"]),
            "teacher_id": str(other),
            "start_time": "2026-09-01T09:00:00",
            "end_time": "2026-09-01T10:30:00",
        },
    )
    assert r.status_code == 201, r.text
    sched_id = r.json()["schedule"]["id"]
    # 李老师查看/考勤王老师的排课 → 403
    r = c.get(f"/api/schedules/{sched_id}", headers=_h(tokens, "t2"))
    assert r.status_code == 403, r.text
    r = c.delete(f"/api/schedules/{sched_id}", headers=_h(tokens, "t2"))
    assert r.status_code == 403, r.text
    # 本人可查看、可取消
    r = c.get(f"/api/schedules/{sched_id}", headers=_h(tokens, "t1"))
    assert r.status_code == 200, r.text
    r = c.delete(f"/api/schedules/{sched_id}", headers=_h(tokens, "t1"))
    assert r.status_code == 204, r.text


def test_sync_title_to_teachers(client):
    c, ids, tokens = client
    c.post("/api/permissions/job-titles", headers=_h(tokens, "admin"),
           json={"name": "主教", "permissions": {"student_create": False}})
    c.post(f"/api/permissions/teachers/{ids['t1']}/apply-title", headers=_h(tokens, "admin"),
           json={"title": "主教"})
    # 改预设后追溯同步
    titles = c.get("/api/permissions/job-titles", headers=_h(tokens, "admin")).json()["items"]
    tid = next(t["id"] for t in titles if t["name"] == "主教")
    c.put(f"/api/permissions/job-titles/{tid}", headers=_h(tokens, "admin"),
          json={"name": "主教", "permissions": {"student_create": True, "student_delete": True}})
    r = c.post(f"/api/permissions/job-titles/{tid}/sync", headers=_h(tokens, "admin"))
    assert r.status_code == 200, r.text
    assert r.json()["synced"] == 1
    rows = c.get("/api/permissions/teachers", headers=_h(tokens, "admin")).json()["items"]
    row = next(x for x in rows if x["teacher_id"] == str(ids["t1"]))
    assert row["permissions"]["student_delete"] is True


def test_only_empty_class_deletable(client):
    c, ids, tokens = client
    # 先把学员放进王班，再删王班 → 400（非空不可删）
    c.patch(f"/api/students/{ids['stu']}/classes", headers=_h(tokens, "admin"), json={"class_ids": [str(ids["c1"])]})
    r = c.delete(f"/api/classes/{ids['c1']}", headers=_h(tokens, "admin"))
    assert r.status_code == 400, r.text
    # 退班后再删 → 204
    c.patch(f"/api/students/{ids['stu']}/classes", headers=_h(tokens, "admin"), json={"class_ids": []})
    r = c.delete(f"/api/classes/{ids['c1']}", headers=_h(tokens, "admin"))
    assert r.status_code == 204, r.text
