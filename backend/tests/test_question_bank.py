"""题库模块 P1：DOCX 规则解析、导入审核发布闭环与权限隔离。"""
import base64
import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app
from app.services.question_bank_parser import parse_docx

TEST_DB_NAME = "child_code_qb_test"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _build_docx(path: Path, *, with_image: bool = False) -> Path:
    import docx

    document = docx.Document()
    # 核心属性写入文件名，保证每次生成的内容哈希不同，避免测试间命中上传去重
    document.core_properties.title = path.stem
    document.add_paragraph("青少年软件编程（Python）等级考试试卷（二级）")
    document.add_paragraph("分数：100  题数：3")
    document.add_paragraph("一、单选题(共2题，共4分)")
    document.add_paragraph("1.\t以下哪个是合法变量名？（ ）")
    document.add_paragraph("A. \t\t1a")
    document.add_paragraph("B. \t\t_name")
    document.add_paragraph("C. \t\ta b")
    document.add_paragraph("D. \t\tfor")
    document.add_paragraph("试题编号：202512-P2-01")
    document.add_paragraph("试题类型：单选题")
    document.add_paragraph("标准答案：B")
    document.add_paragraph("试题难度：较易")
    document.add_paragraph("试题解析：变量名不能以数字开头，也不能含空格或关键字。")
    document.add_paragraph("考生答案：A")
    document.add_paragraph("考生得分：0")
    document.add_paragraph("2.\t看图选择正确的机器人：（ ）")
    if with_image:
        document.add_picture(io.BytesIO(PNG_1PX))
    document.add_paragraph("A.")
    if with_image:
        document.add_picture(io.BytesIO(PNG_1PX))
    document.add_paragraph("B. \t\t机械臂")
    document.add_paragraph("试题编号：202512-P2-02")
    document.add_paragraph("标准答案：A")
    document.add_paragraph("试题解析：图示为机械臂。")
    document.add_paragraph("二、编程题(共1题，共10分)")
    document.add_paragraph("3.\t输出两数之和")
    document.add_paragraph("题目描述：")
    document.add_paragraph("输入两个整数，输出它们的和。")
    document.add_paragraph("输入样例：")
    document.add_paragraph("1 2")
    document.add_paragraph("输出样例：")
    document.add_paragraph("3")
    document.add_paragraph("试题编号：202512-P2-03")
    document.add_paragraph("试题类型：编程题")
    document.add_paragraph("参考代码：")
    document.add_paragraph("a, b = map(int, input().split())")
    document.add_paragraph("print(a + b)")
    document.add_paragraph("试题解析：")
    document.add_paragraph("直接求和输出。")
    document.add_paragraph("评分标准：")
    document.add_paragraph("（1）正确读入 5 分；（2）正确输出 5 分。")
    document.save(path)
    return path


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
        json={"role": role, "username": username, "password": "12345678a", "name": tag},
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"username": username, "password": "12345678a"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def admin_token(client):
    return _register(client, "admin", "qb-admin")


def test_parse_docx_rules_and_images(tmp_path):
    path = _build_docx(tmp_path / "202512py二级.docx", with_image=True)
    paper = parse_docx(path, media_dir=tmp_path / "media", media_url_prefix="/uploads/question_bank/demo/media")
    assert paper.subject == "Python"
    assert paper.level == "二级"
    assert paper.exam_year == 2025
    assert paper.institution == "中国电子学会"
    assert len(paper.questions) == 3
    first, second, third = paper.questions
    assert [q.order_no for q in paper.questions] == [1, 2, 3]
    assert first.type == "single_choice"
    assert first.answer == 1
    assert first.options == ["1a", "_name", "a b", "for"]
    assert "变量名不能以数字开头" in (first.analysis or "")
    assert second.type == "single_choice"
    assert second.answer == 0
    assert any(m["scope"] == "stem" for m in second.media)
    assert any(m["scope"] == "option:A" for m in second.media)
    assert third.type == "programming"
    assert third.language == "python"
    assert "print(a + b)" in (third.reference_code or "")
    assert any((tmp_path / "media").glob("img_*.png"))


