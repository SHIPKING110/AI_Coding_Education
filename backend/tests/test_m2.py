"""M2 冒烟测试：排课（跨教师冲突检测）+ 考勤划课时（防重/余额不足）。

需要本地 PostgreSQL；使用独立测试库 child_code_test。
"""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app

TEST_DB_NAME = "child_code_test"


@pytest.fixture(scope="session")
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


def _register(client, role, tag):
    username = f"{tag}-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/auth/register",
        json={"role": role, "username": username, "password": "123456", "name": tag},
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _uid_from_token(client, token_holder):
    """用当前用户接口取 user id（作为 teacher_id 的占位）。"""
    r = client.get("/api/auth/me", headers=token_holder)
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture()
def admin_token(client):
    return _register(client, "admin", "smk-admin")


def _make_class(client, admin_token, name):
    r = client.post("/api/classes", json={"name": name, "subject": "Python"}, headers=admin_token)
    assert r.status_code == 201
    return r.json()["id"]


def _make_student(client, admin_token, name, balance, class_ids):
    r = client.post(
        "/api/students",
        json={"name": name, "lesson_balance": balance, "class_ids": class_ids},
        headers=admin_token,
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_create_schedule_conflict_detection(client, admin_token):
    # 教师用户
    teacher = _register(client, "teacher", "t1")
    teacher2 = _register(client, "teacher", "t2")

    class_a = _make_class(client, admin_token, "冲突测试A班")
    class_b = _make_class(client, admin_token, "冲突测试B班")

    start = datetime(2026, 9, 5, 9, 0)
    end = datetime(2026, 9, 5, 10, 30)

    teacher_id = _uid_from_token(client, teacher)
    teacher2_id = _uid_from_token(client, teacher2)

    # 教师A 给 A 班排 09:00-10:30
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_a,
            "teacher_id": teacher_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=teacher,
    )
    assert r.status_code == 201
    assert r.json()["created"] is True

    # 教师B 同一时段给 B 班排课（不同教师）-> 不冲突
    r2 = client.post(
        "/api/schedules",
        json={
            "class_id": class_b,
            "teacher_id": teacher2_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=teacher2,
    )
    assert r2.status_code == 201
    body = r2.json()
    assert body["created"] is True
    assert len(body.get("conflicts", [])) == 0

    # 教师A 自己同一时段给 B 班排课（同教师重叠）-> 冲突
    r3 = client.post(
        "/api/schedules",
        json={
            "class_id": class_b,
            "teacher_id": teacher_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=teacher,
    )
    assert r3.status_code == 201
    body3 = r3.json()
    assert body3["created"] is False
    assert len(body3["conflicts"]) >= 1

    # force=true 强制创建
    r4 = client.post(
        "/api/schedules",
        json={
            "class_id": class_b,
            "teacher_id": teacher_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "force": True,
        },
        headers=teacher,
    )
    assert r4.status_code == 201
    assert r4.json()["created"] is True


def test_attendance_deduction_and_idempotency(client, admin_token):
    # 创建班级 + 学员（有足够课时）
    class_id = _make_class(client, admin_token, "考勤测试班")
    sid = _make_student(client, admin_token, "考勤学员", balance=10, class_ids=[class_id])

    start = datetime(2026, 8, 20, 14, 0)  # 过去时间（已到上课时间，允许考勤）
    end = datetime(2026, 8, 20, 15, 30)
    tid = _uid_from_token(client, admin_token)
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin_token,
    )
    assert r.status_code == 201
    sched_id = r.json()["schedule"]["id"]

    # 查看考勤列表（应自动生成）并标记"已到"
    att = client.get(f"/api/schedules/{sched_id}/attendance", headers=admin_token)
    assert att.status_code == 200
    assert len(att.json()) == 1
    assert att.json()[0]["lesson_balance"] == 10

    # 提交"已到" -> 扣 2 课时
    sub = client.post(
        f"/api/schedules/{sched_id}/attendance",
        json={"items": [{"student_id": sid, "status": "attended"}]},
        headers=admin_token,
    )
    assert sub.status_code == 200
    result = sub.json()
    assert len(result["lesson_records"]) == 1
    assert result["lesson_records"][0]["delta"] == -2
    assert result["lesson_records"][0]["balance_after"] == 8

    # 学员余额应变为 8
    stu = client.get(f"/api/students/{sid}", headers=admin_token)
    assert stu.json()["lesson_balance"] == 8

    # 二次标记同排课同人 -> 应拒绝（防重）
    sub2 = client.post(
        f"/api/schedules/{sched_id}/attendance",
        json={"items": [{"student_id": sid, "status": "leave"}]},
        headers=admin_token,
    )
    assert sub2.status_code == 200
    result2 = sub2.json()
    assert len(result2["errors"]) == 1
    assert "不能重复" in result2["errors"][0]["reason"]

    # 排课应已完成
    sw = client.get(f"/api/schedules/{sched_id}", headers=admin_token)
    assert sw.json()["status"] == "completed"


def test_attendance_multi_student_independent(client, admin_token):
    """小明+小红：只标记一人，排课不应变为 completed，另一人仍可操作。"""
    class_id = _make_class(client, admin_token, "双学员班")
    sid_a = _make_student(client, admin_token, "小明", balance=10, class_ids=[class_id])
    sid_b = _make_student(client, admin_token, "小红", balance=10, class_ids=[class_id])

    start = datetime(2026, 8, 20, 9, 0)
    end = datetime(2026, 8, 20, 10, 30)
    tid = _uid_from_token(client, admin_token)
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin_token,
    )
    sched_id = r.json()["schedule"]["id"]

    # 只标记 小红=已到
    sub = client.post(
        f"/api/schedules/{sched_id}/attendance",
        json={"items": [{"student_id": sid_b, "status": "attended"}]},
        headers=admin_token,
    )
    assert sub.status_code == 200
    assert len(sub.json()["errors"]) == 0

    # 排课不应是 completed（小明还没标记）
    sw = client.get(f"/api/schedules/{sched_id}", headers=admin_token)
    assert sw.json()["status"] == "scheduled"

    # 小明此时仍可标记 已到
    sub2 = client.post(
        f"/api/schedules/{sched_id}/attendance",
        json={"items": [{"student_id": sid_a, "status": "attended"}]},
        headers=admin_token,
    )
    assert sub2.status_code == 200
    assert len(sub2.json()["errors"]) == 0
    assert len(sub2.json()["lesson_records"]) == 1

    # 全员标记完成 -> 排课 completed
    sw2 = client.get(f"/api/schedules/{sched_id}", headers=admin_token)
    assert sw2.json()["status"] == "completed"


