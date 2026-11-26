"""题库 P4：AI 校准/打标、知识点词表、能力评语及练习考试扩展。"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app
from app.models.enrollment import Student
from app.models.question_bank import (
    BankQuestionStatus,
    BankSetStatus,
    QuestionBankKpTaxonomy,
    QuestionBankQuestion,
    QuestionBankSet,
    QuestionBankSource,
)

TEST_DB_NAME = "child_code_qb_ai_test"


@pytest.fixture(scope="session")
def test_engine():
    from sqlalchemy import create_engine, text

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
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def admin_token(client):
    return _register(client, "admin", "qbai-admin")


@pytest.fixture()
def db_session(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()


def _publish_sample(db_session, question_status=None):
    """直接写入一套已发布套卷（含 3 道题），避免 DOCX 解析依赖。"""
    from app.models.user import User

    status_value = question_status or BankQuestionStatus.PUBLISHED.value

    uploader_id = db_session.query(User.id).first()[0]
    source = QuestionBankSource(
        filename="sample.docx",
        storage_path="uploads/question_bank/test/sample.docx",
        file_hash=uuid.uuid4().hex,
        uploaded_by=uploader_id,
    )
    db_session.add(source)
    db_session.flush()
    bank_set = QuestionBankSet(
        source_id=source.id,
        name="AI 校准样卷",
        subject="Python",
        level="二级",
        status=BankSetStatus.PUBLISHED.value,
    )
    db_session.add(bank_set)
    db_session.flush()
    q1 = QuestionBankQuestion(
        bank_set_id=bank_set.id,
        order_no=1,
        type="single_choice",
        stem="以下哪个是合法变量名？",
        options=["1a", "_name", "a b", "for"],
        answer=1,
        analysis="变量名不能以数字开头，也不能含空格或关键字。",
        score=2,
        status=status_value,
    )
    q2 = QuestionBankQuestion(
        bank_set_id=bank_set.id,
        order_no=2,
        type="multiple_choice",
        stem="选出全部编程语言",
        options=["Python", "HTML", "Java", "Word"],
        answer=[0, 2],
        analysis="Python 与 Java 是编程语言。",
        score=2,
        status=BankQuestionStatus.PUBLISHED.value,
    )
    q3 = QuestionBankQuestion(
        bank_set_id=bank_set.id,
        order_no=3,
        type="programming",
        stem="输出两数之和",
        options=[],
        answer=None,
        analysis="直接求和输出。",
        reference_code="a, b = map(int, input().split())\nprint(a + b)",
        score=6,
        status=BankQuestionStatus.PUBLISHED.value,
    )
    db_session.add_all([q1, q2, q3])
    db_session.commit()
    return str(bank_set.id), [str(q1.id), str(q2.id), str(q3.id)]


def _mock_llm(monkeypatch, validate_payload=None, tag_payload=None):
    from app.services import llm as llm_mod
    from app.services import question_bank_ai as qb_ai_mod

    class _Resolved:
        model = "test-model"

    class _Ctx:
        def __enter__(self):
            return _Resolved()

        def __exit__(self, *exc):
            return False

    def fake_invoke_text(system, prompt, *, temperature=0.0, timeout=90):
        if "审校" in system:
            return validate_payload or (
                '{"aligned":true,"confidence":0.95,"issues":[{"code":"analysis_missing","message":"缺少解析"}],'
                '"fixes":{"analysis":"补充后的解析"},"reasons":["解析不足"]}'
            )
        if "标注" in system:
            return tag_payload or '{"knowledge_points":["循环结构","变量"],"confidence":0.9}'
        return '{"submitted":0,"correct_rate":0}'

    monkeypatch.setattr(llm_mod, "is_llm_configured", lambda: True)
    monkeypatch.setattr(qb_ai_mod.llm, "invoke_text", fake_invoke_text)
    monkeypatch.setattr(qb_ai_mod, "use_teacher_llm", lambda db, user_id, module: _Ctx())


def test_validation_structured_rules(client, admin_token, db_session):
    set_id, _qids = _publish_sample(db_session)
    r = client.get(f"/api/question-bank/sets/{set_id}/validation", headers=admin_token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert not any(issue["code"] == "number_gap" for issue in body["issues"])
    assert not any(issue["code"] == "missing_reference_code" for issue in body["issues"])
    assert not any(issue["code"] == "missing_answer" for issue in body["issues"])


def test_ai_validate_and_revert(client, admin_token, db_session, monkeypatch):
    _set_id, qids = _publish_sample(db_session, question_status=BankQuestionStatus.DRAFT.value)
    _mock_llm(monkeypatch)

    qid = qids[0]
    r = client.post(
        f"/api/question-bank/questions/{qid}/ai-validate",
        headers=admin_token,
        json={"apply": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is True
    assert body["review"]["status"] == "applied"
    assert body["review"]["kind"] == "validate"
    assert "补充后的解析" in body["question"]["analysis"]

    # 撤销可回到校准前内容
    r3 = client.post(f"/api/question-bank/questions/{qid}/ai-validate/revert", headers=admin_token)
    assert r3.status_code == 200, r3.text
    assert r3.json()["analysis"] == "变量名不能以数字开头，也不能含空格或关键字。"

    # 再次撤销应 409
    r4 = client.post(f"/api/question-bank/questions/{qid}/ai-validate/revert", headers=admin_token)
    assert r4.status_code == 409, r4.text


def test_ai_validate_set(client, admin_token, db_session, monkeypatch):
    set_id, qids = _publish_sample(db_session)
    _mock_llm(monkeypatch)

    r = client.post(
        f"/api/question-bank/sets/{set_id}/ai-validate",
        headers=admin_token,
        json={"question_ids": [qids[0], qids[1]], "apply": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["processed"] == 2
    assert body["applied"] == 0  # apply=False 仅出 suggested，不落库
    assert all(item["review"]["status"] == "suggested" for item in body["items"])
    assert body["failed"] == 0


def test_ai_tag_set(client, admin_token, db_session, monkeypatch):
    set_id, qids = _publish_sample(db_session)
    _mock_llm(monkeypatch, tag_payload='{"knowledge_points":["循环结构"],"confidence":0.8}')

    r = client.post(
        f"/api/question-bank/sets/{set_id}/ai-tag",
        headers=admin_token,
        json={"question_ids": [qids[0]]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tagged"] == 1
    assert body["items"][0]["knowledge_points"] == ["循环结构"]
    assert db_session.query(QuestionBankKpTaxonomy).filter_by(name="循环结构").first() is not None


def test_kp_taxonomy_crud(client, admin_token):
    created = client.post(
        "/api/question-bank/kp-taxonomy",
        headers=admin_token,
        json={
            "subject": "Python",
            "level": "二级",
            "code": "LP01",
            "name": "循环结构",
            "parent": None,
            "sort_order": 1,
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["code"] == "LP01"

    dup = client.post(
        "/api/question-bank/kp-taxonomy",
        headers=admin_token,
        json={
            "subject": "Python",
            "level": "二级",
            "code": "LP01",
            "name": "循环结构",
            "status": "active",
        },
    )
    assert dup.status_code == 409, dup.text

    listed = client.get("/api/question-bank/kp-taxonomy?subject=Python&level=二级", headers=admin_token)
    assert listed.status_code == 200
    assert any(item["code"] == "LP01" for item in listed.json()["items"])


def test_ability_comment_no_data(client, admin_token):
    r = client.post(
        "/api/question-bank/ability-comment",
        headers=admin_token,
        json={"student_id": None, "days": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False
    assert "还没有已完成的练习或考试" in body["content"]
    assert body["stats"]["submitted"] == 0


def test_practice_marked_and_close(client, admin_token, db_session):
    set_id, _qids = _publish_sample(db_session)
    parent_token = _register(client, "parent", "qbai-practice-parent")
    parent_id = client.get("/api/auth/me", headers=parent_token).json()["id"]
    student = Student(name="AI 练习学员", parent_user_id=uuid.UUID(parent_id), lesson_balance=0)
    db_session.add(student)
    db_session.commit()
    student_id = str(student.id)

    # 错题本模式：暂无错题时应 409
    marked_empty = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": student_id, "mode": "practice", "kind": "marked", "mark_kind": "wrong"},
    )
    assert marked_empty.status_code == 409, marked_empty.text

    # 普通练习：答错一题后关闭会话（未交卷）
    started = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": student_id, "mode": "practice", "kind": "set_practice", "set_id": set_id},
    )
    assert started.status_code == 201, started.text
    attempt_id = started.json()["id"]
    qid = started.json()["questions"][0]["id"]  # 第 1 题正确答案为索引 1，选 0 判错
    saved = client.post(
        f"/api/question-bank/attempts/{attempt_id}/answers",
        headers=parent_token,
        json={"question_id": qid, "answer": 0},
    )
    assert saved.status_code == 200
    assert saved.json()["is_correct"] is False

    closed = client.post(f"/api/question-bank/attempts/{attempt_id}/close", headers=parent_token)
    assert closed.status_code == 200, closed.text
    closed_body = closed.json()
    assert closed_body["kind"] == "set_practice"
    assert closed_body["question_results"][qid]["is_correct"] is False

    # 错题已入错题本：错题本模式可组出 1 题
    marked = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": student_id, "mode": "practice", "kind": "marked", "mark_kind": "wrong"},
    )
    assert marked.status_code == 201, marked.text
    assert len(marked.json()["questions"]) == 1

    # 学习统计：knowledge_stats / radar 字段存在；练习模式无达标评级
    stats = client.get(
        "/api/question-bank/learning-stats",
        headers=parent_token,
        params={"student_id": student_id},
    )
    assert stats.status_code == 200, stats.text
    stats_body = stats.json()
    assert stats_body["attempts"] >= 1
    assert "knowledge_stats" in stats_body and "radar" in stats_body
    for item in stats_body["recent"]:
        assert item["rating"] is None

    # 考试模式（exam_set）：交卷后有 normalized_score 与达标评级
    exam = client.post(
        "/api/question-bank/attempts",
        headers=parent_token,
        json={"student_id": student_id, "mode": "exam", "kind": "exam_set", "set_id": set_id},
    )
    assert exam.status_code == 201, exam.text
    exam_id = exam.json()["id"]
    assert exam.json()["mode"] == "exam"
    assert exam.json()["kind"] == "exam_set"
    submitted = client.post(f"/api/question-bank/attempts/{exam_id}/submit", headers=parent_token)
    assert submitted.status_code == 200, submitted.text
    exam_body = submitted.json()
    assert "normalized_score" in exam_body["result"]
    assert exam_body["result"]["rating"] in ("达标", "未达标")
    assert len(exam_body["questions"]) == 3
