"""M3 冒烟测试：课后反馈闭环（批量创建/幂等更新/发布/历史查询/上传校验）。

需要本地 PostgreSQL；使用独立测试库 child_code_test。
"""

import io
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app
from app.models.prompt import PromptScope, PromptTemplate

TEST_DB_NAME = "child_code_test"

# 与迁移 seed 一致的 3 套系统默认模板（测试库用 create_all，需手动 seed）
DEFAULT_SYSTEM_TEMPLATES = [
    ("通用鼓励型", "以鼓励为主，先肯定亮点，再温和指出可提升点，鼓励性收尾。学员：{student_name}"),
    ("问题引导型", "客观具体地指出薄弱环节，并给出可执行建议，兼顾鼓励。学员：{student_name}"),
    ("亮点详述型", "抓住具体细节详述亮点，让家长看到孩子成长。学员：{student_name}"),
]


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
    # seed 系统默认提示词模板（对应迁移 c0ffee000002）
    with sessionmaker(bind=engine)() as sess:
        for name, content in DEFAULT_SYSTEM_TEMPLATES:
            sess.add(PromptTemplate(name=name, content=content, scope=PromptScope.SYSTEM.value))
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


def _uid_from_token(client, token_holder):
    r = client.get("/api/auth/me", headers=token_holder)
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture()
def admin_token(client):
    return _register(client, "admin", "fbk-admin")


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


def _make_schedule(client, teacher_token, class_id, teacher_id, start, end):
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": teacher_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=teacher_token,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] is True
    return body["schedule"]["id"]


def _payload(student_id, schedule_id, **extra):
    base = {
        "schedule_id": schedule_id,
        "student_id": student_id,
        "title": "Python 变量",
        "topic": "变量与类型",
        "content": "讲解变量、整数/字符串",
        "performance": "上课认真，主动回答问题",
        "homework": "完成练习 P12",
    }
    base.update(extra)
    return base


def test_feedback_create_update_publish(client, admin_token):
    """反馈创建 -> 编辑 -> 发布（草稿→已发布）闭环；一次排课对一名学员幂等。"""
    teacher = _register(client, "teacher", "t1")
    class_id = _make_class(client, admin_token, "反馈测试班")
    stu_a = _make_student(client, admin_token, "反馈学员A", 40, [class_id])
    stu_b = _make_student(client, admin_token, "反馈学员B", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher)
    schedule_id = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 9, 10, 9, 0),
        datetime(2026, 9, 10, 10, 30),
    )

    # 1. 创建两名学员反馈
    r1 = client.post("/api/feedbacks", json=_payload(stu_a, schedule_id), headers=teacher)
    assert r1.status_code == 201
    assert r1.json()["status"] == "draft"
    fb_a_id = r1.json()["id"]

    r2 = client.post("/api/feedbacks", json=_payload(stu_b, schedule_id), headers=teacher)
    assert r2.status_code == 201

    # 2. 按排课查询
    by_schedule = client.get(f"/api/feedbacks/schedule/{schedule_id}", headers=teacher).json()
    assert len(by_schedule) == 2

    # 3. 幂等：同一排课同一学员重复创建 -> 更新而非新增
    r3 = client.post(
        "/api/feedbacks",
        json=_payload(stu_a, schedule_id, performance="更新：表现更优秀"),
        headers=teacher,
    )
    assert r3.status_code == 201
    assert r3.json()["id"] == fb_a_id
    assert r3.json()["performance"] == "更新：表现更优秀"
    by_schedule = client.get(f"/api/feedbacks/schedule/{schedule_id}", headers=teacher).json()
    assert len(by_schedule) == 2

    # 4. 空内容发布被拦截
    r_empty = client.post(
        "/api/feedbacks",
        json=_payload(stu_b, schedule_id, title="", topic="", content="", performance=""),
        headers=teacher,
    )
    assert r_empty.status_code == 201
    empty_id = r_empty.json()["id"]
    r_block = client.post(f"/api/feedbacks/{empty_id}/publish", headers=teacher)
    assert r_block.status_code == 400

    # 5. 发布后状态流转
    r_pub = client.post(f"/api/feedbacks/{fb_a_id}/publish", headers=teacher)
    assert r_pub.status_code == 200
    assert r_pub.json()["status"] == "published"
    assert r_pub.json()["published_at"] is not None

    # 6. 历史查询（按关键词）
    history = client.get("/api/feedbacks?keyword=变量", headers=teacher).json()
    assert history["total"] >= 2


