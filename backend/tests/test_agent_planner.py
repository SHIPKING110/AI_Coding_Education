"""验证规划层：多轮循环、去重、预算护栏、降级（docs/adr/adr-0002）。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.enrollment import Class, Student, StudentClass
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus
from app.models.user import User

TEST_DB_NAME = "child_code_test_planner"


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


def _seed(Session) -> uuid.UUID:
    now = datetime.now(UTC)
    with Session() as s:
        teacher = User(
            id=uuid.uuid4(), role="teacher", username=f"t-{uuid.uuid4().hex[:6]}",
            name="王老师", password_hash="x",
        )
        s.add(teacher)
        s.flush()
        cls = Class(id=uuid.uuid4(), name="Scratch 班", subject="Scratch", teacher_id=teacher.id)
        s.add(cls)
        s.flush()
        stu = Student(id=uuid.uuid4(), name="小明", lesson_balance=3, status="active")
        s.add(stu)
        s.flush()
        s.add(StudentClass(student_id=stu.id, class_id=cls.id))
        sched = Schedule(
            id=uuid.uuid4(), class_id=cls.id, teacher_id=teacher.id,
            start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1),
            status=ScheduleStatus.COMPLETED,
        )
        s.add(sched)
        s.flush()
        s.add(Attendance(schedule_id=sched.id, student_id=stu.id, status=AttendanceStatus.ATTENDED))
        s.commit()
        return teacher.id


@pytest.fixture()
def db_session():
    engine = _engine()
    Session = sessionmaker(bind=engine)
    tid = _seed(Session)
    s = Session()
    try:
        yield s, tid
    finally:
        s.close()
        engine.dispose()


def test_non_business_skips_all(db_session, monkeypatch):
    from app.services import agent_planner, llm

    db, tid = db_session
    user = db.get(User, tid)
    called = {"n": 0}

    def fake_step(messages, tools):
        called["n"] += 1
        return "", []

    monkeypatch.setattr(llm, "tool_step", fake_step)
    out = agent_planner.plan_and_run(db, user, "你好呀，讲个笑话")
    assert out.steps == [] and out.block == "" and called["n"] == 0


def test_multi_round_and_dedup(db_session, monkeypatch):
    from app.services import agent_planner, llm

    db, tid = db_session
    user = db.get(User, tid)
    # 第 1 轮：查排课 + 重复两条相同调用（后一条应被去重）；第 2 轮：查学员；第 3 轮：停
    script = [
        [
            {"id": "1", "name": "my_schedule_overview", "arguments": {"period": "this_week"}},
            {"id": "2", "name": "my_schedule_overview", "arguments": {"period": "this_week"}},
        ],
        [{"id": "3", "name": "student_progress", "arguments": {"student_name": "小明"}}],
        [],
    ]
    it = iter(script)
    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "tool_step", lambda messages, tools: ("", next(it, [])))

    out = agent_planner.plan_and_run(db, user, "这周排课怎么样，顺便看下小明的进度")
    # 去重后 2 个不同调用；共 2 轮
    assert [s.tool for s in out.steps] == ["my_schedule_overview", "student_progress"], out.steps
    assert out.rounds == 2
    assert "业务数据" in out.block and "小明" in out.block
    assert all(s.ok for s in out.steps)


def test_budget_max_rounds(db_session, monkeypatch):
    from app.services import agent_planner, llm

    db, tid = db_session
    user = db.get(User, tid)
    # 模型每轮都反复请求（无去重就不会停），靠预算收束
    counter = {"n": 0}

    def step(messages, tools):
        counter["n"] += 1
        return "", [{"id": str(counter["n"]), "name": "list_my_classes", "arguments": {}}]

    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "tool_step", step)
    out = agent_planner.plan_and_run(db, user, "看看我的班级", max_rounds=2, max_calls=6)
    # 同一调用被去重 → 只执行一次，且轮数不超过预算
    assert [s.tool for s in out.steps] == ["list_my_classes"]
    assert out.rounds <= 2


def test_compact_keeps_whole_records():
    """整条裁剪：宁可少保留几条，也不把一条记录切成两半。"""
    from app.services import agent_planner

    data = {"学员数": 6, "学员": [{"姓名": f"学员{i}", "课时": i} for i in range(1, 7)]}
    out = agent_planner.compact_result(data, 60)
    assert "学员1" in out
    # 不允许出现"地址被截掉一半的键"；要么整条可见要么整体不可见
    assert '"课时": 6' not in out  # 第 6 条整条未列出
    assert "未列出" in out
    # 一定比原长更短
    assert len(out) < len(agent_planner.compact_result(data, 10_000))

    # 小结果原样返回
    small = {"班级数": 1}
    assert agent_planner.compact_result(small, 200) == '{"班级数": 1}'


def test_fallback_when_planner_raises(db_session, monkeypatch):
    from app.services import agent_planner, llm

    db, tid = db_session
    user = db.get(User, tid)

    def boom(messages, tools):
        raise RuntimeError("planner down")

    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "tool_step", boom)
    out = agent_planner.plan_and_run(db, user, "本周考勤和缺课情况")
    assert out.degraded is True
    assert any(s.tool == "my_schedule_overview" for s in out.steps), out.steps


def test_fallback_when_planner_returns_empty(db_session, monkeypatch):
    """回归：规划器成功但漏调（返回空），关键词能命中时必须走启发式兜底，绝不零工具。"""
    from app.services import agent_planner, llm

    db, tid = db_session
    user = db.get(User, tid)
    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "tool_step", lambda messages, tools: ("", []))
    out = agent_planner.plan_and_run(
        db, user, "这周考勤怎么样，顺便看看哪些学员课时不足、再给我教学数据"
    )
    assert out.degraded is True
    names = [s.tool for s in out.steps]
    assert "my_schedule_overview" in names, names
    assert "find_students" in names, names
    assert "my_teaching_stats" in names, names
    assert "业务数据" in out.block
