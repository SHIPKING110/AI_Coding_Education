"""M4 AI 习题测试：AI 出题（举一反三/作业模式/对话优化）、作业 CRUD、发布/撤回、题目管理。

需要本地 PostgreSQL；使用独立测试库 child_code_test。
"""

import uuid

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


@pytest.fixture()
def admin_token(client):
    return _register(client, "admin", "asg-admin")


def _uid(client, token_holder):
    r = client.get("/api/auth/me", headers=token_holder)
    assert r.status_code == 200
    return r.json()["id"]


def _make_class(client, admin_token, name):
    r = client.post("/api/classes", json={"name": name, "subject": "Python"}, headers=admin_token)
    assert r.status_code == 201
    return r.json()["id"]


def _single_choice(stem="下面哪个是合法的变量名？", answer=2, difficulty=2):
    return {
        "type": "single_choice",
        "stem": stem,
        "options": ["1a", "a b", "_name", "for"],
        "answer": answer,
        "analysis": "变量名不能以数字开头、不能含空格、不能是关键字。",
        "difficulty": difficulty,
    }


def _programming(stem="编写函数 add(a, b) 返回两数之和。", language="python"):
    return {
        "type": "programming",
        "stem": stem,
        "options": None,
        "answer": "def add(a, b):\n    return a + b",
        "analysis": "直接返回 a + b。",
        "difficulty": 3,
        "test_cases": [{"input": "1 2", "output": "3"}, {"input": "-1 5", "output": "4"}],
        "language": language,
    }


def _judgement(stem="Python 中列表可以包含不同类型的元素。", answer=True):
    return {
        "type": "judgement",
        "stem": stem,
        "options": None,
        "answer": answer,
        "analysis": "列表是异质容器，可包含不同类型元素。",
        "difficulty": 1,
    }