def test_feedback_role_and_upload(client, admin_token):
    """权限：家长/学员不可写；上传仅接受图片/视频并校验大小。"""
    teacher = _register(client, "teacher", "t2")
    parent = _register(client, "parent", "p1")
    class_id = _make_class(client, admin_token, "上传测试班")
    stu = _make_student(client, admin_token, "上传学员", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher)
    schedule_id = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 9, 11, 9, 0),
        datetime(2026, 9, 11, 10, 30),
    )

    # 家长不可创建反馈
    r_parent = client.post("/api/feedbacks", json=_payload(stu, schedule_id), headers=parent)
    assert r_parent.status_code == 403

    # 非图片/视频上传被拒
    bad = client.post(
        "/api/feedbacks/upload",
        files={"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")},
        headers=teacher,
    )
    assert bad.status_code == 400

    # 图片上传成功，返回可访问 url
    good = client.post(
        "/api/feedbacks/upload",
        files={"file": ("photo.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")},
        headers=teacher,
    )
    assert good.status_code == 201
    url = good.json()["url"]
    assert url.startswith("/uploads/feedback/")

    # 上传后文件可通过静态服务访问
    served = client.get(url)
    assert served.status_code == 200
    assert served.content == b"\x89PNG\r\n\x1a\nfake"


def test_feedback_ai_enhance_degraded_without_llm(client, admin_token, monkeypatch):
    """AI 草稿接口：未配置 LLM 时降级——返回当前内容并记录占位 ai_draft（不报错、不真正走网络）。"""
    from app.services import llm

    from app.services import llm_context as _llm_ctx
    monkeypatch.setattr(_llm_ctx, "optional_resolved", lambda *a, **k: None)

    teacher = _register(client, "teacher", "t3")
    class_id = _make_class(client, admin_token, "AI测试班")
    stu = _make_student(client, admin_token, "AI学员", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher)
    schedule_id = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 9, 12, 9, 0),
        datetime(2026, 9, 12, 10, 30),
    )
    fb = client.post("/api/feedbacks", json=_payload(stu, schedule_id), headers=teacher).json()
    r = client.post(f"/api/feedbacks/{fb['id']}/ai-enhance", json={}, headers=teacher)
    assert r.status_code == 200
    body = r.json()
    assert body["topic"] == fb["topic"]

    # 详情中的 ai_draft 记录为降级占位（note 提示未配置）
    detail = client.get(f"/api/feedbacks/schedule/{schedule_id}", headers=teacher).json()
    saved = next(f for f in detail if f["id"] == fb["id"])
    assert "note" in saved.get("ai_draft", {})


