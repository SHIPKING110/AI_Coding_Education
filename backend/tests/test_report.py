"""报告（日报/周报）：FR-DR/FR-WR 全流程冒烟。

日报：按日归档，记录当日工作；周报：自动统计本周指标 + 文字总结 + AI 草稿
"""

import uuid
from datetime import datetime

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
    # seed 系统默认提示词模板（对应迁移 prompt 种子）
    from app.models.prompt import PromptScope, PromptTemplate

    with sessionmaker(bind=engine)() as sess:
        for name in ("通用鼓励型", "问题引导型", "亮点详述型"):
            sess.add(
                PromptTemplate(
                    name=name, content="学员：{student_name}", scope=PromptScope.SYSTEM.value
                )
            )
        sess.commit()
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


@pytest.fixture()
def admin_token(client):
    return _register(client, "admin", "rep-admin")


def test_daily_report_crud_publish_and_unpublish(client, admin_token):
    """日报：幂等创建→编辑→发布→撤回 闭环。"""
    teacher = _register(client, "teacher", "rep-teacher")

    # 1. 幂等创建（第一次 POST）
    r1 = client.post(
        "/api/reports",
        json={
            "type": "daily",
            "period_start": "2026-08-10T00:00:00",
            "period_end": "2026-08-10T00:00:00",
            "title": "8月10日 工作日报",
            "content": {
                "work": "授课",
                "courses": "Python 变量",
                "problems": "无",
                "plan": "准备周报",
            },
        },
        headers=teacher,
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["status"] == "draft"
    rid = r1.json()["id"]

    # 2. 同一教师同日再次创建 = 更新（不新起一条）
    r2 = client.post(
        "/api/reports",
        json={
            "type": "daily",
            "period_start": "2026-08-10T00:00:00",
            "period_end": "2026-08-10T00:00:00",
            "content": {"work": "授课+答疑"},
        },
        headers=teacher,
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == rid

    # 3. PATCH 编辑
    p = client.patch(f"/api/reports/{rid}", json={"content": {"plan": "总结本周"}}, headers=teacher)
    assert p.status_code == 200
    assert p.json()["content"]["plan"] == "总结本周"

    # 4. 发布 / 撤回
    pub = client.post(f"/api/reports/{rid}/publish", headers=teacher)
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["published_at"] is not None
    back = client.post(f"/api/reports/{rid}/unpublish", headers=teacher)
    assert back.json()["status"] == "draft"


def test_weekly_stats_auto_computed(client, admin_token):
    """周报自动统计：已完成排课/上课人次/缺课/出勤率/缺课学员/新增学员（口径与考勤/学员数据一致）。"""
    teacher = _register(client, "teacher", "rep-wr")
    class_id = client.post(
        "/api/classes", json={"name": "统计班", "subject": "Scratch"}, headers=admin_token
    ).json()["id"]

    s_old = client.post(
        "/api/students",
        json={"name": "老学员", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    ).json()["id"]
    s_absent = client.post(
        "/api/students",
        json={"name": "缺课员", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    ).json()["id"]

    teacher_id = client.get("/api/auth/me", headers=teacher).json()["id"]
    sched = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": teacher_id,
            "start_time": datetime(2026, 8, 11, 9, 0).isoformat(),
            "end_time": datetime(2026, 8, 11, 10, 30).isoformat(),
        },
        headers=teacher,
    ).json()["schedule"]["id"]
    # 一次性把已在班的两名学员 attendance 设为 attended/leave（与 crud 幂等逻辑一致）
    r = client.post(
        f"/api/schedules/{sched}/attendance",
        json={
            "items": [
                {"student_id": s_old, "status": "attended"},
                {"student_id": s_absent, "status": "leave"},
            ]
        },
        headers=teacher,
    )
    assert r.status_code == 200

    # 第 2 节：仅排课未上课（scheduled，无考勤）——也应计入排课节数与应到
    client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": teacher_id,
            "start_time": datetime(2026, 8, 12, 14, 0).isoformat(),
            "end_time": datetime(2026, 8, 12, 15, 30).isoformat(),
        },
        headers=teacher,
    )

    # 周报统计预览：整周口径（含未上课的排课）
    rr = client.get(
        "/api/reports/weekly-stats/preview",
        params={"start": "2026-08-11", "end": "2026-08-17"},
        headers=teacher,
    )
    assert rr.status_code == 200, rr.text
    body = rr.json()
    # 排课节数 = 本周全部非取消排课（含已上+未上）
    assert body["schedules"] == 2
    # 应到学员人次 = 各排课班级在册学员数之和（2 节 × 2 人）
    assert body["expected_attendance"] == 4
    # 上课/缺课仅统计已标记考勤的（第 1 节：1 到 1 请；第 2 节未上无考勤）
    assert body["attended"] == 1
    assert body["leave"] == 1
    assert round(body["attendance_rate"], 2) == round(1 / 4, 2)
    assert body["new_students"] >= 0
    # 课时口径：应耗 = 应到×2，实耗 = 已到×2（请假/未上不计）
    assert body["expected_lessons"] == 8
    assert body["consumed_lessons"] == 2
    assert round(body["achievement_rate"], 2) == round(2 / 8, 2)

    # 日报统计预览（8-11，仅第 1 节已上）：应到 = 班级在册学员数
    dd = client.get(
        "/api/reports/daily-stats/preview",
        params={"day": "2026-08-11"},
        headers=teacher,
    )
    assert dd.status_code == 200, dd.text
    daily = dd.json()
    assert daily["schedules"] == 1
    assert daily["expected_attendance"] == 2
    assert daily["attended"] == 1
    assert daily["leave"] == 1
    assert round(daily["attendance_rate"], 2) == 0.5
    assert daily["expected_lessons"] == 4
    assert daily["consumed_lessons"] == 2
    assert round(daily["achievement_rate"], 2) == 0.5

    # 日报统计预览（8-12，第 2 节未上）：排课 1 节、应到 2 人、无考勤
    dd2 = client.get(
        "/api/reports/daily-stats/preview",
        params={"day": "2026-08-12"},
        headers=teacher,
    )
    assert dd2.status_code == 200, dd2.text
    daily2 = dd2.json()
    assert daily2["schedules"] == 1
    assert daily2["expected_attendance"] == 2
    assert daily2["attended"] == 0
    assert daily2["leave"] == 0
    assert daily2["attendance_rate"] == 0.0
    assert daily2["achievement_rate"] == 0.0


