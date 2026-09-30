"""验证只读数据库查询工具：可查数据 + 只读/白名单/敏感列/教师作用域护栏（ADR-0003）。"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.enrollment import Class, Student, StudentClass
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus
from app.models.user import User

TEST_DB_NAME = "child_code_test_sql"


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


def _seed(Session):
    now = datetime.now(UTC)
    with Session() as s:
        teacher = User(id=uuid.uuid4(), role="teacher", username=f"t-{uuid.uuid4().hex[:6]}",
                       name="王老师", password_hash="x")
        s.add(teacher)
        s.flush()
        cls = Class(id=uuid.uuid4(), name="Scratch 班", subject="Scratch", teacher_id=teacher.id)
        s.add(cls)
        s.flush()
        stu = Student(id=uuid.uuid4(), name="小明", lesson_balance=3, status="active")
        s.add(stu)
        s.flush()
        s.add(StudentClass(student_id=stu.id, class_id=cls.id))
        sched = Schedule(id=uuid.uuid4(), class_id=cls.id, teacher_id=teacher.id,
                         start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1),
                         status=ScheduleStatus.COMPLETED)
        s.add(sched)
        s.flush()
        s.add(Attendance(schedule_id=sched.id, student_id=stu.id, status=AttendanceStatus.ATTENDED))
        s.commit()
        return teacher.id


def test_validate_sql_guards():
    from app.models.user import Role, User
    from app.services import agent_sql

    teacher = User(id=uuid.uuid4(), role=Role.TEACHER.value, username="x", name="t", password_hash="x")
    # 非 SELECT
    assert not agent_sql.validate_sql("delete from students", teacher)[0]
    assert not agent_sql.validate_sql("update students set name='x'", teacher)[0]
    # 多语句
    assert not agent_sql.validate_sql("select 1; drop table students", teacher)[0]
    # 敏感列
    assert not agent_sql.validate_sql("select password_hash from users", teacher)[0]
    # 非白名单表
    assert not agent_sql.validate_sql("select * from pg_shadow", teacher)[0]
    # 敏感列（手机号）
    assert not agent_sql.validate_sql("select phone from students", teacher)[0]
    # 合法查询（引用表，不含教师归属）
    assert agent_sql.validate_sql("select name from lesson_packages", teacher)[0]
    # 教师查含教师归属的表必须带自己 id（students 也算）
    ok, reason = agent_sql.validate_sql("select * from schedules", teacher)
    assert not ok and "teacher_id" in reason
    assert not agent_sql.validate_sql("select * from students", teacher)[0]
    ok2, _ = agent_sql.validate_sql(f"select * from schedules where teacher_id = '{teacher.id}'", teacher)
    assert ok2


def test_run_query_and_scope(monkeypatch):
    from app.core.config import get_settings
    from app.services import agent_sql

    engine = _engine()
    Session = sessionmaker(bind=engine)
    tid = _seed(Session)
    # 只读引擎指向测试库
    monkeypatch.setattr(agent_sql, "_readonly_engine", lambda: agent_sql._build_readonly_engine(
        get_settings().DATABASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"
    ))
    try:
        with Session() as s:
            teacher = s.get(User, tid)
            # 合法查询（引用表）：返回一行计数
            res = agent_sql.run_query(s, teacher, "select count(*) as n from lesson_packages")
            assert res.get("row_count") == 1, res
            # 教师作用域：查含教师归属的表但无过滤被拒
            denied = agent_sql.run_query(s, teacher, "select * from schedules")
            assert "错误" in denied and "teacher_id" in denied["错误"], denied
            denied2 = agent_sql.run_query(s, teacher, "select * from students")
            assert "错误" in denied2, denied2
            # 带上自己的 teacher_id 可查
            ok = agent_sql.run_query(
                s, teacher, f"select status from schedules where teacher_id = '{teacher.id}'"
            )
            assert ok.get("row_count") == 1 and ok["rows"][0][0] == "COMPLETED", ok
            # 写操作被拒
            bad = agent_sql.run_query(s, teacher, "select 1; drop table students")
            assert "错误" in bad
    finally:
        engine.dispose()