def test_feedback_ai_enhance_generates_draft(client, admin_token, monkeypatch):
    """AI 课堂评价接口：已配置 LLM 时按模板生成评价（mock，不真调网络），回填 evaluation。"""
    from app.services import llm

    fake_eval = "小明同学本节课表现很棒：能独立完成变量定义练习，课堂提问积极…"
    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "generate_feedback_evaluation", lambda **kw: fake_eval)

    teacher = _register(client, "teacher", "t3b")
    class_id = _make_class(client, admin_token, "AI生成班")
    stu = _make_student(client, admin_token, "AI生成学员", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher)
    schedule_id = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 9, 13, 9, 0),
        datetime(2026, 9, 13, 10, 30),
    )
    fb = client.post("/api/feedbacks", json=_payload(stu, schedule_id), headers=teacher).json()

    # 未指定模板 -> 使用系统默认模板（seed 的「通用鼓励型」）
    r = client.post(
        f"/api/feedbacks/{fb['id']}/ai-enhance",
        json={
            "topic": "变量与类型",
            "content": "讲解变量、整数/字符串",
            "performance": "上课认真",
            "homework": "完成练习 P12",
        },
        headers=teacher,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["evaluation"] == fake_eval
    assert body["topic"] == "变量与类型"  # 非评价字段保持原样
    assert body["model"] is not None

    # ai_draft 已落库（含 input/模板信息/生成时间）
    detail = client.get(f"/api/feedbacks/schedule/{schedule_id}", headers=teacher).json()
    saved = next(f for f in detail if f["id"] == fb["id"])
    assert saved.get("ai_draft", {}).get("evaluation") == fake_eval
    assert "template" in saved["ai_draft"]
    assert "generated_at" in saved["ai_draft"]


def test_feedback_ai_enhance_with_custom_template(client, admin_token, monkeypatch):
    """AI 课堂评价：指定个人模板生成（mock），他人不可使用该模板。"""
    from app.services import llm

    fake_eval = "按自定义模板生成的评价内容…"
    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "generate_feedback_evaluation", lambda **kw: fake_eval)

    # 教师A 创建个人模板
    teacher_a = _register(client, "teacher", "ta")
    tpl = client.post(
        "/api/prompt-templates",
        json={"name": "我的模板", "content": "请按{student_name}的情况撰写评价"},
        headers=teacher_a,
    )
    assert tpl.status_code == 201
    tpl_id = tpl.json()["id"]

    teacher_b = _register(client, "teacher", "tb")
    class_id = _make_class(client, admin_token, "模板班")
    stu = _make_student(client, admin_token, "模板学员", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher_b)
    schedule_id = _make_schedule(
        client,
        teacher_b,
        class_id,
        teacher_id,
        datetime(2026, 9, 14, 9, 0),
        datetime(2026, 9, 14, 10, 30),
    )
    fb = client.post("/api/feedbacks", json=_payload(stu, schedule_id), headers=teacher_b).json()

    # 他人用 A 的个人模板 -> 403
    r = client.post(
        f"/api/feedbacks/{fb['id']}/ai-enhance",
        json={"template_id": tpl_id},
        headers=teacher_b,
    )
    assert r.status_code == 403

    # 管理员可用任意 personal 模板（管理视角）
    r_admin = client.post(
        f"/api/feedbacks/{fb['id']}/ai-enhance",
        json={"template_id": tpl_id},
        headers=admin_token,
    )
    assert r_admin.status_code == 200
    assert r_admin.json()["evaluation"] == fake_eval