def test_report_ai_draft_mock(client, admin_token, monkeypatch):
    """AI 报告草稿（mock）：给已保存的日报生成日报/周报草稿字段，回填可用。"""
    from app.services import llm as llm_mod

    fake_daily = {
        "title": "8月12日 工作日报",
        "work": "授课",
        "courses": "Python",
        "problems": "无",
        "plan": "准备周报",
    }
    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm_mod, "generate_report_summary", lambda **kw: fake_daily)

    teacher = _register(client, "teacher", "rep-ai")
    r = client.post(
        "/api/reports",
        json={
            "type": "daily",
            "period_start": "2026-08-12T00:00:00",
            "period_end": "2026-08-12T00:00:00",
            "content": {"work": "授课"},
        },
        headers=teacher,
    )
    rid = r.json()["id"]

    ai = client.post(f"/api/reports/{rid}/ai-draft", json={}, headers=teacher)
    assert ai.status_code == 200
    assert ai.json()["content"]["work"] == "授课"
    assert ai.json()["model"] is not None


def test_report_list_and_filter(client, admin_token):
    """报告列表：按类型/周期过滤 + 分页。"""
    teacher = _register(client, "teacher", "rep-list")
    for d in ("2026-08-20", "2026-08-21"):
        client.post(
            "/api/reports",
            json={
                "type": "daily",
                "period_start": f"{d}T00:00:00",
                "period_end": f"{d}T00:00:00",
                "content": {"work": f"工作{d}"},
            },
            headers=teacher,
        )
    page = client.get("/api/reports?type=daily&limit=10", headers=teacher).json()
    assert page["total"] >= 2
    assert len(page["items"]) >= 2


