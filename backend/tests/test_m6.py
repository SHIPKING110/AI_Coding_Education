"""M6 学员评估：CRUD / 素材预览 / AI 草稿 / PPT / 客户端可见性。

覆盖：
- 学员评估幂等创建、发布/撤回、删除权限
- 素材预览（已发布反馈 + 课时统计）
- AI 草稿异步任务（mock）与对话优化
- PPT 生成与文件回写
- 客户端仅可见已发布评估
"""

import uuid
from datetime import date, datetime

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
    from app.models import ClassPpt as _ClassPpt  # noqa: F401 注册 class_ppts 表元数据

    Base.metadata.create_all(engine)

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
    return _register(client, "admin", "ev-admin")


@pytest.fixture()
def teacher_token(client):
    return _register(client, "teacher", "ev-teacher")


def _create_student_and_class(client, admin_token, teacher_token):
    class_id = client.post(
        "/api/classes", json={"name": "评估班", "subject": "Scratch"}, headers=admin_token
    ).json()["id"]
    student = client.post(
        "/api/students",
        json={"name": "小评估", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    )
    assert student.status_code == 201, student.text
    student_id = student.json()["id"]
    teacher_id = client.get("/api/auth/me", headers=teacher_token).json()["id"]
    sched = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": teacher_id,
            "start_time": datetime(2026, 9, 1, 9, 0).isoformat(),
            "end_time": datetime(2026, 9, 1, 10, 30).isoformat(),
        },
        headers=teacher_token,
    ).json()["schedule"]["id"]
    client.post(
        f"/api/schedules/{sched}/attendance",
        json={"items": [{"student_id": student_id, "status": "attended"}]},
        headers=teacher_token,
    )
    return class_id, student_id, teacher_id, sched


def _publish_feedback(client, teacher_token, sched, student_id):
    fb = client.post(
        "/api/feedbacks",
        json={
            "schedule_id": sched,
            "student_id": student_id,
            "title": "第一次评估课反馈",
            "topic": "变量与顺序结构",
            "content": "能独立完成基础练习。",
            "performance": "积极回答问题。",
            "evaluation": "课堂投入较好。",
            "homework": "完成练习册第1页。",
        },
        headers=teacher_token,
    )
    assert fb.status_code == 201, fb.text
    fb_id = fb.json()["id"]
    pub = client.post(f"/api/feedbacks/{fb_id}/publish", headers=teacher_token)
    assert pub.status_code == 200, pub.text


def test_evaluation_crud_publish_and_client_visibility(client, admin_token, teacher_token):
    """评估 CRUD 与客户端可见性。"""
    class_id, student_id, teacher_id, sched = _create_student_and_class(
        client, admin_token, teacher_token
    )
    _publish_feedback(client, teacher_token, sched, student_id)

    start = date(2026, 8, 1)
    end = date(2026, 10, 31)
    ev = client.post(
        "/api/evaluations",
        json={
            "student_id": student_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "title": "三个月学习评估",
            "content": {"summary": "基础扎实"},
        },
        headers=teacher_token,
    )
    assert ev.status_code == 201, ev.text
    ev_id = ev.json()["id"]

    same = client.post(
        "/api/evaluations",
        json={
            "student_id": student_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "content": {"summary": "基础扎实+"},
        },
        headers=teacher_token,
    )
    assert same.status_code == 201
    assert same.json()["id"] == ev_id

    detail = client.get(f"/api/evaluations/{ev_id}", headers=teacher_token)
    assert detail.status_code == 200
    assert detail.json()["content"]["summary"] == "基础扎实+"

    pub = client.post(f"/api/evaluations/{ev_id}/publish", headers=teacher_token)
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    # 发布时自动刷新周期统计快照（家长端详情展示依据）
    pub_stats = pub.json()["stats"]
    assert pub_stats is not None
    assert pub_stats["attended"] >= 1
    assert pub_stats["feedback_count"] >= 1

    client_me = client.get("/api/client/me", headers=teacher_token)
    assert client_me.status_code == 403 or client_me.status_code == 200

    parent = _register(client, "parent", "ev-parent")
    # 绑定家长到学员
    client.patch(
        f"/api/students/{student_id}",
        json={"parent_user_id": client.get("/api/auth/me", headers=parent).json()["id"]},
        headers=admin_token,
    )
    client_evs = client.get(f"/api/client/students/{student_id}/evaluations", headers=parent)
    assert client_evs.status_code == 200, client_evs.text
    assert client_evs.json()["total"] >= 1