def test_feedback_editor_stats_completed(client, admin_token):
    """反馈编辑器行 + 统计 + 已完成排课状态（签到需反馈/请假免反馈）。"""
    teacher = _register(client, "teacher", "t4")
    # 过去排课以便标记考勤
    class_id = _make_class(client, admin_token, "编辑器测试班")
    stu_a = _make_student(client, admin_token, "到课学员", 40, [class_id])
    stu_b = _make_student(client, admin_token, "请假学员", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher)
    schedule_id = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 8, 20, 9, 0),
        datetime(2026, 8, 20, 10, 30),
    )

    # 考勤：A 已到、B 请假 -> 全员标记后 schedule 自动 completed
    att = client.post(
        f"/api/schedules/{schedule_id}/attendance",
        json={
            "items": [
                {"student_id": stu_a, "status": "attended"},
                {"student_id": stu_b, "status": "leave"},
            ]
        },
        headers=teacher,
    )
    assert att.status_code == 200, att.text
    assert len(att.json()["errors"]) == 0

    # 1. 编辑器行：A=attended（需反馈）、B=leave（无需反馈）
    editor = client.get(f"/api/feedbacks/schedule/{schedule_id}/editor", headers=teacher).json()
    by_sid = {r["student_id"]: r for r in editor}
    assert by_sid[stu_a]["attendance_status"] == "attended"
    assert by_sid[stu_b]["attendance_status"] == "leave"
    assert by_sid[stu_a]["feedback"] is None

    # 2. 为 A 创建反馈 -> 统计应到2/签到1/请假1/已反馈1/待反馈0（B 请假不计入待反馈）
    #    创建前：待反馈=1（仅签到学员A无反馈，请假学员B不计入）
    before = client.get(
        "/api/feedbacks/stats",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-08-31"},
        headers=teacher,
    ).json()
    assert before["pending"] == 1, "创建反馈前待反馈应=签到学员数(1)，请假不计入"
    fb_resp = client.post("/api/feedbacks", json=_payload(stu_a, schedule_id), headers=teacher)
    assert fb_resp.status_code == 201
    fb_id = fb_resp.json()["id"]
    # 草稿不计入已反馈/已发送（仅已发布算已反馈）
    draft_stats = client.get(
        "/api/feedbacks/stats",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-08-31"},
        headers=teacher,
    ).json()
    assert draft_stats["feedback_done"] == 0
    assert draft_stats["pending"] == 1
    # 发送后才计入
    pub = client.post(f"/api/feedbacks/{fb_id}/publish", headers=teacher)
    assert pub.status_code == 200
    stats = client.get(
        "/api/feedbacks/stats",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-08-31"},
        headers=teacher,
    ).json()
    assert stats["expected"] == 2
    assert stats["attended"] == 1
    assert stats["leave"] == 1
    assert stats["feedback_done"] == 1
    assert stats["pending"] == 0  # 唯一签到学员已发送，请假学员不计入待反馈

    # 3. completed-schedules：只有已完成排课；all_done 需全部签到学员已发送
    comp = client.get(
        "/api/feedbacks/completed-schedules",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-08-31"},
        headers=teacher,
    ).json()
    assert len(comp) == 1
    assert comp[0]["id"] == schedule_id
    assert comp[0]["attended"] == 1
    assert comp[0]["feedback_done"] == 1
    assert comp[0]["all_done"] is True
    assert comp[0]["saved_draft"] == 0

    # 4. 未来排课不进入反馈模块（仅 completed）
    fut_id = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 9, 20, 9, 0),
        datetime(2026, 9, 20, 10, 30),
    )
    comp2 = client.get(
        "/api/feedbacks/completed-schedules",
        params={"class_id": class_id, "start": "2026-09-01", "end": "2026-09-30"},
        headers=teacher,
    ).json()
    assert all(s["id"] != fut_id for s in comp2), "未上完的课不应进入反馈模块"

    # 5. 新增一个已到但无反馈的排课（同班），其 all_done 应为 False
    sch2 = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 8, 22, 9, 0),
        datetime(2026, 8, 22, 10, 30),
    )
    att2 = client.post(
        f"/api/schedules/{sch2}/attendance",
        json={
            "items": [
                {"student_id": stu_a, "status": "attended"},
                {"student_id": stu_b, "status": "leave"},
            ]
        },
        headers=teacher,
    )
    assert att2.status_code == 200
    comp3 = client.get(
        "/api/feedbacks/completed-schedules",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-08-31"},
        headers=teacher,
    ).json()
    s2 = next(s for s in comp3 if s["id"] == sch2)
    assert s2["all_done"] is False
    assert s2["feedback_done"] == 0


def test_feedback_end_boundary(client, admin_token):
    """日期区间 end 为闭区间（含当天）：结束日当天的已完成排课应被统计/列出。

    对应前端生成区间时 end 取“结束日次日 00:00”作为开区间上界，因此当日排课必须命中。
    """
    teacher = _register(client, "teacher", "t-bnd")
    class_id = _make_class(client, admin_token, "边界测试班")
    stu = _make_student(client, admin_token, "边界学员", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher)
    # 完成于 8-28 当天 9:00
    sid = _make_schedule(
        client,
        teacher,
        class_id,
        teacher_id,
        datetime(2026, 8, 28, 9, 0),
        datetime(2026, 8, 28, 10, 30),
    )
    att = client.post(
        f"/api/schedules/{sid}/attendance",
        json={"items": [{"student_id": stu, "status": "attended"}]},
        headers=teacher,
    )
    assert att.status_code == 200

    # end=08-29（次日）应包含 08-28 当天的排课；end=08-28 则不应包含
    comp = client.get(
        "/api/feedbacks/completed-schedules",
        params={"class_id": class_id, "start": "2026-08-25", "end": "2026-08-29"},
        headers=teacher,
    ).json()
    assert [s["id"] for s in comp] == [sid], "end=次日 应包含结束日当天的已完成排课"

    comp_excl = client.get(
        "/api/feedbacks/completed-schedules",
        params={"class_id": class_id, "start": "2026-08-25", "end": "2026-08-28"},
        headers=teacher,
    ).json()
    assert [s["id"] for s in comp_excl] == [], "end=当天 00:00 应排除当天的排课"

    stats = client.get(
        "/api/feedbacks/stats",
        params={"class_id": class_id, "start": "2026-08-25", "end": "2026-08-29"},
        headers=teacher,
    ).json()
    assert stats["schedule_count"] == 1
    assert stats["attended"] == 1
    assert stats["pending"] == 1