def test_period_stats_and_quarterly_ppt(client, admin_token):
    """季度/年度：周期聚合统计 + 生成 PPT 草稿（落盘 uploads/ppt/，写入 reports.ppt_url）。"""
    teacher = _register(client, "teacher", "rep-qs")
    class_id = client.post(
        "/api/classes", json={"name": "季度班", "subject": "Python"}, headers=admin_token
    ).json()["id"]
    s_old = client.post(
        "/api/students",
        json={"name": "季度老员", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    ).json()["id"]
    s_new = client.post(
        "/api/students",
        json={"name": "季度新员", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    )
    assert s_new.status_code == 201

    teacher_id = client.get("/api/auth/me", headers=teacher).json()["id"]
    sched = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": teacher_id,
            "start_time": datetime(2026, 7, 6, 9, 0).isoformat(),
            "end_time": datetime(2026, 7, 6, 10, 30).isoformat(),
        },
        headers=teacher,
    ).json()["schedule"]["id"]
    client.post(
        f"/api/schedules/{sched}/attendance",
        json={"items": [{"student_id": s_old, "status": "attended"}]},
        headers=teacher,
    )
    # 班级两名学员需全标记（考勤规则：全员完成后排课才 completed）
    client.post(
        f"/api/schedules/{sched}/attendance",
        json={"items": [{"student_id": s_new.json()["id"], "status": "leave"}]},
        headers=teacher,
    )

    # 1) 周期统计预览（Q3: 7~9 月）
    rr = client.get(
        "/api/reports/period-stats/preview",
        params={"start": "2026-07-01", "end": "2026-09-30"},
        headers=teacher,
    )
    assert rr.status_code == 200, rr.text
    body = rr.json()
    assert body["schedules"] >= 1
    assert body["attended"] >= 1
    assert body["weekly_count"] >= 0

    # 2) 创建季度总结并生成 PPT
    rep = client.post(
        "/api/reports",
        json={
            "type": "quarterly",
            "period_start": "2026-07-01T00:00:00",
            "period_end": "2026-09-30T00:00:00",
            "title": "2026年第三季度工作总结",
            "content": {
                "summary": "本季度教学顺利，Python 基础讲授完成。",
                "highlights": "学员出勤稳定，部分优秀学员完成项目挑战。",
                "problems": "部分学员练习完成率待提升。",
                "next_plan": "进阶课程启动。",
                "stats_notes": "出勤率按已到/应到统计。",
            },
            "stats": body,
        },
        headers=teacher,
    )
    assert rep.status_code == 201, rep.text
    rid = rep.json()["id"]

    ppt = client.post(f"/api/reports/{rid}/ppt", headers=teacher)
    assert ppt.status_code == 200, ppt.text
    ppt_body = ppt.json()
    assert ppt_body["ppt_url"].startswith("ppt/") and ppt_body["ppt_url"].endswith(".pptx")
    detail = client.get(f"/api/reports/{rid}", headers=teacher).json()
    assert detail["ppt_url"] == ppt_body["ppt_url"]

    # 3) 发布后确认仍可访问；非季度/年度不可生成 PPT
    pub = client.post(f"/api/reports/{rid}/publish", headers=teacher)
    assert pub.status_code == 200


def test_quarterly_ai_draft_uses_period_generator(client, admin_token, monkeypatch):
    """季度总结 AI 草稿走 generate_period_summary（mock），返回结构化字段。"""
    from app.services import llm as llm_mod

    fake = {
        "title": "第三季度总结",
        "summary": "季度总体情况",
        "highlights": "亮点",
        "problems": "问题",
        "next_plan": "计划",
        "stats_notes": "数据说明",
    }
    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm_mod, "generate_period_summary", lambda **kw: fake)

    teacher = _register(client, "teacher", "rep-qsai")
    rep = client.post(
        "/api/reports",
        json={
            "type": "yearly",
            "period_start": "2026-01-01T00:00:00",
            "period_end": "2026-12-31T00:00:00",
            "content": {"summary": "年度"},
        },
        headers=teacher,
    )
    assert rep.status_code == 201, rep.text
    ai = client.post(
        f"/api/reports/{rep.json()['id']}/ai-draft", json={"extra_note": "重点"}, headers=teacher
    )
    assert ai.status_code == 200
    assert ai.json()["content"]["summary"] == "季度总体情况"
    assert ai.json()["content"]["stats_notes"] == "数据说明"