def test_recurring_schedule_creation(client, admin_token):
    """循环排课：每周2节 × 连续周，共排 5 节。"""
    class_id = _make_class(client, admin_token, "循环排课班")
    tid = _uid_from_token(client, admin_token)

    r = client.post(
        "/api/schedules/recurring",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_date": "2026-09-07",  # 周一
            "slots": [
                {"weekday": 1, "start_time": "09:00", "duration_min": 90},  # 周一
                {"weekday": 4, "start_time": "14:00", "duration_min": 90},  # 周四
            ],
            "total_lessons": 5,
        },
        headers=admin_token,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["created"] is True
    assert body["created_count"] == 5

    # 验证日期序列：周一9-07、周四9-10、周一9-14、周四9-17、周一9-21
    days = [s["start_time"][:10] for s in body["schedules"]]
    assert days == ["2026-09-07", "2026-09-10", "2026-09-14", "2026-09-17", "2026-09-21"]

    # 教师时间：09:00 与 14:00 各出现符合预期（前3次周一，后2次周四）
    times = [s["start_time"][11:16] for s in body["schedules"]]
    assert times == ["09:00", "14:00", "09:00", "14:00", "09:00"]

    # 冲突检测：同一教师在相同时段已有排课 -> 拒绝并返回 conflicts
    r2 = client.post(
        "/api/schedules/recurring",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_date": "2026-09-07",
            "slots": [{"weekday": 1, "start_time": "09:00", "duration_min": 90}],
            "total_lessons": 2,
        },
        headers=admin_token,
    )
    assert r2.status_code == 201
    assert r2.json()["created"] is False
    assert len(r2.json()["conflicts"]) >= 1


def test_teacher_listing(client, admin_token):
    """教师列表接口：admin 可见，包含刚注册的教师。"""
    _register(client, "teacher", "列表教师")
    r = client.get("/api/auth/teachers", headers=admin_token)
    assert r.status_code == 200
    assert any("列表教师" in (t["name"] or "") for t in r.json()["items"])