def test_import_review_publish_and_visibility(client, admin_token, tmp_path):
    path = _build_docx(tmp_path / "202512py二级.docx")
    with path.open("rb") as fh:
        r = client.post(
            "/api/question-bank/imports",
            headers=admin_token,
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"institution": "中国电子学会", "subject": "Python", "level": "二级", "exam_year": "2025年12月"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    set_id = body["set_id"]
    assert body["question_count"] == 3

    detail = client.get(f"/api/question-bank/sets/{set_id}", headers=admin_token)
    assert detail.status_code == 200
    assert detail.json()["status"] == "draft"
    assert detail.json()["exam_year"] == 2025
    assert [q["order_no"] for q in detail.json()["questions"]] == [1, 2, 3]

    parent_token = _register(client, "parent", "qb-parent")
    teacher_token = _register(client, "teacher", "qb-teacher")
    assert client.get("/api/question-bank/sets", headers=parent_token).json()["total"] == 0
    assert client.get("/api/question-bank/sets", headers=teacher_token).json()["total"] == 0
    assert client.get(f"/api/question-bank/sets/{set_id}", headers=teacher_token).status_code == 404

    blocked = client.post(f"/api/question-bank/sets/{set_id}/publish", headers=admin_token)
    assert blocked.status_code == 409
    assert len(blocked.json()["detail"]["question_numbers"]) == 3

    reviewed = client.post(f"/api/question-bank/sets/{set_id}/review-all", headers=admin_token)
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewed"] == 3

    published = client.post(f"/api/question-bank/sets/{set_id}/publish", headers=admin_token)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    published_detail = client.get(f"/api/question-bank/sets/{set_id}", headers=admin_token).json()
    assert published_detail["questions"][0]["status"] == "published"

    assert client.get("/api/question-bank/sets", headers=teacher_token).json()["total"] == 1
    teacher_detail = client.get(f"/api/question-bank/sets/{set_id}", headers=teacher_token)
    assert teacher_detail.status_code == 200
    assert "answer" in teacher_detail.json()["questions"][0]

    parent_detail = client.get(f"/api/question-bank/sets/{set_id}", headers=parent_token)
    assert parent_detail.status_code == 200
    assert "answer" not in parent_detail.json()["questions"][0]

    with path.open("rb") as fh:
        duplicate = client.post(
            "/api/question-bank/imports",
            headers=admin_token,
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert duplicate.status_code == 409


@pytest.fixture()
def db_session(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()


def _publish_sample(client, admin_token, tmp_path) -> str:
    path = _build_docx(tmp_path / f"sample-{uuid.uuid4().hex[:6]}.docx")
    with path.open("rb") as fh:
        r = client.post(
            "/api/question-bank/imports",
            headers=admin_token,
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert r.status_code == 201, r.text
    set_id = r.json()["set_id"]
    assert client.post(f"/api/question-bank/sets/{set_id}/review-all", headers=admin_token).status_code == 200
    assert client.post(f"/api/question-bank/sets/{set_id}/publish", headers=admin_token).status_code == 200
    return set_id


def test_teacher_cannot_manage_bank(client):
    teacher_token = _register(client, "teacher", "qb-teacher-no")
    r = client.post(
        "/api/question-bank/imports",
        headers=teacher_token,
        files={"file": ("x.docx", io.BytesIO(b"not a docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 403


def test_practice_exam_and_learning_stats(client, admin_token, db_session, tmp_path):
    from app.models.enrollment import Student

    set_id = _publish_sample(client, admin_token, tmp_path)
    parent_token = _register(client, "parent", "qb-practice-parent")
    parent_id = client.get("/api/auth/me", headers=parent_token).json()["id"]
    student = Student(name="练习学员", parent_user_id=uuid.UUID(parent_id), lesson_balance=0)
    db_session.add(student)
    db_session.commit()

    started = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": str(student.id), "mode": "practice", "set_id": set_id},
    )
    assert started.status_code == 201, started.text
    attempt = started.json()
    assert attempt["status"] == "in_progress"
    assert len(attempt["questions"]) == 3
    assert "answer" not in attempt["questions"][0]
    qid = attempt["questions"][0]["id"]

    saved = client.post(
        f"/api/question-bank/attempts/{attempt['id']}/answers",
        headers=parent_token,
        json={"question_id": qid, "answer": 1},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_correct"] is True
    assert saved.json()["correct_answer"] == 1

    submitted = client.post(f"/api/question-bank/attempts/{attempt['id']}/submit", headers=parent_token)
    assert submitted.status_code == 200, submitted.text
    data = submitted.json()
    assert data["status"] == "evaluated"
    assert data["result"]["correct_count"] == 1
    assert data["result"]["score"] > 0
    assert data["questions"][0]["answer"] == 1

    stats = client.get(
        "/api/question-bank/learning-stats",
        headers=parent_token,
        params={"student_id": str(student.id)},
    )
    assert stats.status_code == 200, stats.text
    assert stats.json()["submitted"] == 1
    assert stats.json()["correct_rate"] > 0
    assert stats.json()["streak_days"] >= 1

    exam = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={
            "student_id": str(student.id),
            "mode": "exam",
            "rules": {"single_choice": 2, "judgement": 0, "programming": 0},
            "exam_minutes": 90,
        },
    )
    assert exam.status_code == 201, exam.text
    exam_data = exam.json()
    assert exam_data["mode"] == "exam"
    assert exam_data["paper_meta"]["exam_minutes"] == 90
    assert exam_data["answers"] == {}
    assert "answer" not in exam_data["questions"][0]
    exam_submitted = client.post(f"/api/question-bank/attempts/{exam_data['id']}/submit", headers=parent_token)
    assert exam_submitted.status_code == 200
    assert exam_submitted.json()["result"]["correct_count"] == 0

    gaps = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": str(student.id), "mode": "exam", "rules": {"single_choice": 99}},
    )
    assert gaps.status_code == 409
    assert "single_choice" in gaps.json()["detail"]["gaps"]


def test_clear_answer_and_attempt_access(client, admin_token, db_session, tmp_path):
    from app.models.enrollment import Student

    set_id = _publish_sample(client, admin_token, tmp_path)
    parent_token = _register(client, "parent", "qb-clear-parent")
    parent_id = client.get("/api/auth/me", headers=parent_token).json()["id"]
    student = Student(name="清答学员", parent_user_id=uuid.UUID(parent_id), lesson_balance=0)
    db_session.add(student)
    db_session.commit()

    started = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": str(student.id), "mode": "practice", "set_id": set_id},
    )
    assert started.status_code == 201, started.text
    attempt = started.json()
    qid = attempt["questions"][0]["id"]

    wrong = client.post(
        f"/api/question-bank/attempts/{attempt['id']}/answers",
        headers=parent_token,
        json={"question_id": qid, "answer": 999},
    )
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["is_correct"] is False

    cleared = client.post(
        f"/api/question-bank/attempts/{attempt['id']}/answers",
        headers=parent_token,
        json={"question_id": qid, "answer": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] is True

    refetched = client.get(f"/api/question-bank/attempts/{attempt['id']}", headers=parent_token).json()
    assert qid not in refetched["answers"]
    assert qid not in refetched["question_results"]

    wrong_book = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": str(student.id), "mode": "practice", "kind": "marked", "mark_kind": "wrong"},
    )
    assert wrong_book.status_code == 409

    trend = client.get("/api/question-bank/attempts/trend", headers=parent_token)
    assert trend.status_code == 200
    assert isinstance(trend.json()["weeks"], list)

def test_teacher_can_read_own_attempt(client, admin_token, tmp_path):
    set_id = _publish_sample(client, admin_token, tmp_path)
    teacher_token = _register(client, "teacher", "qb-own-attempt")

    started = client.post(
        "/api/question-bank/attempts",
        headers=teacher_token,
        json={"mode": "practice", "set_id": set_id},
    )
    assert started.status_code == 201, started.text
    attempt_id = started.json()["id"]

    refetch = client.get(f"/api/question-bank/attempts/{attempt_id}", headers=teacher_token)
    assert refetch.status_code == 200, refetch.text
    assert refetch.json()["id"] == attempt_id

def test_blueprints_and_to_assignment(client, admin_token, tmp_path):
    set_id = _publish_sample(client, admin_token, tmp_path)
    teacher_token = _register(client, "teacher", "qb-bp-teacher")

    created = client.post(
        "/api/question-bank/blueprints",
        headers=admin_token,
        json={"name": "Python 二级标准模考", "subject": "Python", "level": "二级", "rules": {"single_choice": 2, "judgement": 1}},
    )
    assert created.status_code == 201, created.text
    assert created.json()["rules"]["single_choice"] == 2
    listed = client.get("/api/question-bank/blueprints", headers=admin_token)
    assert listed.status_code == 200
    assert any(b["name"] == "Python 二级标准模考" for b in listed.json())

    composed = client.post(
        "/api/question-bank/compose",
        headers=teacher_token,
        json={"rules": {"single_choice": 2}},
    )
    assert composed.status_code == 200, composed.text
    assert len(composed.json()["questions"]) == 2
    assert "answer" in composed.json()["questions"][0]

    # 题库组作业需 question_bank_assignment 权限：未授权先 403，管理员授权后 201
    denied = client.post(
        f"/api/question-bank/sets/{set_id}/to-assignment",
        headers=teacher_token,
        json={"title": "题库生成作业"},
    )
    assert denied.status_code == 403, denied.text
    teacher_id = client.get("/api/auth/me", headers=teacher_token).json()["id"]
    granted = client.put(
        f"/api/permissions/teachers/{teacher_id}",
        headers=admin_token,
        json={"question_bank_assignment": True},
    )
    assert granted.status_code == 200, granted.text

    assignment = client.post(
        f"/api/question-bank/sets/{set_id}/to-assignment",
        headers=teacher_token,
        json={"title": "题库生成作业"},
    )
    assert assignment.status_code == 201, assignment.text
    assert assignment.json()["question_count"] == 3
    assert assignment.json()["title"] == "题库生成作业"


def test_question_bank_ai_task_lookup(client):
    token = _register(client, "parent", "qb-ai-task-parent")
    missing = client.get("/api/question-bank/ai-tasks/does-not-exist", headers=token)
    assert missing.status_code == 404
    active = client.get("/api/question-bank/ai-tasks", headers=token)
    assert active.status_code == 200
    assert active.json()["tasks"] == []


def test_delete_set_frees_document_hash(client, admin_token, tmp_path):
    """彻底删除套卷后，同一文档可重新上传（哈希去重不再误拦）。"""
    path = _build_docx(tmp_path / "202512py二级.docx")
    with path.open("rb") as fh:
        first = client.post(
            "/api/question-bank/imports",
            headers=admin_token,
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"institution": "中国电子学会", "subject": "Python", "level": "二级"},
        )
    assert first.status_code == 201, first.text
    set_id = first.json()["set_id"]

    deleted = client.delete(f"/api/question-bank/sets/{set_id}", headers=admin_token)
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/question-bank/sets/{set_id}", headers=admin_token).status_code == 404

    with path.open("rb") as fh:
        again = client.post(
            "/api/question-bank/imports",
            headers=admin_token,
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"institution": "中国电子学会", "subject": "Python", "level": "二级"},
        )
    assert again.status_code == 201, again.text
    assert again.json()["question_count"] == 3


def test_close_untouched_attempt_is_removed(client, admin_token, db_session, tmp_path):
    """未作答的记录点「取消」应从做题记录中移除，不留 0 分且不计入统计。"""
    from app.models.enrollment import Student

    set_id = _publish_sample(client, admin_token, tmp_path)
    parent_token = _register(client, "parent", "qb-cancel-parent")
    parent_id = client.get("/api/auth/me", headers=parent_token).json()["id"]
    student = Student(name="未做学员", parent_user_id=uuid.UUID(parent_id), lesson_balance=0)
    db_session.add(student)
    db_session.commit()

    started = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": str(student.id), "mode": "practice", "set_id": set_id},
    )
    assert started.status_code == 201, started.text
    attempt_id = started.json()["id"]

    closed = client.post(f"/api/question-bank/attempts/{attempt_id}/close", headers=parent_token)
    assert closed.status_code == 200, closed.text
    assert closed.json().get("abandoned") is True

    # 记录已移除：查询返回 404，列表不再计入
    assert client.get(f"/api/question-bank/attempts/{attempt_id}", headers=parent_token).status_code == 404
    listed = client.get("/api/question-bank/attempts", headers=parent_token)
    assert listed.json()["total"] == 0

    # 统计不受污染
    stats = client.get(
        "/api/question-bank/learning-stats",
        headers=parent_token,
        params={"student_id": str(student.id)},
    )
    assert stats.json()["attempts"] == 0
    assert stats.json()["submitted"] == 0


def test_close_answered_attempt_is_still_evaluated(client, admin_token, db_session, tmp_path):
    """已作答的记录点「取消」仍正常评估并保留在做题记录中。"""
    from app.models.enrollment import Student

    set_id = _publish_sample(client, admin_token, tmp_path)
    parent_token = _register(client, "parent", "qb-answered-parent")
    parent_id = client.get("/api/auth/me", headers=parent_token).json()["id"]
    student = Student(name="已作答学员", parent_user_id=uuid.UUID(parent_id), lesson_balance=0)
    db_session.add(student)
    db_session.commit()

    started = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": str(student.id), "mode": "practice", "set_id": set_id},
    )
    assert started.status_code == 201, started.text
    attempt = started.json()
    qid = attempt["questions"][0]["id"]

    saved = client.post(
        f"/api/question-bank/attempts/{attempt['id']}/answers",
        headers=parent_token,
        json={"question_id": qid, "answer": 0},
    )
    assert saved.status_code == 200, saved.text

    closed = client.post(f"/api/question-bank/attempts/{attempt['id']}/close", headers=parent_token)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "evaluated"
    assert "abandoned" not in closed.json()

    kept = client.get(f"/api/question-bank/attempts/{attempt['id']}", headers=parent_token)
    assert kept.status_code == 200