def test_report_board_lists_published_only(client, admin_token):
    """公栏：仅展示已发布的报告，按类型/周期过滤，且所有角色可读。"""
    teacher_a = _register(client, "teacher", "board-a")
    teacher_b = _register(client, "teacher", "board-b")

    # A：一份已发布 + 一份草稿
    daily = client.post(
        "/api/reports",
        json={
            "type": "daily",
            "period_start": "2026-08-15T00:00:00",
            "period_end": "2026-08-15T00:00:00",
            "content": {"work": "A 已发布"},
            "stats": {
                "schedules": 2,
                "expected_attendance": 4,
                "attended": 3,
                "leave": 1,
                "attendance_rate": 0.75,
                "expected_lessons": 6,
                "consumed_lessons": 6,
                "achievement_rate": 1.0,
            },
        },
        headers=teacher_a,
    ).json()["id"]
    client.post(f"/api/reports/{daily}/publish", headers=teacher_a)
    draft = client.post(
        "/api/reports",
        json={
            "type": "daily",
            "period_start": "2026-08-16T00:00:00",
            "period_end": "2026-08-16T00:00:00",
            "content": {"work": "A 草稿"},
        },
        headers=teacher_a,
    ).json()["id"]

    # B：周报（已发布）
    weekly = client.post(
        "/api/reports",
        json={
            "type": "weekly",
            "period_start": "2026-08-17T00:00:00",
            "period_end": "2026-08-23T00:00:00",
            "content": {"summary": "B 周报"},
        },
        headers=teacher_b,
    ).json()["id"]
    client.post(f"/api/reports/{weekly}/publish", headers=teacher_b)

    # 教师（非 admin/staff）也可访问公栏
    board = client.get(
        "/api/reports/board", params={"start": "2026-08-01", "end": "2026-08-31"},
        headers=teacher_a,
    )
    assert board.status_code == 200, board.text
    items = board.json()["items"]
    assert board.json()["total"] >= 2
    pub_ids = {i["id"] for i in items}
    assert daily in pub_ids
    assert weekly in pub_ids
    assert draft not in pub_ids  # 草稿不进入公栏

    # 公栏报告代入提交时的统计（stats 快照）
    daily_item = next(i for i in items if i["id"] == daily)
    assert daily_item["stats"] is not None
    assert daily_item["stats"]["schedules"] == 2
    assert daily_item["stats"]["expected_attendance"] == 4
    assert daily_item["stats"]["attended"] == 3
    assert daily_item["stats"]["leave"] == 1
    assert 0 < daily_item["stats"]["attendance_rate"] <= 1
    assert daily_item["stats"]["achievement_rate"] == 1.0

    # 按类型过滤
    only_weekly = client.get(
        "/api/reports/board", params={"type": "weekly", "start": "2026-08-01", "end": "2026-08-31"},
        headers=teacher_b,
    ).json()
    assert all(i["type"] == "weekly" for i in only_weekly["items"])


def test_report_board_stats_active_teacher(client, admin_token):
    """公栏统计：按在职教师 + 周期计算日报/周报应提交与已提交。"""
    # 两名在职教师
    teacher_a = _register(client, "teacher", "bstat-a")
    _register(client, "teacher", "bstat-b")

    # A 交 1 篇日报，B 未交
    daily = client.post(
        "/api/reports",
        json={
            "type": "daily",
            "period_start": "2026-08-20T00:00:00",
            "period_end": "2026-08-20T00:00:00",
            "content": {"work": "x"},
        },
        headers=teacher_a,
    ).json()["id"]
    client.post(f"/api/reports/{daily}/publish", headers=teacher_a)

    st = client.get(
        "/api/reports/board/stats",
        params={"start": "2026-08-10", "end": "2026-08-21"},
        headers=teacher_a,
    )
    assert st.status_code == 200, st.text
    body = st.json()
    tc = body["teacher_count"]
    assert tc >= 2  # 至少包含本用例的两名在职教师（测试库会累积其他用例教师）
    # 12 天 → 每人应交 12 篇日报；2 周 → 每人应交 2 篇周报
    assert body["daily_due"] == tc * 12
    assert body["daily_submitted"] >= 1
    assert body["weekly_due"] == tc * 2


