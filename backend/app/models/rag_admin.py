"""RAG 运营后台持久化模型：检索台账 / 参数版本 / 审计 / 评测。

设计目标：
- 检索 trace 是“可溯源”的唯一台账，记录每次真实检索的路由、候选、门控、重排与耗时；
- 配置版本化，任何参数调整可回滚、可审计；
- 评测集与运行结果落库，优化决策有数据依据。

注意：trace 只存分片预览（截断），不重复存储整篇文档，控制表体积。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RagRetrievalTrace(Base):
    """一次真实检索的完整链路台账。"""

    __tablename__ = "rag_retrieval_traces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(32), default="", index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    route: Mapped[str] = mapped_column(String(64), default="", index=True)

    query: Mapped[str] = mapped_column(Text, default="")
    rewritten_query: Mapped[str] = mapped_column(Text, default="")
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding_fingerprint: Mapped[str] = mapped_column(String(128), default="")

    vector_candidates: Mapped[int] = mapped_column(Integer, default=0)
    keyword_candidates: Mapped[int] = mapped_column(Integer, default=0)
    rerank_candidates: Mapped[int] = mapped_column(Integer, default=0)
    gated_out: Mapped[int] = mapped_column(Integer, default=0)

    vector_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    keyword_used: Mapped[bool] = mapped_column(Boolean, default=False)
    rerank_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    rerank_model: Mapped[str] = mapped_column(String(128), default="")

    zero_result: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    stage_timings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RagConfigVersion(Base):
    """RAG 参数版本：每次更新生成一条快照，支持回滚。"""

    __tablename__ = "rag_config_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RagAdminAudit(Base):
    """后台操作审计：配置、重建、删除、清理、评测运行。"""

    __tablename__ = "rag_admin_audit"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RagEvalSet(Base):
    """评测集：一组 query + 标注。"""

    __tablename__ = "rag_eval_sets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(32), default="agent_teacher")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RagEvalCase(Base):
    """评测用例：relevant 用文档标题或 doc_id 标注。"""

    __tablename__ = "rag_eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_eval_sets.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    relevant: Mapped[list | None] = mapped_column(JSON, nullable=True)
    gt_answer: Mapped[str] = mapped_column(Text, default="")
    gt_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    query_type: Mapped[str] = mapped_column(String(32), default="fact")
    difficulty: Mapped[str] = mapped_column(String(16), default="normal")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RagEvalRun(Base):
    """一次评测运行：同时跑 rerank=off / on，保存两套指标与对比。"""

    __tablename__ = "rag_eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_eval_sets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    rerank: Mapped[bool] = mapped_column(Boolean, default=True)
    answer_eval: Mapped[bool] = mapped_column(Boolean, default=False)
    config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    compare: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RagEvalResult(Base):
    """单条评测结果：逐 case 的 ranked / 命中 / 诊断 / Bad Case 分类。"""

    __tablename__ = "rag_eval_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_eval_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    ranked: Mapped[list | None] = mapped_column(JSON, nullable=True)
    relevant: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retrieval_summary: Mapped[str] = mapped_column(Text, default="")
    bad_case_type: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "RagRetrievalTrace",
    "RagConfigVersion",
    "RagAdminAudit",
    "RagEvalSet",
    "RagEvalCase",
    "RagEvalRun",
    "RagEvalResult",
]