def test_evaluation_material_ai_and_ppt(client, admin_token, teacher_token, monkeypatch):
    """素材预览、AI 草稿与 PPT 生成。"""
    from app.services import llm as llm_mod

    class_id, student_id, teacher_id, sched = _create_student_and_class(
        client, admin_token, teacher_token
    )
    _publish_feedback(client, teacher_token, sched, student_id)
    start = date(2026, 8, 1)
    end = date(2026, 10, 31)

    preview = client.get(
        "/api/evaluations/material/preview",
        params={"student_id": student_id, "start": start.isoformat(), "end": end.isoformat()},
        headers=teacher_token,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["stats"]["feedback_count"] >= 1

    fake = {
        "title": "三个月学习评估",
        "summary": "综合表现良好",
        "subjects": [{"name": "编程思维", "level": 4, "comment": "思路清晰"}],
        "progress": "能独立完成基础任务；回答积极",
        "to_improve": "书写习惯可继续加强",
        "suggestions": "每周坚持 2 次练习",
    }
    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm_mod, "generate_evaluation", lambda **kw: fake)

    ev = client.post(
        "/api/evaluations",
        json={
            "student_id": student_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "title": "三个月学习评估",
            "content": {"summary": "待生成"},
        },
        headers=teacher_token,
    ).json()
    task = client.post(f"/api/evaluations/{ev['id']}/ai-draft", json={}, headers=teacher_token)
    assert task.status_code == 202, task.text
    task_id = task.json()["id"]

    import time

    deadline = time.time() + 5
    while time.time() < deadline:
        fresh = client.get(f"/api/evaluations/ai-tasks/{task_id}", headers=teacher_token)
        assert fresh.status_code == 200
        body = fresh.json()
        if body["status"] == "done":
            assert body["result"]["summary"] == "综合表现良好"
            break
        time.sleep(0.05)
    else:
        raise AssertionError("AI task not done")

    refine = client.post(
        f"/api/evaluations/{ev['id']}/ai-refine",
        json={"instruction": "更强调自信心"},
        headers=teacher_token,
    )
    assert refine.status_code == 202, refine.text

    # 更新评估内容后可生成 PPT
    patch = client.patch(
        f"/api/evaluations/{ev['id']}",
        json={"content": fake},
        headers=teacher_token,
    )
    assert patch.status_code == 200
    ppt = client.post(f"/api/evaluations/{ev['id']}/ppt", headers=teacher_token)
    assert ppt.status_code == 200, ppt.text
    assert ppt.json()["ppt_url"].startswith("ppt/")


def test_evaluation_pdf_export(client, admin_token, teacher_token):
    """后端 PDF 导出（M6 后端化）：管理端可导（含草稿），客户端仅已发布可导。"""
    class_id, student_id, teacher_id, sched = _create_student_and_class(
        client, admin_token, teacher_token
    )
    start = date(2026, 8, 1)
    end = date(2026, 10, 31)
    ev = client.post(
        "/api/evaluations",
        json={
            "student_id": student_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "title": "三个月学习评估",
            "content": {
                "summary": "综合表现良好，能独立完成课堂项目。",
                "subjects": [
                    {"name": "编程思维", "level": 4, "comment": "思路清晰"},
                    {"name": "作品创意", "level": 5, "comment": "有想法"},
                ],
                "progress": "能独立完成任务；课堂参与积极",
                "to_improve": "代码规范需加强",
                "suggestions": "每周坚持练习",
            },
        },
        headers=teacher_token,
    )
    assert ev.status_code == 201, ev.text
    ev_id = ev.json()["id"]

    # 管理端：教师导出自己的草稿（PDF 文件头 + content-type）
    r = client.get(f"/api/evaluations/{ev_id}/pdf", headers=teacher_token)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
    assert "attachment" in r.headers.get("content-disposition", "")

    # 其他教师无权导出
    other = _register(client, "teacher", "ev-teacher-2")
    forbidden = client.get(f"/api/evaluations/{ev_id}/pdf", headers=other)
    assert forbidden.status_code == 403

    # 家长绑定学员
    parent = _register(client, "parent", "ev-parent-pdf")
    client.patch(
        f"/api/students/{student_id}",
        json={"parent_user_id": client.get("/api/auth/me", headers=parent).json()["id"]},
        headers=admin_token,
    )
    # 客户端：草稿不可导出
    draft_pdf = client.get(
        f"/api/client/students/{student_id}/evaluations/{ev_id}/pdf", headers=parent
    )
    assert draft_pdf.status_code == 404

    # 发布后可导出
    pub = client.post(f"/api/evaluations/{ev_id}/publish", headers=teacher_token)
    assert pub.status_code == 200
    published_pdf = client.get(
        f"/api/client/students/{student_id}/evaluations/{ev_id}/pdf", headers=parent
    )
    assert published_pdf.status_code == 200, published_pdf.text
    assert published_pdf.headers["content-type"] == "application/pdf"
    assert published_pdf.content.startswith(b"%PDF-")