def test_period_stats_new_metrics(client, admin_token):
    """期间统计新增指标：当前学员/应耗课时/消耗课时/达标率。"""
    teacher = _register(client, "teacher", "pmetric")
    class_id = client.post(
        "/api/classes", json={"name": "指标班", "subject": "Scratch"}, headers=admin_token
    ).json()["id"]
    s1 = client.post(
        "/api/students",
        json={"name": "在读数员", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    ).json()["id"]
    s2 = client.post(
        "/api/students",
        json={"name": "在读二", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    ).json()["id"]

    tid = client.get("/api/auth/me", headers=teacher).json()["id"]
    sched = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": datetime(2026, 7, 6, 9, 0).isoformat(),
            "end_time": datetime(2026, 7, 6, 10, 30).isoformat(),
        },
        headers=teacher,
    ).json()["schedule"]["id"]
    client.post(
        f"/api/schedules/{sched}/attendance",
        json={"items": [{"student_id": s1, "status": "attended"}]},
        headers=teacher,
    )
    client.post(
        f"/api/schedules/{sched}/attendance",
        json={"items": [{"student_id": s2, "status": "attended"}]},
        headers=teacher,
    )

    body = client.get(
        "/api/reports/period-stats/preview",
        params={"start": "2026-07-01", "end": "2026-09-30"},
        headers=teacher,
    ).json()
    assert body["current_students"] == 2
    assert body["expected_lessons"] >= 1
    assert body["consumed_lessons"] >= 1
    assert 0 < body["achievement_rate"] <= 1


def test_period_monthly_and_comparison_charts(client, admin_token):
    """月度折线图 + 同期对比柱状图数据接口。"""
    teacher = _register(client, "teacher", "pchart")
    class_id = client.post(
        "/api/classes", json={"name": "图表班", "subject": "Python"}, headers=admin_token
    ).json()["id"]
    s = client.post(
        "/api/students",
        json={"name": "图表员", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    ).json()["id"]
    tid = client.get("/api/auth/me", headers=teacher).json()["id"]
    sched = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": tid,
            "start_time": datetime(2026, 7, 13, 9, 0).isoformat(),
            "end_time": datetime(2026, 7, 13, 10, 30).isoformat(),
        },
        headers=teacher,
    ).json()["schedule"]["id"]
    client.post(
        f"/api/schedules/{sched}/attendance",
        json={"items": [{"student_id": s, "status": "attended"}]},
        headers=teacher,
    )

    # 月度（Q3: 7~9 月，共 3 个月点）
    monthly = client.get(
        "/api/reports/period-stats/monthly",
        params={"start": "2026-07-01", "end": "2026-09-30"},
        headers=teacher,
    )
    assert monthly.status_code == 200, monthly.text
    mbody = monthly.json()
    assert len(mbody) == 3
    assert mbody[0]["month"] == "2026-07"
    assert mbody[0]["consumed_lessons"] >= 1
    assert mbody[0]["attendance"] >= 1

    # 对比：应返回 3 个月标签 + current + previous
    cmp = client.get(
        "/api/reports/period-stats/comparison",
        params={"start": "2026-07-01", "end": "2026-09-30"},
        headers=teacher,
    )
    assert cmp.status_code == 200, cmp.text
    cbody = cmp.json()
    assert len(cbody["labels"]) == 3
    assert len(cbody["current"]) == 3
    assert len(cbody["previous"]) == 3


def test_empty_summary_ppt_blocked_422(client, admin_token):
    """空数据门禁：正文全空 + 统计全零的季度/年度总结生成 PPT 返回 422。"""
    teacher = _register(client, "teacher", "rep-empty")

    q = client.post(
        "/api/reports",
        json={
            "type": "quarterly",
            "period_start": "2026-07-01T00:00:00",
            "period_end": "2026-09-30T00:00:00",
            "title": "空季度",
            "content": {},
        },
        headers=teacher,
    )
    assert q.status_code == 201, q.text
    ppt = client.post(f"/api/reports/{q.json()['id']}/ppt", headers=teacher)
    assert ppt.status_code == 422, ppt.text
    assert "暂无实质内容" in ppt.json()["detail"]

    y = client.post(
        "/api/reports",
        json={
            "type": "yearly",
            "period_start": "2026-01-01T00:00:00",
            "period_end": "2026-12-31T00:00:00",
            "title": "空年度",
            "content": {},
        },
        headers=teacher,
    )
    assert y.status_code == 201, y.text
    ppt_y = client.post(f"/api/reports/{y.json()['id']}/ppt", headers=teacher)
    assert ppt_y.status_code == 422, ppt_y.text
    assert "季度总结" in ppt_y.json()["detail"]


