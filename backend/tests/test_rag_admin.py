"""RAG 运营后台：管理员权限、配置版本、trace 落库、虚拟知识库统计。"""

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 —— 注册全部 ORM 模型
from app.core.database import Base
from app.main import app
from app.services.rag import _split_multi_intent, _title_overlap, _apply_title_boost, _demote_faq_on_tie, _effective_score

TEST_DB_NAME = "child_code_rag_admin_test"


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
def client(test_engine, tmp_path_factory, monkeypatch):
    from app.api import deps
    from app.api.routers import rag_admin as rag_admin_router
    from app.services import rag, rag_evaluation, rag_trace

    rag.CHROMA_DIR = tmp_path_factory.mktemp("rag-admin-chroma")
    TestSession = sessionmaker(bind=test_engine)
    rag._SESSION_FACTORY = TestSession
    rag.invalidate_embedding_cache()
    rag.invalidate_parent_embedding_cache()
    # 测试不加载本地 Qwen（冷启动 >30s 会让评测轮询超时）；向量查询仍走真实 Chroma 空集合
    monkeypatch.setattr(
        rag, "embed_texts",
        lambda texts, *args, **kwargs: [[0.0, 0.0, 0.0, 0.0] for _ in texts],
    )
    rag_trace._SESSION_FACTORY = TestSession
    rag_evaluation._SESSION_FACTORY = TestSession
    rag_admin_router._SESSION_FACTORY = TestSession
    # 评测后台线程会调用 LLM；即使调用失败也不能把 usage 账本写进开发库
    from app.services import usage_meter

    usage_meter._session_factory = TestSession
    rag_trace.flush(0.1)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    c = TestClient(app)
    c.test_session_factory = TestSession  # type: ignore[attr-defined]
    yield c
    rag._SESSION_FACTORY = None
    rag.invalidate_embedding_cache()
    rag.invalidate_parent_embedding_cache()
    app.dependency_overrides.clear()


def _register(client, role: str, tag: str) -> tuple[dict, dict]:
    username = f"{tag}-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/auth/register",
        json={"role": role, "username": username, "password": "123456", "name": tag},
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    token = login.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return {"Authorization": f"Bearer {token}"}, me


def test_rag_admin_requires_admin(client):
    teacher_h, _ = _register(client, "teacher", "rag-t")
    admin_h, _ = _register(client, "admin", "rag-a")

    assert client.get("/api/admin/rag/overview", headers=teacher_h).status_code == 403
    r = client.get("/api/admin/rag/overview", headers=admin_h)
    assert r.status_code == 200, r.text
    assert "assets" in r.json()


