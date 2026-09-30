"""验证智能助手业务工具层：scope 正确 + 数据口径正确（docs/adr/adr-0001）。"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.enrollment import Class, Student, StudentClass
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus
from app.models.user import User

TEST_DB_NAME = "child_code_test_tools"


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
    """造数据：一个教师、一个班、两名学员、一节已完成排课（1 到 1 请假）。"""
    now = datetime.now(UTC)
    with Session() as s:
        teacher = User(
            id=uuid.uuid4(), role="teacher", username=f"t-{uuid.uuid4().hex[:6]}",
            name="王老师", password_hash="x",
        )
        other = User(
            id=uuid.uuid4(), role="teacher", username=f"t-{uuid.uuid4().hex[:6]}",
            name="李老师", password_hash="x",
        )
        s.add_all([teacher, other])
        s.flush()
        cls = Class(id=uuid.uuid4(), name="Scratch 启蒙班", subject="Scratch", teacher_id=teacher.id)
        s.add(cls)
        s.flush()
        stu1 = Student(id=uuid.uuid4(), name="小明", lesson_balance=3, status="active")
        stu2 = Student(id=uuid.uuid4(), name="小红", lesson_balance=50, status="active")
        s.add_all([stu1, stu2])
        s.flush()
        s.add_all([
            StudentClass(student_id=stu1.id, class_id=cls.id),
            StudentClass(student_id=stu2.id, class_id=cls.id),
        ])
        sched = Schedule(
            id=uuid.uuid4(), class_id=cls.id, teacher_id=teacher.id,
            start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1),
            status=ScheduleStatus.COMPLETED,
        )
        s.add(sched)
        s.flush()
        s.add_all([
            Attendance(schedule_id=sched.id, student_id=stu1.id, status=AttendanceStatus.ATTENDED),
            Attendance(schedule_id=sched.id, student_id=stu2.id, status=AttendanceStatus.LEAVE),
        ])
        # 评估：小明已发布(published)，小红仍为草稿(draft)，覆盖三种完成状态
        from app.models.evaluation import Evaluation, EvaluationStatus

        s.add_all([
            Evaluation(
                id=uuid.uuid4(), student_id=stu1.id, teacher_id=teacher.id,
                title="小明评估", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
                status=EvaluationStatus.PUBLISHED.value,
            ),
            Evaluation(
                id=uuid.uuid4(), student_id=stu2.id, teacher_id=teacher.id,
                title="小红评估", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
                status=EvaluationStatus.DRAFT.value,
            ),
        ])
        s.commit()
        return {"teacher_id": teacher.id, "other_id": other.id}


def test_tools_scope_and_data():
    from app.services import agent_tools

    engine = _engine()
    Session = sessionmaker(bind=engine)
    ids = _seed(Session)
    try:
        with Session() as s:
            teacher = s.get(User, ids["teacher_id"])
            other = s.get(User, ids["other_id"])

            # 排课考勤：本周 1 节课，1 到 1 请假，出勤率 50%
            ov = agent_tools.execute_tool(s, teacher, "my_schedule_overview", {"period": "this_week"})
            assert ov["排课节数"] == 1, ov
            assert ov["上课人次"] == 1 and ov["缺课人次"] == 1, ov
            assert ov["出勤率"] == "50.0%", ov
            assert "小红" in ov["缺课学员"], ov

            # 另一名教师看不到别人的排课
            ov2 = agent_tools.execute_tool(s, other, "my_schedule_overview", {"period": "this_week"})
            assert ov2["排课节数"] == 0, ov2

            # 班级列表：教师只见自己的班
            cls = agent_tools.execute_tool(s, teacher, "list_my_classes", {})
            assert cls["班级数"] == 1 and cls["班级"][0]["学员数"] == 2, cls
            assert agent_tools.execute_tool(s, other, "list_my_classes", {})["班级数"] == 0

            # 找学员 + 低课时催缴：教师只见本人班级的学员
            low = agent_tools.execute_tool(s, teacher, "find_students", {"low_balance_only": True})
            assert low["总数"] == 1 and low["学员"][0]["姓名"] == "小明", low
            # 教师查学员只含本人班级：小红(50课时) 也属于该班，非低课时
            all_s = agent_tools.execute_tool(s, teacher, "find_students", {})
            assert all_s["总数"] == 2, all_s
            # 按班级名过滤：返回该班全部学员
            by_class = agent_tools.execute_tool(s, teacher, "find_students", {"class_name": "Scratch"})
            assert by_class["总数"] == 2, by_class
            # 另一名教师的学员不可见
            other_all = agent_tools.execute_tool(s, other, "find_students", {})
            assert other_all["总数"] == 0, other_all
            # 教师无法查到非本人学员的进度
            prog_other = agent_tools.execute_tool(
                s, other, "student_progress", {"student_name": "小明", "period": "this_week"}
            )
            assert "错误" in prog_other, prog_other

            # 班级评估完成情况：小明已发布(published)已完成，小红草稿(draft)未完成
            ev = agent_tools.execute_tool(
                s, teacher, "class_evaluation_overview", {"class_name": "Scratch"}
            )
            assert ev["学员数"] == 2, ev
            states = {d["学员"]: d["状态"] for d in ev["明细"]}
            assert states.get("小明") == "已完成", ev
            assert states.get("小红") == "草稿·未完成", ev
            assert ev["已完成"] == 1 and ev["未完成"] == 1, ev
            # 另一名教师找不到该班
            ev_other = agent_tools.execute_tool(
                s, other, "class_evaluation_overview", {"class_name": "Scratch"}
            )
            assert "错误" in ev_other, ev_other

            # 教学数据：达标率 = 已到 1×2 / 应到 2×2 = 50%
            stats = agent_tools.execute_tool(s, teacher, "my_teaching_stats", {"period": "this_week"})
            assert stats["应消耗课时"] == 4 and stats["实际消耗课时"] == 2, stats
            assert stats["达标率"] == "50.0%", stats
    finally:
        engine.dispose()


def test_period_parsing_and_routing():
    from app.services import agent_tools

    start, end = agent_tools.parse_period("last_week")
    assert (end - start).days == 7
    assert agent_tools.looks_like_business("这周考勤怎么样")
    assert not agent_tools.looks_like_business("你好呀")
    calls = agent_tools._heuristic_calls("帮我看看本周排课和缺课情况")
    assert any(c["name"] == "my_schedule_overview" for c in calls)