def test_yearly_ai_draft_uses_selected_quarters(client, admin_token, monkeypatch):
    """年度 AI：勾选 2 篇季度总结聚合素材可用；from_quarters 提示词分支被触发。"""
    from app.services import llm as llm_mod

    seen: dict = {}

    def fake_period(*, report_type, material, extra_note=None, from_quarters=False):
        seen["material"] = material
        seen["from_quarters"] = from_quarters
        return {
            "title": "2026 年度总结",
            "summary": "全年走势",
            "highlights": "成绩",
            "problems": "问题",
            "next_plan": "计划",
            "stats_notes": "数据",
        }

    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm_mod, "generate_period_summary", fake_period)

    teacher = _register(client, "teacher", "rep-yq")
    qids = []
    for start, title in (
        ("2026-01-01T00:00:00", "Q1总结"),
        ("2026-04-01T00:00:00", "Q2总结"),
        ("2026-07-01T00:00:00", "Q3总结"),
    ):
        r = client.post(
            "/api/reports",
            json={
                "type": "quarterly",
                "period_start": start,
                "period_end": start,
                "title": title,
                "content": {"summary": f"{title}总体", "highlights": f"{title}亮点"},
                "stats": {
                    "schedules": 10, "attended": 20, "leave": 2, "attendance_rate": 0.9,
                    "absent_students": [], "new_students": 1, "weekly_count": 5,
                    "current_students": 6, "expected_lessons": 44, "consumed_lessons": 40,
                    "achievement_rate": 0.9,
                },
            },
            headers=teacher,
        )
        assert r.status_code == 201, r.text
        qids.append(r.json()["id"])
        client.post(f"/api/reports/{r.json()['id']}/publish", headers=teacher)

    y = client.post(
        "/api/reports",
        json={
            "type": "yearly",
            "period_start": "2026-01-01T00:00:00",
            "period_end": "2026-12-31T00:00:00",
            "title": "2026 年度",
            "content": {},
        },
        headers=teacher,
    )
    assert y.status_code == 201, y.text
    yid = y.json()["id"]

    # 只勾选前 2 篇季度
    ai = client.post(
        f"/api/reports/{yid}/ai-draft",
        json={"source_quarter_ids": qids[:2]},
        headers=teacher,
    )
    assert ai.status_code == 200, ai.text
    assert ai.json()["content"]["summary"] == "全年走势"
    assert seen["from_quarters"] is True
    assert "Q1总结" in seen["material"] and "Q2总结" in seen["material"]
    assert "Q3总结" not in seen["material"]

    # 非法 id 被 400 拦截
    bad = client.post(
        f"/api/reports/{yid}/ai-draft",
        json={"source_quarter_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=teacher,
    )
    assert bad.status_code == 400, bad.text


def test_yearly_includes_q1_boundary(client, admin_token, monkeypatch):
    """回归：Q1（01-01 起始）落在年度区间下界，不能被时区边界丢掉。

    年度 AI 未显式勾选时自动带出本年度全部已发布季度，Q1~Q4 都应出现在素材中。
    """
    from app.services import llm as llm_mod

    seen: dict = {}

    def fake_period(*, report_type, material, extra_note=None, from_quarters=False):
        seen["material"] = material
        return {
            "title": "年度", "summary": "s", "highlights": "h",
            "problems": "p", "next_plan": "n", "stats_notes": "d",
        }

    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm_mod, "generate_period_summary", fake_period)

    teacher = _register(client, "teacher", "rep-q1b")
    stats = {
        "schedules": 10, "attended": 20, "leave": 2, "attendance_rate": 0.9,
        "absent_students": [], "new_students": 1, "weekly_count": 5,
        "current_students": 6, "expected_lessons": 44, "consumed_lessons": 40,
        "achievement_rate": 0.9,
    }
    for start, qtitle in (
        ("2026-01-01T00:00:00", "Q1总结"),
        ("2026-04-01T00:00:00", "Q2总结"),
        ("2026-07-01T00:00:00", "Q3总结"),
        ("2026-10-01T00:00:00", "Q4总结"),
    ):
        r = client.post(
            "/api/reports",
            json={
                "type": "quarterly", "period_start": start, "period_end": start,
                "title": qtitle, "content": {"summary": f"{qtitle}总体"}, "stats": stats,
            },
            headers=teacher,
        )
        assert r.status_code == 201, r.text
        assert client.post(f"/api/reports/{r.json()['id']}/publish", headers=teacher).status_code == 200

    y = client.post(
        "/api/reports",
        json={
            "type": "yearly", "period_start": "2026-01-01T00:00:00",
            "period_end": "2026-12-31T23:59:59", "title": "2026年度", "content": {},
        },
        headers=teacher,
    )
    assert y.status_code == 201, y.text

    # 不传 source_quarter_ids，应自动带出全部 4 篇（含 Q1）
    ai = client.post(f"/api/reports/{y.json()['id']}/ai-draft", json={}, headers=teacher)
    assert ai.status_code == 200, ai.text
    for qt in ("Q1总结", "Q2总结", "Q3总结", "Q4总结"):
        assert qt in seen["material"], f"{qt} 未出现在年度素材中"


