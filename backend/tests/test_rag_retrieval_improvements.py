"""P2 检索优化：RRF 融合、父子切分、路由参数覆盖、Query 改写。"""

import time
import uuid

from app.services import rag, rag_settings


def test_build_parent_texts_groups_children():
    chunks = ["a" * 10, "b" * 10, "c" * 10]
    parents = rag._build_parent_texts(chunks, 25)
    assert len(parents) == 3
    assert parents[0] == parents[1]  # 前两个子块聚合为同一父块
    assert "a" in parents[0] and "b" in parents[0]
    assert parents[2] == "c" * 10


def test_rrf_merge_prefers_doc_in_both_lists():
    v = [{"doc_id": "a", "text": "a", "title": "A"}, {"doc_id": "b", "text": "b", "title": "B"}]
    k = [{"doc_id": "b", "text": "b", "title": "B"}, {"doc_id": "c", "text": "c", "title": "C"}]
    out = rag._rrf_merge(v, k)
    assert out[0]["doc_id"] == "b"
    assert {x["doc_id"] for x in out} == {"a", "b", "c"}


def test_rewrite_query_only_when_enabled():
    q, changed = rag._rewrite_query("退费怎么算", {"query_rewrite_enabled": False})
    assert q == "退费怎么算" and changed is False
    q2, changed2 = rag._rewrite_query("退费怎么算", {"query_rewrite_enabled": True})
    assert changed2 is True
    assert "退款" in q2


class _FakeCollection:
    def __init__(self, docs, metas, dists):
        self._docs, self._metas, self._dists = docs, metas, dists

    def query(self, **_kwargs):
        return {"documents": [self._docs], "metadatas": [self._metas], "distances": [self._dists]}


def _set_cfg(monkeypatch, **overrides):
    cfg = {**rag_settings.DEFAULTS, **overrides}
    monkeypatch.setattr(rag_settings, "_cache", (time.time(), cfg), raising=False)
    return cfg


def test_retrieve_applies_route_override_and_parent_context(monkeypatch):
    _set_cfg(
        monkeypatch,
        route_overrides={"agent_teacher": {"top_k": 1}},
        parent_chunk_size=100,
    )
    docs = ["子块一", "子块二", "子块三"]
    metas = [
        {"doc_id": "d1", "title": "文档一", "parent_text": "父块上下文一"},
        {"doc_id": "d2", "title": "文档二"},
        {"doc_id": "d3", "title": "文档三"},
    ]
    monkeypatch.setattr(rag, "get_collection", lambda: _FakeCollection(docs, metas, [0.1, 0.2, 0.3]))
    monkeypatch.setattr(rag, "embed_texts", lambda texts: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr("app.crud.knowledge.usable_doc_ids", lambda db, doc_ids: set(doc_ids))
    monkeypatch.setattr(rag, "_apply_rerank", lambda q, cands, db, owner: (cands, {"rerank": False}))

    diag: dict = {}
    out = rag.retrieve(
        "家长政策", db=object(), owner_id=uuid.uuid4(), top_k=None,
        rerank=False, diag=diag, route_key="agent_teacher",
    )
    assert len(out) == 1, "路由覆盖 top_k=1 应生效"
    assert out[0]["doc_id"] == "d1"
    assert out[0]["text"] == "父块上下文一"
    assert out[0]["child_text"] == "子块一"
    assert diag.get("retrieval_mode") == "dense"


def test_retrieval_mode_labels():
    assert rag._compute_retrieval_mode({"error": "boom"}) == "error"
    assert rag._compute_retrieval_mode({"vector": True, "hybrid": True}) == "hybrid"
    assert rag._compute_retrieval_mode({"vector": True}) == "dense"
    assert rag._compute_retrieval_mode({"vector": True, "multi_query": True}) == "dense_multi"
    assert rag._compute_retrieval_mode({"keyword": True}) == "keyword_fallback"
    assert rag._compute_retrieval_mode({}) == "none"


def _fake_retrieval_env(monkeypatch, dists=(0.1,)):
    docs = ["内容一"] * len(dists)
    metas = [{"doc_id": f"d{i}", "title": "文档一"} for i in range(len(dists))]
    monkeypatch.setattr(rag, "get_collection", lambda: _FakeCollection(docs, metas, list(dists)))
    monkeypatch.setattr(rag, "embed_texts", lambda texts: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr("app.crud.knowledge.usable_doc_ids", lambda db, doc_ids: set(doc_ids))
    kw = [{"text": "内容一", "title": "文档一", "doc_id": "d0", "similarity": 0.5}]
    monkeypatch.setattr(rag, "_keyword_search", lambda q, **kwargs: kw)


def test_hybrid_override_forces_hybrid_even_if_config_off(monkeypatch):
    _set_cfg(monkeypatch, hybrid_enabled=False, route_overrides={})
    _fake_retrieval_env(monkeypatch)
    diag: dict = {}
    out = rag.retrieve(
        "家长政策", db=object(), owner_id=uuid.uuid4(), rerank=False,
        diag=diag, hybrid_override=True,
    )
    assert diag.get("hybrid") is True
    assert diag.get("retrieval_mode") == "hybrid"
    assert out and out[0]["doc_id"] == "d0"


def test_route_override_can_enable_hybrid_per_route(monkeypatch):
    _set_cfg(monkeypatch, hybrid_enabled=False, route_overrides={"eval": {"hybrid_enabled": True}})
    _fake_retrieval_env(monkeypatch)
    diag: dict = {}
    rag.retrieve(
        "家长政策", db=object(), owner_id=uuid.uuid4(), rerank=False,
        diag=diag, route_key="eval",
    )
    assert diag.get("hybrid") is True
    # 其他路由不受影响：eval 路由的覆盖不应泄漏到生产路由
    diag2: dict = {}
    rag.retrieve(
        "家长政策", db=object(), owner_id=uuid.uuid4(), rerank=False,
        diag=diag2, route_key="agent_teacher",
    )
    assert diag2.get("hybrid") is not True
    assert diag2.get("retrieval_mode") == "dense"


def test_hybrid_mode_uses_keyword_when_vector_empty(monkeypatch):
    _set_cfg(monkeypatch, hybrid_enabled=True, route_overrides={})
    _fake_retrieval_env(monkeypatch, dists=())
    diag: dict = {}
    out = rag.retrieve(
        "家长政策", db=object(), owner_id=uuid.uuid4(), rerank=False, diag=diag,
    )
    assert out and out[0]["doc_id"] == "d0"
    assert diag.get("retrieval_mode") == "hybrid", "Hybrid 模式下向量空但关键词命中，仍属 hybrid 架构而非降级兜底"