def test_attendance_insufficient_balance(client, admin_token):
    class_id = _make_class(client, admin_token, "余额不足班")
    # 课时 1，不足以扣 2；先把透支上限设为 0，还原“不足即拦”的断言口径
    # （默认 overdraft_max=10，余额 1 扣 2 后 -1 在透支额度内是允许的）
    put = client.put(
        "/api/business/finance-setting",
        json={"overdraft_max": 0},
        headers=admin_token,
    )
    assert put.status_code == 200, put.text
    sid = _make_student(client, admin_token, "余额不足学员", balance=1, class_ids=[class_id])

    start = datetime(2026, 8, 20, 10, 0)
    end = datetime(2026, 8, 20, 11, 30)
    tid = _uid_from_token(client, admin_token)
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin_token,
    )
    sched_id = r.json()["schedule"]["id"]

    sub = client.post(
        f"/api/schedules/{sched_id}/attendance",
        json={"items": [{"student_id": sid, "status": "attended"}]},
        headers=admin_token,
    )
    assert sub.status_code == 200
    result = sub.json()
    assert len(result["errors"]) == 1
    assert "不足" in result["errors"][0]["reason"]
    assert len(result["lesson_records"]) == 0

    # 请假不扣课时 -> 余额仍 1
    leave = client.post(
        f"/api/schedules/{sched_id}/attendance",
        json={"items": [{"student_id": sid, "status": "leave"}]},
        headers=admin_token,
    )
    assert leave.status_code == 200
    assert len(leave.json()["lesson_records"]) == 0
    stu = client.get(f"/api/students/{sid}", headers=admin_token)
    assert stu.json()["lesson_balance"] == 1


def test_attendance_blocked_before_start(client, admin_token):
    """未到上课时间的排课不允许签到/请假（防止误操作）。"""
    class_id = _make_class(client, admin_token, "未开课班")
    sid = _make_student(client, admin_token, "未来学员", balance=10, class_ids=[class_id])

    # 未来的排课（相对当前时间 +2 天，避免硬编码日期过期）
    _future = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=2)
    start = _future
    end = _future + timedelta(hours=1, minutes=30)
    tid = _uid_from_token(client, admin_token)
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin_token,
    )
    sched_id = r.json()["schedule"]["id"]

    # 已到 / 请假 都应被拦截并提示"未到上课时间"
    for st in ("attended", "leave"):
        sub = client.post(
            f"/api/schedules/{sched_id}/attendance",
            json={"items": [{"student_id": sid, "status": st}]},
            headers=admin_token,
        )
        assert sub.status_code == 400
        assert "未到上课时间" in sub.json()["detail"]

    # 余额未被扣减
    stu = client.get(f"/api/students/{sid}", headers=admin_token)
    assert stu.json()["lesson_balance"] == 10


def _register_with_campus(client, role, name, campus):
    username = f"{name}-{uuid.uuid4().hex[:6]}"
    r = client.post(
        "/api/auth/register",
        json={
            "role": role,
            "username": username,
            "password": "123456",
            "name": name,
            "campus": campus,
        },
    )
    assert r.status_code == 201
    return r.json()


def test_teacher_campus_management(client, admin_token):
    """教师校区标签：创建可带校区，列表按校区/关键字筛选，编辑、删除（停用）。"""
    t1 = _register_with_campus(client, "teacher", "一校张老师", "一校")
    t2 = _register_with_campus(client, "teacher", "二校李老师", "二校")
    t3 = _register_with_campus(client, "teacher", "三校王老师", "三校")

    # 校区列表去重
    camps = client.get("/api/auth/campuses", headers=admin_token)
    assert camps.status_code == 200
    assert "一校" in camps.json() and "二校" in camps.json() and "三校" in camps.json()

    # 按校区筛选
    r = client.get("/api/auth/teachers?campus=二校", headers=admin_token)
    names = [t["name"] for t in r.json()["items"]]
    assert names == ["二校李老师"]
    assert "一校张老师" not in names

    # 按关键字筛选
    r2 = client.get("/api/auth/teachers?keyword=张老师", headers=admin_token)
    assert all(t["campus"] == "一校" for t in r2.json()["items"])

    # 编辑：改校区
    upd = client.patch(
        f"/api/auth/teachers/{t1['id']}",
        json={"campus": "总部"},
        headers=admin_token,
    )
    assert upd.status_code == 200
    assert upd.json()["campus"] == "总部"

    # 删除 = 软停用：默认列表不出现，include_inactive=true 可见
    rm = client.delete(f"/api/auth/teachers/{t2['id']}", headers=admin_token)
    assert rm.status_code == 204
    active = client.get("/api/auth/teachers", headers=admin_token).json()
    assert all(t["id"] != t2["id"] for t in active["items"])
    with_inactive = client.get(
        "/api/auth/teachers?include_inactive=true", headers=admin_token
    ).json()
    assert any(t["id"] == t2["id"] and t["status"] == "disabled" for t in with_inactive["items"])

    # 查看详情
    detail = client.get(f"/api/auth/teachers/{t3['id']}", headers=admin_token)
    assert detail.status_code == 200
    assert detail.json()["campus"] == "三校"