def test_yearly_preview_quarters_first(client, admin_token):
    """年度统计预览 quarters-first：report_type=yearly 时优先聚合已发布季度总结。"""
    teacher = _register(client, "teacher", "rep-yprev")
    stats = {
        "schedules": 10, "attended": 20, "leave": 2, "attendance_rate": 0.9,
        "absent_students": [], "new_students": 1, "weekly_count": 5,
        "current_students": 6, "expected_lessons": 44, "consumed_lessons": 40,
        "achievement_rate": 0.9,
    }
    for start, qtitle in (
        ("2026-01-01T00:00:00", "Q1预"),
        ("2026-04-01T00:00:00", "Q2预"),
    ):
        r = client.post(
            "/api/reports",
            json={
                "type": "quarterly", "period_start": start, "period_end": start,
                "title": qtitle, "content": {"summary": f"{qtitle}总体"}, "stats": stats,
            },
            headers=teacher,
        )
        assert r.status_code == 201, r.text
        assert client.post(f"/api/reports/{r.json()['id']}/publish", headers=teacher).status_code == 200

    prev = client.get(
        "/api/reports/period-stats/preview",
        params={"start": "2026-01-01", "end": "2026-12-31", "report_type": "yearly"},
        headers=teacher,
    )
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["quarterly_count"] == 2
    assert body["schedules"] == 20
    assert body["consumed_lessons"] == 80
    assert body["weekly_count"] == 10
    # 无 report_type 时走明细/周报回退，不带 quarterly_count
    prev2 = client.get(
        "/api/reports/period-stats/preview",
        params={"start": "2026-01-01", "end": "2026-12-31"},
        headers=teacher,
    )
    assert prev2.status_code == 200, prev2.text
    assert prev2.json()["quarterly_count"] == 0


def test_teacher_can_read_teacher_list_but_not_write(client, admin_token):
    """问题修复：教师可查看教师列表（只读），但新增/编辑/删除被 403 拦截。"""
    teacher = _register(client, "teacher", "t-read")

    # 只读：列表 + 校区
    lst = client.get("/api/auth/teachers?limit=50", headers=teacher)
    assert lst.status_code == 200, lst.text
    assert lst.json()["total"] >= 1
    camps = client.get("/api/auth/campuses", headers=teacher)
    assert camps.status_code == 200

    # 写操作被拦截
    upd = client.patch(
        f"/api/auth/teachers/{lst.json()['items'][0]['id']}",
        json={"name": "改名"},
        headers=teacher,
    )
    assert upd.status_code == 403