def _register_with_campus(client, name, campus):
    r = client.post(
        "/api/auth/register",
        json={
            "role": "teacher",
            "username": f"{name}-{uuid.uuid4().hex[:6]}",
            "password": "123456",
            "name": name,
            "campus": campus,
        },
    )
    assert r.status_code == 201
    return r.json()


def test_class_campus_filter(client, admin_token):
    """班级按带教教师所属校区过滤（筛选联动：选校区后班级只显示该校区教师的班级）。"""
    t1 = _register_with_campus(client, "一校反馈师", "一校")
    t2 = _register_with_campus(client, "二校反馈师", "二校")

    c1a = client.post(
        "/api/classes",
        json={"name": "一校A班", "subject": "Python", "teacher_id": t1["id"]},
        headers=admin_token,
    )
    assert c1a.status_code == 201
    c2 = client.post(
        "/api/classes",
        json={"name": "二校B班", "subject": "Scratch", "teacher_id": t2["id"]},
        headers=admin_token,
    )
    assert c2.status_code == 201

    # 按校区过滤班级
    one = client.get("/api/classes?campus=一校", headers=admin_token).json()
    names = {c["name"] for c in one["items"]}
    assert "一校A班" in names
    assert "二校B班" not in names

    two = client.get("/api/classes?campus=二校", headers=admin_token).json()
    two_names = {c["name"] for c in two["items"]}
    assert "二校B班" in two_names

    # 按教师 + 校区 精确过滤（覆盖：选教师后班级只剩该教师班级）
    teacher = client.get(f"/api/auth/teachers/{t1['id']}", headers=admin_token).json()
    by_teacher = client.get(
        f"/api/classes?teacher_id={teacher['id']}&campus=一校", headers=admin_token
    ).json()
    assert {c["name"] for c in by_teacher["items"]} == {"一校A班"}

    # 计数接口同样生效
    one_count = client.get("/api/classes?campus=一校&limit=1", headers=admin_token).json()
    assert one_count["total"] >= 1


def test_feedback_resend_and_unpublish(client, admin_token):
    """已发送反馈可撤回重新编辑后再次发送；草稿/待发送状态与已发送彻底区分（销量型指标）。"""
    teacher = _register(client, "teacher", "t-resend")
    class_id = _make_class(client, admin_token, "重发测试班")
    stu = _make_student(client, admin_token, "重发学员", 40, [class_id])
    teacher_id = _uid_from_token(client, teacher)
    sid = _make_schedule(
        client, teacher, class_id, teacher_id,
        datetime(2026, 8, 24, 9, 0), datetime(2026, 8, 24, 10, 30),
    )
    client.post(
        f"/api/schedules/{sid}/attendance",
        json={"items": [{"student_id": stu, "status": "attended"}]},
        headers=teacher,
    )
    fb = client.post("/api/feedbacks", json=_payload(stu, sid), headers=teacher).json()
    fb_id = fb["id"]

    # 草稿仅保存在「草稿」，未计入已发送
    stats_draft = client.get(
        "/api/feedbacks/stats",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-09-30"},
        headers=teacher,
    ).json()
    assert stats_draft["feedback_done"] == 0

    # 发送后才计入
    pub = client.post(f"/api/feedbacks/{fb_id}/publish", headers=teacher)
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    stats_pub = client.get(
        "/api/feedbacks/stats",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-09-30"},
        headers=teacher,
    ).json()
    assert stats_pub["feedback_done"] == 1
    comp_pub = client.get(
        "/api/feedbacks/completed-schedules",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-09-30"},
        headers=teacher,
    ).json()
    s_pub = next(s for s in comp_pub if s["id"] == sid)
    assert s_pub["feedback_done"] == 1
    assert s_pub["saved_draft"] == 0
    assert s_pub["all_done"] is True

    # 撤回为草稿后，已发送回到 0，草稿数 1，待反馈回到 1
    back = client.post(f"/api/feedbacks/{fb_id}/unpublish", headers=teacher)
    assert back.status_code == 200
    assert back.json()["status"] == "draft"
    stats_back = client.get(
        "/api/feedbacks/stats",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-09-30"},
        headers=teacher,
    ).json()
    assert stats_back["feedback_done"] == 0
    assert stats_back["pending"] == 1
    comp_back = client.get(
        "/api/feedbacks/completed-schedules",
        params={"class_id": class_id, "start": "2026-08-01", "end": "2026-09-30"},
        headers=teacher,
    ).json()
    s_back = next(s for s in comp_back if s["id"] == sid)
    assert s_back["feedback_done"] == 0
    assert s_back["saved_draft"] == 1
    assert s_back["all_done"] is False

    # 重发成功
    rep = client.post(f"/api/feedbacks/{fb_id}/publish", headers=teacher)
    assert rep.json()["status"] == "published"