def test_class_keyword_search(client, admin_token):
    """班级搜索：按名称/科目/带教教师姓名过滤。"""
    teacher = _register(client, "teacher", "带队教师")
    tid = _uid_from_token(client, teacher)
    client.post(
        "/api/classes",
        json={"name": "Python 算法班XY", "subject": "Python", "teacher_id": tid},
        headers=admin_token,
    )
    client.post(
        "/api/classes",
        json={"name": "Scratch 启蒙班YZ", "subject": "Scratch"},
        headers=admin_token,
    )

    by_name = client.get("/api/classes?keyword=算法班XY", headers=admin_token)
    assert by_name.status_code == 200
    assert len(by_name.json()["items"]) == 1
    assert by_name.json()["items"][0]["name"] == "Python 算法班XY"

    by_subject = client.get("/api/classes?keyword=scratch", headers=admin_token)
    assert len(by_subject.json()["items"]) == 1
    assert by_subject.json()["items"][0]["subject"] == "Scratch"

    # 按带教教师姓名搜索
    me = client.get("/api/auth/me", headers=teacher).json()
    by_teacher = client.get(f"/api/classes?keyword={me['name']}", headers=admin_token)
    assert len(by_teacher.json()["items"]) == 1
    assert by_teacher.json()["items"][0]["name"] == "Python 算法班XY"

    # 无匹配
    none = client.get("/api/classes?keyword=不存在的班级", headers=admin_token)
    assert len(none.json()["items"]) == 0


def test_student_follow_up_flow(client, admin_token):
    """催缴跟进：课时<=10 进名单；标记已续费后保留在名单并直接显示已续费。"""
    class_id = _make_class(client, admin_token, "跟进测试班")
    sid = _make_student(client, admin_token, "跟进学员", balance=6, class_ids=[class_id])

    # 课时<=10 -> 在名单中且为 pending
    col = client.get("/api/students?low_balance_only=true", headers=admin_token).json()
    row = next(s for s in col["items"] if s["id"] == sid)
    assert row["follow_up_status"] == "pending"
    assert row["low_balance"] is True

    # 标记已续费
    upd = client.patch(
        f"/api/students/{sid}/follow-up",
        json={"follow_up_status": "renewed", "note": "已确认续费"},
        headers=admin_token,
    )
    assert upd.status_code == 200
    assert upd.json()["follow_up_status"] == "renewed"
    assert upd.json()["follow_up_at"] is not None

    # 仍保留在名单中，且直接显示已续费
    col2 = client.get("/api/students?low_balance_only=true", headers=admin_token).json()
    row2 = next(s for s in col2["items"] if s["id"] == sid)
    assert row2["follow_up_status"] == "renewed"

    # 按跟进状态筛选
    renewed = client.get(
        "/api/students?low_balance_only=true&follow_up=renewed", headers=admin_token
    ).json()
    assert any(s["id"] == sid for s in renewed["items"])
    pending = client.get(
        "/api/students?low_balance_only=true&follow_up=pending", headers=admin_token
    ).json()
    assert all(s["id"] != sid for s in pending["items"])

    # 非法跟进状态拒绝
    bad = client.patch(
        f"/api/students/{sid}/follow-up",
        json={"follow_up_status": "unknown"},
        headers=admin_token,
    )
    assert bad.status_code == 400