def test_config_get(client):
    admin_h, _ = _register(client, "admin", "rag-cfg-get")
    r = client.get("/api/admin/rag/config", headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "config" in body and "defaults" in body
    assert body["config"]["top_k"] >= 1


def test_config_version_and_rollback(client):
    admin_h, admin_me = _register(client, "admin", "rag-cfg")
    from app.services import rag_settings

    rag_settings.invalidate()
    r = client.put("/api/admin/rag/config", json={"config": {"top_k": 7}, "note": "v1"}, headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["config"]["top_k"] == 7

    r2 = client.put("/api/admin/rag/config", json={"config": {"top_k": 9}, "note": "v2"}, headers=admin_h)
    assert r2.status_code == 200, r2.text
    _db = client.test_session_factory()
    try:
        assert rag_settings.get_config(_db, force=True)["top_k"] == 9
    finally:
        _db.close()

    versions = client.get("/api/admin/rag/config/versions", headers=admin_h).json()["items"]
    assert versions
    v1 = min(v["version"] for v in versions)
    rr = client.post(f"/api/admin/rag/config/rollback/{v1}", headers=admin_h)
    assert rr.status_code == 200, rr.text
    _db = client.test_session_factory()
    try:
        assert rag_settings.get_config(_db, force=True)["top_k"] == 7
    finally:
        _db.close()

    audit = client.get("/api/admin/rag/audit", headers=admin_h).json()["items"]
    assert any(a["action"] == "config.update" for a in audit)


def test_trace_persisted_and_virtual_bases(client):
    admin_h, admin_me = _register(client, "admin", "rag-tr")
    teacher_h, teacher_me = _register(client, "teacher", "rag-kb")

    from app.models.knowledge import KnowledgeDocument
    from app.services import rag_trace

    db = client.test_session_factory()
    try:
        db.add(KnowledgeDocument(
            owner_id=uuid.UUID(teacher_me["id"]), title="家长政策A",
            description="退费与请假政策", status="ready", chunk_count=3,
            visibility="private", enabled=True, visible_to_parents=True,
        ))
        db.commit()
    finally:
        db.close()

    bases = client.get("/api/admin/rag/knowledge-bases", headers=admin_h).json()["items"]
    private = next(x for x in bases if x["key"] == "private")
    parent = next(x for x in bases if x["key"] == "parent")
    assert private["documents"] >= 1
    assert private["chunks"] >= 3
    assert parent["documents"] >= 1

    with rag_trace.trace_scope(
        domain="admin_test", user_id=admin_me["id"], owner_id=admin_me["id"], route="admin_test",
    ) as ctx:
        rag_trace.record(
            ctx, query="退费政策是什么", hits=[{
                "doc_id": "d1", "title": "家长政策A", "similarity": 0.9,
                "rerank_score": None, "rrf_score": None, "preview": "退费规则",
            }],
            vector_ok=True, latency_ms=12, stage_timings={"vector": 5.0},
        )
    assert rag_trace.flush(3.0)
    deadline = time.time() + 3
    items = []
    while time.time() < deadline:
        items = client.get("/api/admin/rag/traces", headers=admin_h).json()["items"]
        if items:
            break
        time.sleep(0.1)
    assert items, "trace 应已异步落库"
    assert items[0]["query"] == "退费政策是什么"
    assert items[0]["hits"][0]["title"] == "家长政策A"
    assert True


def test_route_override(client):
    admin_h, _ = _register(client, "admin", "rag-route")
    r = client.put("/api/admin/rag/routes/agent_teacher", json={
        "top_k": 3, "min_similarity": 0.42, "per_doc_cap": 1,
    }, headers=admin_h)
    assert r.status_code == 200, r.text
    routes = client.get("/api/admin/rag/routes", headers=admin_h).json()["items"]
    agent = next(x for x in routes if x["key"] == "agent_teacher")
    assert agent["effective"]["top_k"] == 3
    assert agent["effective"]["min_similarity"] == 0.42
    assert agent["override"]["per_doc_cap"] == 1


def test_parent_sessions_endpoint(client):
    admin_h, _ = _register(client, "admin", "rag-ps")
    from app.models.parent_service import ParentServiceMessage, ParentServiceThread

    db = client.test_session_factory()
    try:
        thread = ParentServiceThread(status="open", risk_flag=True)
        db.add(thread)
        db.commit()
        db.refresh(thread)
        db.add(ParentServiceMessage(thread_id=thread.id, role="user", content="退费怎么处理"))
        db.commit()
        thread_id = str(thread.id)
    finally:
        db.close()

    rows = client.get("/api/admin/rag/parent-sessions", headers=admin_h).json()
    assert rows["total"] >= 1
    item = next(x for x in rows["items"] if x["thread_id"] == thread_id)
    assert item["risk_flag"] is True
    assert item["message_count"] >= 1

    risk_rows = client.get("/api/admin/rag/parent-sessions", params={"risk": True}, headers=admin_h).json()
    assert any(x["thread_id"] == thread_id for x in risk_rows["items"])

    detail = client.get(f"/api/admin/rag/parent-sessions/{thread_id}", headers=admin_h)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["thread"]["id"] == thread_id
    assert body["messages"][0]["content"] == "退费怎么处理"


def test_eval_run_completes(client):
    admin_h, admin_me = _register(client, "admin", "rag-eval")
    # 创建评测集与用例
    s = client.post("/api/admin/rag/eval/sets", json={
        "name": "种子集", "domain": "agent_teacher", "owner_id": admin_me["id"],
    }, headers=admin_h).json()
    client.post(f"/api/admin/rag/eval/sets/{s['id']}/cases", json={
        "query": "测试问题", "relevant": ["不存在的文档"], "query_type": "fact",
    }, headers=admin_h)
    r = client.post(f"/api/admin/rag/eval/sets/{s['id']}/runs", json={
        "owner_id": admin_me["id"], "top_k": 3,
    }, headers=admin_h)
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    # 轮询完成（冷启动首次导入 Chroma/本地依赖可能较慢，给 30s 余量）
    deadline = time.time() + 30
    run = None
    while time.time() < deadline:
        run = client.get(f"/api/admin/rag/eval/runs/{run_id}", headers=admin_h).json()["run"]
        if run["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert run is not None and run["status"] == "done", run
    assert "off" in (run["metrics"] or {}) and "on" in (run["metrics"] or {})


def test_eval_cases_paginated(client):
    admin_h, admin_me = _register(client, "admin", "rag-eval-page")
    s = client.post("/api/admin/rag/eval/sets", json={
        "name": "分页集", "domain": "agent_teacher", "owner_id": admin_me["id"],
    }, headers=admin_h).json()
    cases = [{"query": f"分页问题 {i}", "relevant": ["文档"]} for i in range(25)]
    bulk = client.post(
        f"/api/admin/rag/eval/sets/{s['id']}/cases/bulk",
        json={"cases": cases}, headers=admin_h,
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["created"] == 25

    page1 = client.get(
        f"/api/admin/rag/eval/sets/{s['id']}/cases",
        params={"page": 1, "page_size": 10}, headers=admin_h,
    ).json()
    assert page1["total"] == 25
    assert page1["page"] == 1 and page1["page_size"] == 10
    assert len(page1["items"]) == 10

    page3 = client.get(
        f"/api/admin/rag/eval/sets/{s['id']}/cases",
        params={"page": 3, "page_size": 10}, headers=admin_h,
    ).json()
    assert page3["total"] == 25
    assert len(page3["items"]) == 5


def test_eval_cases_bulk_partial_and_dedupe(client):
    admin_h, admin_me = _register(client, "admin", "rag-eval-bulk")
    s = client.post("/api/admin/rag/eval/sets", json={
        "name": "批量校验集", "domain": "agent_teacher", "owner_id": admin_me["id"],
    }, headers=admin_h).json()
    r = client.post(
        f"/api/admin/rag/eval/sets/{s['id']}/cases/bulk",
        json={
            "cases": [
                {"query": "重复问题", "relevant": []},
                {"query": " 重复问题 ", "relevant": []},
                {"relevant": []},
                {"query": "另一个问题", "relevant": ["文档"]},
            ],
            "skip_duplicates": True,
        },
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["skipped_duplicates"] == 1
    assert body["failed"] == 1
    assert body["errors"][0]["index"] == 3


def test_eval_run_rejects_same_generation_and_judge_model(client, monkeypatch):
    from app.services import rag_evaluation

    monkeypatch.setattr(rag_evaluation, "start_run", lambda run_id: None)
    admin_h, admin_me = _register(client, "admin", "rag-eval-model")
    cfg1 = client.post("/api/llm-configs", json={
        "name": "生成模型", "base_url": "https://example.com/v1",
        "api_key": "sk-test", "model": "model-a",
    }, headers=admin_h).json()
    cfg2 = client.post("/api/llm-configs", json={
        "name": "裁判模型", "base_url": "https://example.com/v1",
        "api_key": "sk-test", "model": "model-b",
    }, headers=admin_h).json()
    assert cfg1["id"] != cfg2["id"]

    models = client.get("/api/admin/rag/eval/models", headers=admin_h).json()
    assert {m["id"] for m in models["items"]} >= {cfg1["id"], cfg2["id"]}

    s = client.post("/api/admin/rag/eval/sets", json={
        "name": "模型校验集", "domain": "agent_teacher", "owner_id": admin_me["id"],
    }, headers=admin_h).json()
    client.post(f"/api/admin/rag/eval/sets/{s['id']}/cases", json={
        "query": "模型校验问题", "relevant": ["文档"],
    }, headers=admin_h)

    same = client.post(f"/api/admin/rag/eval/sets/{s['id']}/runs", json={
        "owner_id": admin_me["id"], "answer_eval": True,
        "generation_config_id": cfg1["id"], "judge_config_id": cfg1["id"],
    }, headers=admin_h)
    assert same.status_code == 400, same.text

    same_model = client.post("/api/admin/rag/eval/sets/{}/runs".format(s["id"]), json={
        "owner_id": admin_me["id"], "answer_eval": True,
        "generation_config_id": cfg1["id"], "judge_config_id": cfg2["id"],
    }, headers=admin_h)
    assert same_model.status_code == 200, same_model.text
    assert same_model.json()["generation_model"] == "model-a"
    assert same_model.json()["judge_model"] == "model-b"

    cfg3 = client.post("/api/llm-configs", json={
        "name": "同模型配置", "base_url": "https://example.com/v1",
        "api_key": "sk-test", "model": "model-a",
    }, headers=admin_h).json()
    duplicate_model = client.post(f"/api/admin/rag/eval/sets/{s['id']}/runs", json={
        "owner_id": admin_me["id"], "answer_eval": True,
        "generation_config_id": cfg1["id"], "judge_config_id": cfg3["id"],
    }, headers=admin_h)
    assert duplicate_model.status_code == 400, duplicate_model.text


def test_split_multi_intent_parallel_signals():
    query = (
        "家长发现机构教室电脑很旧、上课经常卡顿，同时顾问说老师都是清北毕业。"
        "文档里对这两个信号分别怎么判断？"
    )
    parts = _split_multi_intent(query)
    assert len(parts) == 2
    assert "电脑很旧" in parts[0]
    assert "清北毕业" in parts[1]
    assert all("这两个信号" not in p for p in parts)


def test_split_multi_intent_two_questions():
    query = (
        "孩子从Scratch转Python后频繁报错、开始抵触，家长应该先排查课程匹配度"
        "还是先考虑退费？退费时合同里哪条最关键？"
    )
    parts = _split_multi_intent(query)
    assert len(parts) == 2
    assert "课程匹配度" in parts[0]
    assert "合同" in parts[1]


def test_split_multi_intent_single_question():
    query = "GESP和CSP怎么衔接？"
    assert _split_multi_intent(query) == [query]


def test_split_multi_intent_ignores_short_followups():
    query = "听说现在强基计划省一都不好使了？真的假的？那银牌呢？"
    # 短追问不是独立检索意图，不能把主问句拆成噪声子查询
    assert _split_multi_intent(query) == [query]


def test_title_overlap_prefers_specific_document():
    ratio = _title_overlap("退费多久到账？", "C3 合同与退费操作手册")
    assert ratio > 0
    assert _title_overlap("退费多久到账？", "家长常见540问") == 0


def test_title_boost_skips_faq_and_scores_specific_document():
    cands = [
        {"title": "家长常见540问", "rerank_score": 0.9, "similarity": 0.8},
        {"title": "C3 合同与退费操作手册", "rerank_score": 0.8, "similarity": 0.7},
    ]
    _apply_title_boost(cands, "退费多久到账？", 0.12)
    assert cands[0].get("title_boost") is None
    assert cands[1]["title_boost"] > 0
    assert _effective_score(cands[1]) > 0.8


def test_faq_demoted_only_on_close_tie():
    faq = {"title": "家长常见540问", "rerank_score": 0.90}
    specific = {"title": "C3 合同与退费操作手册", "rerank_score": 0.895}
    out = _demote_faq_on_tie([faq, specific], 0.01)
    assert out[0] is specific

    faq2 = {"title": "家长常见540问", "rerank_score": 0.90}
    specific2 = {"title": "C3 合同与退费操作手册", "rerank_score": 0.70}
    out2 = _demote_faq_on_tie([faq2, specific2], 0.01)
    assert out2[0] is faq2