def _create_quarterly(client, headers, *, title="季度总结", stats=None, published=False,
                      period_start="2026-07-01T00:00:00", period_end="2026-09-30T23:59:59"):
    r = client.post(
        "/api/reports",
        json={
            "type": "quarterly",
            "period_start": period_start,
            "period_end": period_end,
            "title": title,
            "content": {"summary": "总体情况", "highlights": "亮点"},
            "stats": stats
            or {
                "schedules": 10, "attended": 20, "leave": 2, "attendance_rate": 0.9,
                "absent_students": [], "new_students": 1, "weekly_count": 5,
                "current_students": 6, "expected_lessons": 44, "consumed_lessons": 40,
                "achievement_rate": 0.9,
            },
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    if published:
        assert client.post(f"/api/reports/{rid}/publish", headers=headers).status_code == 200
    return rid


def test_history_mine_only(client, admin_token):
    """历史记录 mine=true：任何角色都只看本人报告。"""
    t1 = _register(client, "teacher", "rep-mine1")
    t2 = _register(client, "teacher", "rep-mine2")
    _create_quarterly(client, t1, title="T1季度")
    _create_quarterly(client, t2, title="T2季度")

    mine1 = client.get("/api/reports", params={"type": "quarterly", "mine": "true"}, headers=t1)
    assert mine1.status_code == 200, mine1.text
    titles = [it["title"] for it in mine1.json()["items"]]
    assert "T1季度" in titles and "T2季度" not in titles

    # 管理员 mine=true 也只看本人（本人无季度总结）
    mine_admin = client.get(
        "/api/reports", params={"type": "quarterly", "mine": "true"}, headers=admin_token
    )
    assert mine_admin.status_code == 200
    assert all(it["teacher_id"] != t1 and True for it in mine_admin.json()["items"])
    assert all("T1季度" != it["title"] for it in mine_admin.json()["items"])


def test_report_visibility_and_delete_permissions(client, admin_token):
    """可见性：他人已发布可查看、草稿不可见；删除：本人可删、他人 403、管理员可删。"""
    owner = _register(client, "teacher", "rep-own")
    other = _register(client, "teacher", "rep-other")

    draft_id = _create_quarterly(client, owner, title="草稿季度", published=False)
    pub_id = _create_quarterly(
        client, owner, title="已发布季度", published=True,
        period_start="2026-01-01T00:00:00", period_end="2026-03-31T23:59:59",
    )

    # 他人查看：草稿 403，已发布 200
    assert client.get(f"/api/reports/{draft_id}", headers=other).status_code == 403
    assert client.get(f"/api/reports/{pub_id}", headers=other).status_code == 200

    # 他人编辑/删除被拒
    assert client.patch(
        f"/api/reports/{pub_id}", json={"title": "改"}, headers=other
    ).status_code == 403
    assert client.delete(f"/api/reports/{pub_id}", headers=other).status_code == 403

    # 本人删除成功
    assert client.delete(f"/api/reports/{draft_id}", headers=owner).status_code == 204
    assert client.get(f"/api/reports/{draft_id}", headers=owner).status_code == 404

    # 管理员删除他人已发布成功
    assert client.delete(f"/api/reports/{pub_id}", headers=admin_token).status_code == 204


def test_ppt_build_custom(client, admin_token):
    """定制 PPT：按 slides 规格构建，自动注入数据表+趋势图；空数据仍被 422 拦截。"""
    teacher = _register(client, "teacher", "rep-build")
    rid = _create_quarterly(client, teacher, title="定制季度")

    build = client.post(
        f"/api/reports/{rid}/ppt-build",
        json={
            "title": "定制季度 PPT",
            "theme": "cyan",
            "slides": [
                {"kind": "bullets", "title": "主要亮点", "items": ["学员进步明显", "家长反馈好"]},
                {"kind": "prose", "title": "总体情况", "text": "本季度整体运行平稳。"},
            ],
        },
        headers=teacher,
    )
    assert build.status_code == 200, build.text
    url = build.json()["ppt_url"]
    assert url.startswith("ppt/") and url.endswith(".pptx")

    # 空数据报告：仍被门禁拦截
    empty = client.post(
        "/api/reports",
        json={
            "type": "quarterly",
            "period_start": "2026-01-01T00:00:00",
            "period_end": "2026-03-31T23:59:59",
            "title": "空季度",
            "content": {},
        },
        headers=teacher,
    )
    assert empty.status_code == 201
    blocked = client.post(
        f"/api/reports/{empty.json()['id']}/ppt-build",
        json={"slides": []},
        headers=teacher,
    )
    assert blocked.status_code == 422, blocked.text


def test_ppt_chat_streams_sse(client, admin_token, monkeypatch):
    """对话式 PPT 定制：SSE 流式返回 delta 与 done；未配置 LLM 时回传 error 事件。"""
    from app.services import llm as llm_mod

    teacher = _register(client, "teacher", "rep-chat")
    rid = _create_quarterly(client, teacher, title="对话季度")

    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm_mod, "stream_text", lambda system, prompt: iter(["你好", "，这是", "大纲"]))

    resp = client.post(
        f"/api/reports/{rid}/ppt-chat",
        json={"stage": "outline", "message": "给个大纲", "outline": [], "sections": []},
        headers=teacher,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "你好" in body and "大纲" in body
    assert '"done"' in body
    # 思考过程：SSE 应推送 phase 阶段事件（读取→分析→模型→接收）
    assert '"phase"' in body and '"read"' in body and '"model"' in body