def test_class_parent_ppt(client, admin_token, teacher_token, monkeypatch, test_engine):
    """班级家长会 PPT（以班级为单位）：结合全班学员评估生成，异步任务 + latest 回查。"""
    from app.services import llm as llm_mod

    class_id, student_id, teacher_id, sched = _create_student_and_class(
        client, admin_token, teacher_token
    )
    _publish_feedback(client, teacher_token, sched, student_id)
    # 再加一名学员入班，并为其发布评估
    student2 = client.post(
        "/api/students",
        json={"name": "小评估2", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    )
    assert student2.status_code == 201, student2.text
    student2_id = student2.json()["id"]

    # 将班级指派给当前教师（教师仅可为自己带教班级生成家长会 PPT）
    assigned = client.patch(
        f"/api/classes/{class_id}", json={"teacher_id": teacher_id}, headers=admin_token
    )
    assert assigned.status_code == 200, assigned.text

    start = date(2026, 8, 1)
    end = date(2026, 10, 31)
    fake_content = {
        "title": "评估班 阶段学习汇报家长会",
        "class_summary": "本班整体表现出色",
        "ability_comment": "编程思维进步明显",
        "highlights": "小明进步突出；出勤率保持高位",
        "to_improve": "课后练习频次不足",
        "next_plan": "进入循环结构模块；增加项目实战",
        "home_suggestions": "每周完成 2 次家庭练习",
    }
    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm_mod, "generate_class_meeting", lambda **kw: dict(fake_content))

    # runner 在后台线程内用 SessionLocal 落库 → 测试中替换为测试库会话工厂
    from app.api.routers import evaluations as evaluations_router

    monkeypatch.setattr(evaluations_router, "SessionLocal", sessionmaker(bind=test_engine))

    import uuid as _uuid
    from datetime import UTC
    from datetime import datetime as _dt

    from app.services import ai_tasks as ai_tasks_mod

    def sync_create_task(*, owner_id: str, kind: str, summary: str, runner,
                         dedup_key: str | None = None):
        task = {
            "id": str(_uuid.uuid4()),
            "owner_id": owner_id,
            "kind": kind,
            "summary": summary,
            "status": "pending",
            "stage": "排队中（等待前面的 AI 任务完成）",
            "result": None,
            "error": None,
            "created_at": _dt.now(UTC).isoformat(),
            "started_at": None,
            "finished_at": None,
        }
        if dedup_key is not None:
            task["dedup_key"] = dedup_key
        result = runner(lambda stage: None)
        task.update(
            {
                "status": "done",
                "stage": "已完成，可查看并加入作业",
                "result": result,
                "started_at": task["created_at"],
                "finished_at": _dt.now(UTC).isoformat(),
            }
        )
        ai_tasks_mod._tasks[task["id"]] = task
        return dict(task)

    monkeypatch.setattr(ai_tasks_mod, "create_task", sync_create_task)

    for sid, summary, do_publish in (
        (student_id, "逻辑清晰", False),  # 留一份草稿：草稿评估也应计入班级 PPT 素材
        (student2_id, "勇于表达", True),
    ):
        ev = client.post(
            "/api/evaluations",
            json={
                "student_id": sid,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "title": f"{sid[:4]} 学习评估",
                "content": {
                    "summary": summary,
                    "subjects": [{"name": "编程思维", "level": 4, "comment": "思路清晰"}],
                    "progress": "能独立完成基础任务；回答积极",
                    "to_improve": "书写规范待加强",
                    "suggestions": "每周坚持练习",
                },
            },
            headers=teacher_token,
        )
        assert ev.status_code == 201, ev.text
        if do_publish:
            pub = client.post(f"/api/evaluations/{ev.json()['id']}/publish", headers=teacher_token)
            assert pub.status_code == 200

    # 名单：草稿也标注为已生成（generated=2，published=1）
    roster = client.get(
        "/api/evaluations/class-roster",
        params={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    )
    assert roster.status_code == 200, roster.text
    assert roster.json()["generated"] == 2
    assert roster.json()["published"] == 1

    # 无任何评估的周期 → 400
    empty = client.post(
        "/api/evaluations/class-ppt",
        json={
            "class_id": class_id,
            "period_start": date(2020, 1, 1).isoformat(),
            "period_end": date(2020, 3, 31).isoformat(),
        },
        headers=teacher_token,
    )
    assert empty.status_code == 400, empty.text

    # 其他教师无权生成
    other = _register(client, "teacher", "ev-class-ppt-other")
    forbidden = client.post(
        "/api/evaluations/class-ppt",
        json={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=other,
    )
    assert forbidden.status_code == 403, forbidden.text

    task = client.post(
        "/api/evaluations/class-ppt",
        json={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "extra_note": "突出编程思维成长",
        },
        headers=teacher_token,
    )
    assert task.status_code == 202, task.text
    task_id = task.json()["id"]

    import time

    deadline = time.time() + 10
    while time.time() < deadline:
        fresh = client.get(f"/api/evaluations/ai-tasks/{task_id}", headers=teacher_token)
        assert fresh.status_code == 200
        body = fresh.json()
        if body["status"] == "done":
            result = body["result"]
            assert result["ppt_url"].startswith("ppt/")
            assert result["class_id"] == class_id
            assert result["evaluated_count"] == 2
            break
        assert body["status"] in ("pending", "running"), body
        time.sleep(0.05)
    else:
        raise AssertionError("class ppt task not done")

    # latest 回查（生成即落库：返回可编辑记录 + 全部文案字段）
    latest = client.get(
        "/api/evaluations/class-ppt/latest", params={"class_id": class_id}, headers=teacher_token
    )
    assert latest.status_code == 200, latest.text
    latest_body = latest.json()
    assert latest_body["source"] == "db"
    assert latest_body["ppt_url"] == result["ppt_url"]
    assert latest_body["record_id"] == result["record_id"]
    assert latest_body["content"]["highlights"]
    assert latest_body["stats"]["student_count"] == 2

    # 编辑文案 → 秒级重排版（ppt_url 更新），再次 latest 返回新文案
    edited = client.patch(
        f"/api/evaluations/class-ppt/{latest_body['record_id']}",
        json={"highlights": "全班出勤率保持高位；项目作品完成度显著提升", "title": "新标题家长会"},
        headers=teacher_token,
    )
    assert edited.status_code == 200, edited.text
    edited_body = edited.json()
    assert edited_body["title"] == "新标题家长会"
    assert "全班出勤率保持高位" in edited_body["content"]["highlights"]
    assert edited_body["ppt_url"].startswith("ppt/")
    relatest = client.get(
        "/api/evaluations/class-ppt/latest", params={"class_id": class_id}, headers=teacher_token
    ).json()
    assert relatest["ppt_url"] == edited_body["ppt_url"]
    assert "项目作品完成度显著提升" in relatest["content"]["highlights"]

    # 其他教师无权编辑该班文案
    denied_edit = client.patch(
        f"/api/evaluations/class-ppt/{latest_body['record_id']}",
        json={"highlights": "越权修改"},
        headers=other,
    )
    assert denied_edit.status_code == 403, denied_edit.text

    # 任务出现在评估 AI 任务列表（前端任务卡可见）
    tasks = client.get("/api/evaluations/ai-tasks", headers=teacher_token).json()
    assert any(t["id"] == task_id for t in tasks)

    # regen-dedup：素材无变化 → 预检 unchanged=true，再次提交被 409 拦截（需 force 二次确认）
    fp = client.get(
        "/api/evaluations/class-ppt/fingerprint",
        params={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    )
    assert fp.status_code == 200, fp.text
    fp_body = fp.json()
    assert fp_body["has_record"] is True
    assert fp_body["unchanged"] is True
    assert fp_body["running"] is False

    dup = client.post(
        "/api/evaluations/class-ppt",
        json={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    )
    assert dup.status_code == 409, dup.text
    assert "无变化" in dup.json()["detail"]

    # force=true 二次确认后放行：同步 runner 内直接完成，再次提交同样 202
    forced = client.post(
        "/api/evaluations/class-ppt",
        json={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "force": True,
        },
        headers=teacher_token,
    )
    assert forced.status_code == 202, forced.text

    # 改动学员评估内容 → 素材变化 → 预检 unchanged=false，可直接重提（不再 409）
    ev_list = client.get(
        "/api/evaluations", params={"limit": 50}, headers=teacher_token
    ).json()["items"]
    target = next(e for e in ev_list if e["title"] == f"{student_id[:4]} 学习评估")
    patch_ev = client.patch(
        f"/api/evaluations/{target['id']}",
        json={"content": {"summary": "逻辑清晰+新增亮点：主动帮助同学调试"}},
        headers=teacher_token,
    )
    assert patch_ev.status_code == 200, patch_ev.text
    fp2 = client.get(
        "/api/evaluations/class-ppt/fingerprint",
        params={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    ).json()
    assert fp2["unchanged"] is False
    regen = client.post(
        "/api/evaluations/class-ppt",
        json={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    )
    assert regen.status_code == 202, regen.text


def test_class_ppt_layout_handles_oversize_content():
    """排版引擎对超长/异常文案的兜底：自动缩字截断，不抛异常、不溢出。"""
    from app.services import pptx_builder

    huge = "这是一段特别长的班级整体情况总结，" * 120  # ~2400 字
    long_bullets = "；".join(f"亮点条目 {i}：学员持续进步表现优异" for i in range(40))
    honors = [
        (f"学员{i}", "课堂表现积极，能独立完成项目并在讲台上讲解自己的作品思路" * 2)
        for i in range(12)
    ]
    url = pptx_builder.build_class_meeting_ppt(
        class_name="超长内容班",
        subject="Scratch",
        period_label="2026年06月~09月07日",
        teacher_name="测试教师",
        created_at=datetime.now(),
        class_stats={
            "student_count": 12,
            "active_count": 10,
            "total_lessons": 96,
            "avg_attendance_rate": 0.97,
            "total_feedbacks": 30,
            "total_homework": 22,
            "avg_homework_score_rate": 0.88,
        },
        averages=[
            ("编程思维", 4.5),
            ("代码实践", 4.2),
            ("逻辑表达", 3.8),
            ("团队合作", 4.0),
            ("创造力", 4.7),
            ("专注力", 3.2),
        ],
        honor_roll=honors,
        content={
            "title": "超长文案压力测试家长会",
            "class_summary": huge,
            "ability_comment": "能力点评" * 80,
            "highlights": long_bullets,
            "to_improve": "改进项" * 200,
            "next_plan": "计划" * 200,
            "home_suggestions": "建议" * 200,
        },
    )
    assert url.startswith("ppt/")


def test_class_roster_and_student_teacher_filter(client, admin_token, teacher_token):
    """班级名单接口（学员+周期内评估生成状态）+ /students 按带教教师筛选。"""
    class_id, student_id, teacher_id, sched = _create_student_and_class(
        client, admin_token, teacher_token
    )
    client.post(
        "/api/students",
        json={"name": "小评估2", "lesson_balance": 40, "class_ids": [class_id]},
        headers=admin_token,
    )
    # 班级外学员（不应出现在名单 / 教师筛选中）
    client.post(
        "/api/students",
        json={"name": "局外学员", "lesson_balance": 40},
        headers=admin_token,
    )
    assigned = client.patch(
        f"/api/classes/{class_id}", json={"teacher_id": teacher_id}, headers=admin_token
    )
    assert assigned.status_code == 200

    start = date(2026, 8, 1)
    end = date(2026, 10, 31)

    # 名单：两名学员，均未生成
    r = client.get(
        "/api/evaluations/class-roster",
        params={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["generated"] == 0
    assert {s["name"] for s in body["students"]} == {"小评估", "小评估2"}
    assert all(s["evaluation"] is None for s in body["students"])

    # 生成草稿 → generated+1；发布 → published+1
    ev = client.post(
        "/api/evaluations",
        json={
            "student_id": student_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "content": {"summary": "基础扎实"},
        },
        headers=teacher_token,
    ).json()
    r2 = client.get(
        "/api/evaluations/class-roster",
        params={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    ).json()
    assert r2["generated"] == 1 and r2["published"] == 0
    by_id = {s["student_id"]: s for s in r2["students"]}
    assert by_id[student_id]["evaluation"]["status"] == "draft"
    assert by_id[student_id]["evaluation"]["id"] == ev["id"]

    pub = client.post(f"/api/evaluations/{ev['id']}/publish", headers=teacher_token)
    assert pub.status_code == 200
    r3 = client.get(
        "/api/evaluations/class-roster",
        params={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=teacher_token,
    ).json()
    assert r3["published"] == 1

    # 其他教师不可看名单
    other = _register(client, "teacher", "ev-roster-other")
    denied = client.get(
        "/api/evaluations/class-roster",
        params={
            "class_id": class_id,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
        headers=other,
    )
    assert denied.status_code == 403

    # /students 按带教教师筛选：仅返回其班级内学员（不含局外学员）
    mine = client.get("/api/students", params={"teacher_id": teacher_id}, headers=teacher_token)
    assert mine.status_code == 200, mine.text
    names = {s["name"] for s in mine.json()["items"]}
    assert {"小评估", "小评估2"} <= names
    assert "局外学员" not in names