def test_assignment_crud_publish_flow(client, admin_token):
    """作业闭环：创建（含题目）-> 详情 -> 编辑题目 -> 发布（需班级）-> 撤回 -> 删除。"""
    teacher = _register(client, "teacher", "t-aw")
    class_id = _make_class(client, admin_token, "作业测试班")

    # 1. 创建作业（草稿，含 3 题）
    r = client.post(
        "/api/assignments",
        json={
            "title": "Python 基础练习",
            "description": "变量与列表知识点",
            "questions": [_single_choice(), _judgement(), _programming()],
        },
        headers=teacher,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assign_id = body["id"]
    assert body["status"] == "draft"
    assert body["question_count"] == 3
    assert len(body["questions"]) == 3
    assert [q["order_no"] for q in body["questions"]] == [1, 2, 3]
    prog = next(q for q in body["questions"] if q["type"] == "programming")
    assert prog["test_cases"][0]["output"] == "3"
    assert prog["language"] == "python"

    # 2. 详情
    detail = client.get(f"/api/assignments/{assign_id}", headers=teacher).json()
    assert detail["id"] == assign_id
    assert detail["class_name"] is None

    # 3. 编辑单题（改题干 + 选项）
    q1 = body["questions"][0]
    up = client.patch(
        f"/api/assignments/{assign_id}/questions/{q1['id']}",
        json={
            "stem": "哪个是合法的列表？",
            "options": ["(1,2)", "[1,2]", "{1,2}", "range(3)"],
            "answer": 1,
        },
        headers=teacher,
    )
    assert up.status_code == 200
    assert up.json()["stem"] == "哪个是合法的列表？"
    assert up.json()["answer"] == 1

    # 4. 追加题目 + 排序
    added = client.post(
        f"/api/assignments/{assign_id}/questions",
        json=[_single_choice(stem="新增第 4 题")],
        headers=teacher,
    )
    assert added.status_code == 200
    assert added.json()["question_count"] == 4
    ids = [q["id"] for q in added.json()["questions"]]
    reorder = client.put(
        f"/api/assignments/{assign_id}/questions/reorder",
        json={"question_ids": [ids[-1], *ids[:-1]]},
        headers=teacher,
    )
    assert reorder.status_code == 200
    assert reorder.json()["questions"][0]["stem"] == "新增第 4 题"

    # 5. 未指定班级不可发布（class_id 必填 -> 422）；无题目不可发布
    r_no_class = client.post(f"/api/assignments/{assign_id}/publish", json={}, headers=teacher)
    assert r_no_class.status_code == 422
    empty = client.post(
        "/api/assignments",
        json={"title": "空作业", "questions": []},
        headers=teacher,
    ).json()
    r_empty = client.post(
        f"/api/assignments/{empty['id']}/publish",
        json={"class_ids": [class_id]},
        headers=teacher,
    )
    assert r_empty.status_code == 400

    # 6. 发布（多班级 + 截止时间）
    deadline = "2026-09-30T23:59:00Z"
    pub = client.post(
        f"/api/assignments/{assign_id}/publish",
        json={"class_ids": [class_id], "deadline": deadline},
        headers=teacher,
    )
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["class_id"] == class_id
    assert pub.json()["class_name"] == "作业测试班"
    assert pub.json()["published_class_ids"] == [class_id]
    assert pub.json()["published_class_names"] == ["作业测试班"]
    assert pub.json()["published_at"] is not None
    assert pub.json()["deadline"] is not None

    # 7. 已发布班级不可重复发布 -> 400；可追加发布到新班级
    r_dup = client.post(
        f"/api/assignments/{assign_id}/publish",
        json={"class_ids": [class_id]},
        headers=teacher,
    )
    assert r_dup.status_code == 400
    assert "已发布" in r_dup.json()["detail"]
    class_b2 = _make_class(client, admin_token, "作业测试班B")
    pub_more = client.post(
        f"/api/assignments/{assign_id}/publish",
        json={"class_ids": [class_b2]},
        headers=teacher,
    )
    assert pub_more.status_code == 200
    assert set(pub_more.json()["published_class_ids"]) == {class_id, class_b2}
    assert pub_more.json()["status"] == "published"

    # 8. 已发布作业不可直接删除 -> 先撤回（撤回清空发布记录，可重新选班）
    r_del = client.delete(f"/api/assignments/{assign_id}", headers=teacher)
    assert r_del.status_code == 400
    back = client.post(f"/api/assignments/{assign_id}/unpublish", headers=teacher)
    assert back.status_code == 200
    assert back.json()["status"] == "draft"
    assert back.json()["published_at"] is None
    assert back.json()["published_class_ids"] == []
    # 撤回后原来发布过的班级可以再次发布
    repub = client.post(
        f"/api/assignments/{assign_id}/publish",
        json={"class_ids": [class_id]},
        headers=teacher,
    )
    assert repub.status_code == 200
    # 删除前先撤回
    back2 = client.post(f"/api/assignments/{assign_id}/unpublish", headers=teacher)
    assert back2.status_code == 200

    # 10. 删除题目（删除后重排序号）+ 删除作业
    qs = client.get(f"/api/assignments/{assign_id}", headers=teacher).json()["questions"]
    first_id = qs[0]["id"]
    r_del_q = client.delete(
        f"/api/assignments/{assign_id}/questions/{first_id}", headers=teacher
    )
    assert r_del_q.status_code == 204
    after = client.get(f"/api/assignments/{assign_id}", headers=teacher).json()
    assert after["question_count"] == 3
    assert [q["order_no"] for q in after["questions"]] == [1, 2, 3]

    r_del = client.delete(f"/api/assignments/{assign_id}", headers=teacher)
    assert r_del.status_code == 204
    gone = client.get(f"/api/assignments/{assign_id}", headers=teacher)
    assert gone.status_code == 404


def test_assignment_role_and_visibility(client, admin_token):
    """权限：教师仅可见/可操作自己的作业；家长/学员不可创建；教师不可见他人作业。"""
    teacher_a = _register(client, "teacher", "t-va")
    teacher_b = _register(client, "teacher", "t-vb")
    parent = _register(client, "parent", "p-v")

    a = client.post(
        "/api/assignments",
        json={"title": "A 的作业", "questions": [_single_choice()]},
        headers=teacher_a,
    ).json()

    # B 看不到 A 的作业（默认只看自己）
    b_list = client.get("/api/assignments", headers=teacher_b).json()
    assert all(item["id"] != a["id"] for item in b_list["items"])

    # B 查看 A 的作业详情 -> 403
    assert client.get(f"/api/assignments/{a['id']}", headers=teacher_b).status_code == 403

    # 管理员/教务可查看全部
    admin_list = client.get("/api/assignments", headers=admin_token).json()
    assert any(item["id"] == a["id"] for item in admin_list["items"])

    # 家长不可创建/不可出题
    r_p = client.post(
        "/api/assignments", json={"title": "x", "questions": []}, headers=parent
    )
    assert r_p.status_code == 403
    r_ai = client.post(
        "/api/assignments/ai-generate",
        json={"mode": "homework", "count": 2, "difficulty": 3, "hint": "列表"},
        headers=parent,
    )
    assert r_ai.status_code == 403


def _wait_task(client, headers, task_id, timeout=30.0):
    """轮询任务直至 done/failed（异步后台执行，测试需等待）。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/assignments/ai-tasks/{task_id}", headers=headers)
        assert r.status_code == 200
        task = r.json()
        if task["status"] in ("done", "failed"):
            return task
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} 未在 {timeout}s 内完成")


def test_assignment_ai_generate_similar(client, monkeypatch):
    """举一反三：AI 出题异步任务（mock 秒回）完成后返回相似题；未配 LLM 时 400 降级。"""
    from app.services import llm

    fake = [
        {
            "type": "single_choice",
            "stem": "改编题：哪个不是合法的标识符？",
            "options": ["_x", "x1", "1x", "x_1"],
            "answer": 2,
            "analysis": "标识符不能以数字开头。",
            "difficulty": 3,
        },
        {
            "type": "judgement",
            "stem": "判断：关键字不能作为变量名。",
            "answer": True,
            "analysis": "关键字被语言保留。",
            "difficulty": 2,
        },
    ]
    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "generate_questions", lambda **kw: fake)

    teacher = _register(client, "teacher", "t-ai1")
    r = client.post(
        "/api/assignments/ai-generate",
        json={
            "mode": "similar",
            "count": 2,
            "difficulty": 3,
            "source_question": "下面哪个是合法的变量名？",
            "source_answer": "_name",
        },
        headers=teacher,
    )
    # 提交即返回任务（202），不含结果 —— 前端据此轮询，期间可切页面
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["kind"] == "generate"
    assert body["status"] in ("pending", "running", "done")
    assert body["result"] is None or body["status"] == "done"
    assert "举一反三" in body["summary"]

    task = _wait_task(client, teacher, body["id"])
    assert task["status"] == "done", task.get("error")
    questions = task["result"]
    assert len(questions) == 2
    assert task["model"] is not None
    q0 = questions[0]
    assert q0["type"] == "single_choice"
    assert q0["answer"] == 2
    assert q0["difficulty"] == 3
    assert q0["language"] is None
    q1 = questions[1]
    assert q1["type"] == "judgement"
    assert q1["answer"] is True

    # 未配置 LLM -> 400 降级提示
    from app.services import llm_context as _llm_ctx
    monkeypatch.setattr(
        _llm_ctx, "require_llm", lambda *a, **k: (_ for _ in ()).throw(
            llm.LLMConfigError("未配置模型")
        ),
    )
    r_no = client.post(
        "/api/assignments/ai-generate",
        json={"mode": "similar", "count": 1, "difficulty": 3, "source_question": "x"},
        headers=teacher,
    )
    assert r_no.status_code == 400


def test_llm_normalize_question(monkeypatch):
    """LLM 出题结果规范化：字符串答案/难度转 int、判断文字转 bool、编程题补默认语言。"""
    from app.services import llm

    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    raw = (
        '[{"type": "single_choice", "stem": "哪个合法？", '
        '"options": ["1a", "a b", "_name", "for"], "answer": "2", '
        '"analysis": "变量名规则", "difficulty": "4"},'
        '{"type": "judgement", "stem": "判断", "answer": "正确", "difficulty": 1},'
        '{"type": "programming", "stem": "求和", "answer": "def f(): pass", '
        '"test_cases": [{"input": "1", "output": "2"}], "difficulty": 5}]'
    )
    monkeypatch.setattr(llm, "_invoke", lambda prompt: raw)
    questions = llm.generate_questions(
        mode="homework", count=3, difficulty=3, hint="变量"
    )
    assert questions[0]["type"] == "single_choice"
    assert questions[0]["answer"] == 2
    assert questions[0]["difficulty"] == 4
    assert questions[1]["answer"] is True
    assert questions[2]["type"] == "programming"
    assert questions[2]["language"] == "python"
    assert questions[2]["test_cases"][0]["output"] == "2"


def test_assignment_ai_generate_homework_and_refine(client, monkeypatch):
    """作业模式 + 对话优化：AI 生成整套题并可按要求重写单题。"""
    from app.services import llm

    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(
        llm,
        "generate_questions",
        lambda **kw: [_single_choice(stem="作业模式生成的题"), _programming()],
    )
    monkeypatch.setattr(
        llm,
        "refine_question",
        lambda **kw: dict(kw["question"], stem="按修改要求优化后的题干"),
    )

    teacher = _register(client, "teacher", "t-ai2")
    r = client.post(
        "/api/assignments/ai-generate",
        json={
            "mode": "homework",
            "count": 2,
            "difficulty": 3,
            "hint": "循环与条件判断",
            "types": ["single_choice", "programming"],
        },
        headers=teacher,
    )
    assert r.status_code == 202
    task = _wait_task(client, teacher, r.json()["id"])
    assert task["status"] == "done"
    questions = task["result"]
    assert len(questions) == 2
    assert questions[1]["type"] == "programming"
    assert questions[1]["language"] == "python"
    assert questions[1]["test_cases"][0]["input"] == "1 2"

    # 对话优化：基于题目 + 修改要求重新生成
    refine = client.post(
        "/api/assignments/ai-refine",
        json={
            "question": questions[0],
            "instruction": "把难度调低，换一个生活中排序的例子",
        },
        headers=teacher,
    )
    assert refine.status_code == 202
    refined = _wait_task(client, teacher, refine.json()["id"])
    assert refined["status"] == "done"
    assert "优化后的题干" in refined["result"]["stem"]


def test_assignment_ai_generate_parse_fallback(client, monkeypatch):
    """AI 输出无法解析时兜底：返回可编辑的占位题而非空结果。"""
    from app.services import llm

    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)
    monkeypatch.setattr(llm, "_invoke", lambda prompt: "抱歉，我不太理解这个知识点。")

    teacher = _register(client, "teacher", "t-ai3")
    r = client.post(
        "/api/assignments/ai-generate",
        json={"mode": "homework", "count": 3, "difficulty": 2, "hint": "很冷门的知识点"},
        headers=teacher,
    )
    assert r.status_code == 202
    task = _wait_task(client, teacher, r.json()["id"])
    assert task["status"] == "done"
    questions = task["result"]
    assert len(questions) == 1
    assert questions[0]["type"] == "code_fill"
    assert "解析失败" in questions[0]["stem"]


def test_assignment_ai_task_visibility_and_failure(client, monkeypatch):
    """任务可见性：教师仅看自己的任务；失败任务会记录 error。"""
    from app.services import llm

    monkeypatch.setattr(llm, "is_llm_configured", lambda: True)

    teacher_a = _register(client, "teacher", "t-vis-a")
    teacher_b = _register(client, "teacher", "t-vis-b")

    # 让任务抛错，验证 failed 状态与错误信息
    def _boom(**_kw):
        raise RuntimeError("mock ai error")

    monkeypatch.setattr(llm, "generate_questions", _boom)
    r = client.post(
        "/api/assignments/ai-generate",
        json={"mode": "similar", "count": 1, "difficulty": 3, "source_question": "x"},
        headers=teacher_a,
    )
    assert r.status_code == 202
    task = _wait_task(client, teacher_a, r.json()["id"])
    assert task["status"] == "failed"
    assert "mock ai error" in task["error"]

    # B 不能看 A 的任务
    forbid = client.get(f"/api/assignments/ai-tasks/{task['id']}", headers=teacher_b)
    assert forbid.status_code == 403
    # 自己可看
    mine = client.get(f"/api/assignments/ai-tasks/{task['id']}", headers=teacher_a)
    assert mine.status_code == 200

    # 列表仅返回自己的任务
    mine_list = client.get("/api/assignments/ai-tasks", headers=teacher_a).json()
    other_list = client.get("/api/assignments/ai-tasks", headers=teacher_b).json()
    assert any(t["id"] == task["id"] for t in mine_list)
    assert not any(t["id"] == task["id"] for t in other_list)


def test_assignment_list_filter_and_deadline(client, admin_token):
    """作业列表筛选：按状态/班级；截止时间可空；教师列表只含自己。"""
    teacher = _register(client, "teacher", "t-lf")
    class_a = _make_class(client, admin_token, "筛选A班")
    class_b = _make_class(client, admin_token, "筛选B班")

    client.post(
        "/api/assignments",
        json={"title": "草稿作业", "questions": [_single_choice()]},
        headers=teacher,
    ).json()
    published = client.post(
        "/api/assignments",
        json={"title": "发布作业", "questions": [_judgement()]},
        headers=teacher,
    ).json()
    client.post(
        f"/api/assignments/{published['id']}/publish",
        json={"class_ids": [class_a], "deadline": "2026-09-30T23:59:00Z"},
        headers=teacher,
    )
    # 多班级发布：同一作业追加发布到 B 班（A 班已发布不可重选）
    more = client.post(
        f"/api/assignments/{published['id']}/publish",
        json={"class_ids": [class_b]},
        headers=teacher,
    )
    assert more.status_code == 200
    assert set(more.json()["published_class_ids"]) == {class_a, class_b}

    drafts = client.get("/api/assignments?status=draft", headers=teacher).json()
    assert {i["title"] for i in drafts["items"]} == {"草稿作业"}
    pubs = client.get("/api/assignments?status=published", headers=teacher).json()
    assert {i["title"] for i in pubs["items"]} == {"发布作业"}

    # 按班级过滤：发布到 A 与 B 的作业都命中（多班级通过，M4.1）
    by_class = client.get(f"/api/assignments?class_id={class_a}", headers=admin_token).json()
    assert {i["title"] for i in by_class["items"]} == {"发布作业"}
    by_class_b = client.get(f"/api/assignments?class_id={class_b}", headers=admin_token).json()
    assert {i["title"] for i in by_class_b["items"]} == {"发布作业"}

    # 教师不能看他人作业（即使带 teacher_id 参数）
    other = _register(client, "teacher", "t-lf2")
    teacher_uid = _uid(client, teacher)
    r = client.get(
        f"/api/assignments?teacher_id={teacher_uid}", headers=other
    )
    assert r.status_code == 403
    # 但管理员可以
    admin_view = client.get(
        f"/api/assignments?teacher_id={teacher_uid}&status=published", headers=admin_token
    ).json()
    assert admin_view["total"] == 1


def test_questions_pool_filters_and_pagination(client, admin_token):
    """历史题目池：仅含已发布作业的题目；支持按作业标题/题型(多选)/难度筛选与分页。"""
    teacher = _register(client, "teacher", "t-pool")
    class_id = _make_class(client, admin_token, "题目池测试班")

    def create(title, questions):
        r = client.post(
            "/api/assignments",
            json={"title": title, "questions": questions},
            headers=teacher,
        )
        assert r.status_code == 201, r.text
        return r.json()

    a1 = create(
        "循环练习",
        [
            _single_choice(stem="循环题一", difficulty=2),
            _judgement(stem="循环题二"),
        ],
    )
    a2 = create("函数练习", [_programming(stem="函数题一")])

    # 草稿作业的题目不进入池
    r = client.get("/api/assignments/questions/pool?keyword=循环练习", headers=teacher)
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []

    # 发布到班级后进入池（跨教师可见 = 复用其他教师的题目）
    for a in (a1, a2):
        r = client.post(
            f"/api/assignments/{a['id']}/publish",
            json={"class_ids": [class_id]},
            headers=teacher,
        )
        assert r.status_code == 200, r.text

    # 按作业标题关键字锁定本次测试数据（共享测试库中可能还有其他已发布作业）
    scoped = {"keyword": "循环练习"}
    r = client.get("/api/assignments/questions/pool", params=scoped, headers=teacher)
    assert r.json()["total"] == 2
    r = client.get(
        "/api/assignments/questions/pool", params={"keyword": "函数练习"}, headers=teacher
    )
    assert r.json()["total"] == 1

    # 按题型多选筛选（逗号分隔）
    r = client.get(
        "/api/assignments/questions/pool",
        params={"keyword": "循环练习", "types": "single_choice,judgement"},
        headers=teacher,
    )
    body = r.json()
    assert body["total"] == 2
    assert all(it["type"] in ("single_choice", "judgement") for it in body["items"])

    # 按难度区间筛选
    r = client.get(
        "/api/assignments/questions/pool",
        params={"keyword": "函数练习", "difficulty_min": 3, "difficulty_max": 5},
        headers=teacher,
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["type"] == "programming"

    # 按作业标题关键字筛选（模糊匹配）
    r = client.get(
        "/api/assignments/questions/pool",
        params={"keyword": "循环"},
        headers=teacher,
    )
    body = r.json()
    assert body["total"] == 2
    assert all(it["assignment_title"] == "循环练习" for it in body["items"])

    # 分页：limit/offset 生效且条目含所属作业标题
    p1 = client.get(
        "/api/assignments/questions/pool",
        params={"keyword": "循环练习", "limit": 1, "offset": 0},
        headers=teacher,
    ).json()
    p2 = client.get(
        "/api/assignments/questions/pool",
        params={"keyword": "循环练习", "limit": 1, "offset": 1},
        headers=teacher,
    ).json()
    assert len(p1["items"]) == 1
    assert len(p2["items"]) == 1
    assert p1["items"][0]["id"] != p2["items"][0]["id"]
    assert p1["items"][0]["assignment_title"]
    assert "order_no" in p1["items"][0]