def test_student_stop_and_resume(client, admin_token):
    """学员停课/恢复在读：停课需备注，恢复后回到待跟进名单。"""
    class_id = _make_class(client, admin_token, "停课测试班")
    sid = _make_student(client, admin_token, "停课学员", balance=6, class_ids=[class_id])

    # 停课不填备注 -> 400
    bad = client.patch(
        f"/api/students/{sid}/status",
        json={"status": "stopped"},
        headers=admin_token,
    )
    assert bad.status_code == 400
    assert "备注" in bad.json()["detail"]

    # 停课（填备注）
    r = client.patch(
        f"/api/students/{sid}/status",
        json={"status": "stopped", "stop_note": "家长请假一个月，后续视情况复课"},
        headers=admin_token,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stopped"
    assert body["stop_note"] == "家长请假一个月，后续视情况复课"
    # 停课后跟进状态同步为 stopped（不再催缴），但仍保留在名单中展示
    assert body["follow_up_status"] == "stopped"
    col = client.get("/api/students?low_balance_only=true", headers=admin_token).json()
    assert any(s["id"] == sid and s["follow_up_status"] == "stopped" for s in col["items"])

    # 恢复在读 -> 状态 active + 跟进回到 pending
    r2 = client.patch(
        f"/api/students/{sid}/status",
        json={"status": "active"},
        headers=admin_token,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["status"] == "active"
    assert body2["follow_up_status"] == "pending"

    # 非法状态拒绝
    r3 = client.patch(
        f"/api/students/{sid}/status",
        json={"status": "weird"},
        headers=admin_token,
    )
    assert r3.status_code == 400


def test_student_renew_with_package_and_custom(client, admin_token):
    """催缴续费：可选用课时包或自定义课时+金额，均入账并标记已续费。"""
    class_id = _make_class(client, admin_token, "续费测试班")
    sid = _make_student(client, admin_token, "续费学员", balance=6, class_ids=[class_id])

    # 新建课时包（80 课时，¥8000）
    pkg = client.post(
        "/api/lesson-packages",
        json={"name": "冲刺包 80 课时", "price": 8000, "total_lessons": 80},
        headers=admin_token,
    ).json()

    # 二选一校验：都不传 -> 400
    bad = client.post(f"/api/students/{sid}/renew", json={}, headers=admin_token)
    assert bad.status_code == 400

    # 选课包续费：补 80 课时
    r = client.post(
        f"/api/students/{sid}/renew",
        json={"package_id": pkg["id"]},
        headers=admin_token,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["lesson_balance"] == 86
    assert body["follow_up_status"] == "renewed"

    # 自定义续费：补 30 课时 + 金额 ¥3200
    r2 = client.post(
        f"/api/students/{sid}/renew",
        json={"custom_lessons": 30, "custom_amount": 3200, "note": "老学员优惠续费"},
        headers=admin_token,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["lesson_balance"] == 116
    assert body2["follow_up_status"] == "renewed"
    assert "老学员优惠续费" in (body2["follow_up_note"] or "")

    # 流水可查（recharge 入账记录）
    records = client.get(f"/api/students/{sid}/lesson-records", headers=admin_token).json()
    recharges = [rec for rec in records if rec["record_type"] == "recharge"]
    assert len(recharges) >= 2

    # 已下架课包不可续费
    deact = client.delete(f"/api/lesson-packages/{pkg['id']}", headers=admin_token)
    assert deact.status_code == 204
    bad2 = client.post(
        f"/api/students/{sid}/renew",
        json={"package_id": pkg["id"]},
        headers=admin_token,
    )
    assert bad2.status_code == 400


def test_schedule_campus_filter(client, admin_token):
    """排课按校区过滤：选择校区只看到该校区教师的排课。"""
    t1 = _register_with_campus(client, "teacher", "一校排课教师", "一校")
    t2 = _register_with_campus(client, "teacher", "二校排课教师", "二校")
    login1 = client.post(
        "/api/auth/login", json={"username": t1["username"], "password": "123456"}
    ).json()
    login2 = client.post(
        "/api/auth/login", json={"username": t2["username"], "password": "123456"}
    ).json()
    h1 = {"Authorization": f"Bearer {login1['access_token']}"}
    h2 = {"Authorization": f"Bearer {login2['access_token']}"}
    tid1 = _uid_from_token(client, h1)
    tid2 = _uid_from_token(client, h2)

    class_a = _make_class(client, admin_token, "校区A班")
    class_b = _make_class(client, admin_token, "校区B班")

    start = datetime(2026, 9, 8, 9, 0)
    end = datetime(2026, 9, 8, 10, 30)
    r1 = client.post(
        "/api/schedules",
        json={
            "class_id": class_a,
            "teacher_id": tid1,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin_token,
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/api/schedules",
        json={
            "class_id": class_b,
            "teacher_id": tid2,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=admin_token,
    )
    assert r2.status_code == 201

    one = client.get(
        "/api/schedules?campus=一校",
        headers=admin_token,
    ).json()
    assert all(s["teacher_name"] == "一校排课教师" for s in one)
    assert len(one) == 1

    two = client.get(
        "/api/schedules?campus=二校",
        headers=admin_token,
    ).json()
    assert all(s["teacher_name"] == "二校排课教师" for s in two)


def test_schedule_list_ordered_by_time(client, admin_token):
    """周课表按开始时间升序返回（同一天 9:00 排在 14:30 之前）。"""
    class_id = _make_class(client, admin_token, "排序测试班")
    tid = _uid_from_token(client, admin_token)
    # 同一天两个排课：晚的(14:30)先创建，早的(9:00)后创建
    late_sid = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": "2026-08-30T14:30:00",
            "end_time": "2026-08-30T16:00:00",
        },
        headers=admin_token,
    ).json()["schedule"]["id"]
    early_sid = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": "2026-08-30T09:00:00",
            "end_time": "2026-08-30T10:30:00",
        },
        headers=admin_token,
    ).json()["schedule"]["id"]

    rows = client.get(
        "/api/schedules?start=2026-08-30T00:00:00&end=2026-08-31T00:00:00",
        headers=admin_token,
    ).json()
    times = [r["start_time"] for r in rows]
    assert [r["id"] for r in rows] == [early_sid, late_sid], (
        f"应按开始时间升序排列（9:00 在 14:30 前），实际顺序: {times}"
    )


def test_class_teacher_id_filter(client, admin_token):
    """班级按带教教师精确过滤（teacher_id），与 keyword 可叠加。"""
    teacher_a = _register(client, "teacher", "过滤教师A")
    teacher_b = _register(client, "teacher", "过滤教师B")
    tid_a = _uid_from_token(client, teacher_a)
    tid_b = _uid_from_token(client, teacher_b)

    client.post(
        "/api/classes",
        json={"name": "教师A的班", "subject": "Python", "teacher_id": tid_a},
        headers=admin_token,
    )
    client.post(
        "/api/classes",
        json={"name": "教师B的班", "subject": "Scratch", "teacher_id": tid_b},
        headers=admin_token,
    )
    client.post(
        "/api/classes",
        json={"name": "无教师的班", "subject": "C++"},
        headers=admin_token,
    )

    # 只返回教师A的班级
    by_a = client.get(f"/api/classes?teacher_id={tid_a}", headers=admin_token).json()
    assert by_a["total"] == 1
    assert by_a["items"][0]["name"] == "教师A的班"

    # teacher_id 与 keyword 叠加
    both = client.get(
        f"/api/classes?teacher_id={tid_b}&keyword=Scratch", headers=admin_token
    ).json()
    assert both["total"] == 1
    assert both["items"][0]["name"] == "教师B的班"

    # 未分配教师的班级不受影响
    none = client.get("/api/classes?keyword=无教师", headers=admin_token).json()
    assert none["total"] == 1


def test_list_pagination(client, admin_token):
    """分页：学员/班级/教师/课时包列表返回 items+total。"""
    class_id = _make_class(client, admin_token, "分页测试班")
    for i in range(5):
        _make_student(client, admin_token, f"分页学员{i}", balance=20, class_ids=[class_id])

    # 用 keyword 隔离本用例数据（测试库为所有用例共用）
    page1 = client.get(
        "/api/students?keyword=分页学员&limit=2&offset=0", headers=admin_token
    ).json()
    assert page1["total"] == 5
    assert len(page1["items"]) == 2

    page3 = client.get(
        "/api/students?keyword=分页学员&limit=2&offset=4", headers=admin_token
    ).json()
    assert len(page3["items"]) == 1

    cls = client.get("/api/classes?keyword=分页测试班&limit=2", headers=admin_token).json()
    assert cls["total"] == 1
    assert len(cls["items"]) == 1

    pkg = client.post(
        "/api/lesson-packages",
        json={"name": "分页包", "price": 100, "total_lessons": 10},
        headers=admin_token,
    )
    assert pkg.status_code == 201
    pkgs = client.get("/api/lesson-packages?limit=1", headers=admin_token).json()
    assert pkgs["total"] >= 1
    assert len(pkgs["items"]) == 1

    teachers = client.get("/api/auth/teachers?limit=1", headers=admin_token).json()
    assert teachers["total"] >= 1
    assert len(teachers["items"]) == 1