def test_prompt_template_crud_isolation_publish(client, admin_token):
    """提示词模板：系统模板可见；个人模板账号隔离；管理员发布后全校可见；权限校验。"""
    teacher_a = _register(client, "teacher", "tpa")
    teacher_b = _register(client, "teacher", "tpb")

    # 1. 系统默认模板（seed 3 套）对任何用户可见
    sys_list = client.get("/api/prompt-templates", headers=teacher_a).json()
    sys_names = {t["name"] for t in sys_list if t["scope"] == "system"}
    assert len(sys_names) == 3

    # 2. A 创建个人模板 -> 仅 A 与 admin 可见
    tpl = client.post(
        "/api/prompt-templates",
        json={"name": "A的模板", "content": "请用鼓励语气评价 {student_name}"},
        headers=teacher_a,
    )
    assert tpl.status_code == 201
    tpl_id = tpl.json()["id"]
    assert tpl.json()["scope"] == "personal"

    a_list = client.get("/api/prompt-templates", headers=teacher_a).json()
    assert any(t["id"] == tpl_id for t in a_list)
    b_list = client.get("/api/prompt-templates", headers=teacher_b).json()
    assert not any(t["id"] == tpl_id for t in b_list)  # 账号隔离

    # 3. B 编辑/删除 A 的模板 -> 403；A 自己可编辑
    r = client.patch(f"/api/prompt-templates/{tpl_id}", json={"name": "改名"}, headers=teacher_b)
    assert r.status_code == 403
    r = client.patch(f"/api/prompt-templates/{tpl_id}", json={"name": "改名"}, headers=teacher_a)
    assert r.status_code == 200
    assert r.json()["name"] == "改名"

    # 4. 管理员发布 -> 全校教师可见
    pub = client.post(f"/api/prompt-templates/{tpl_id}/publish", headers=admin_token)
    assert pub.status_code == 200
    assert pub.json()["scope"] == "published"
    b_list2 = client.get("/api/prompt-templates", headers=teacher_b).json()
    assert any(t["id"] == tpl_id for t in b_list2)  # 发布后 B 可见

    # 5. 教师 B 编辑已发布模板 -> 403；管理员可编辑/撤回
    r = client.patch(f"/api/prompt-templates/{tpl_id}", json={"name": "x"}, headers=teacher_b)
    assert r.status_code == 403
    r = client.patch(f"/api/prompt-templates/{tpl_id}", json={"name": "校版"}, headers=admin_token)
    assert r.status_code == 200
    assert r.json()["name"] == "校版"
    back = client.post(f"/api/prompt-templates/{tpl_id}/unpublish", headers=admin_token)
    assert back.status_code == 200
    assert back.json()["scope"] == "personal"

    # 6. 管理员可删除任意个人模板（管理视角）
    d = client.delete(f"/api/prompt-templates/{tpl_id}", headers=admin_token)
    assert d.status_code == 204
    after = client.get("/api/prompt-templates", headers=teacher_a).json()
    assert not any(t["id"] == tpl_id for t in after)
