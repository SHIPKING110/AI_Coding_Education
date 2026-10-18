"""检索模型配置 CRUD：系统级 Embedding（单例）+ 教师级 Rerank。

resolved 对象与对话模型的 ResolvedLLM 分离，避免误用（embedding/rerank 的
endpoint 与 schema 都不是 chat 兼容的）。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.secretbox import decrypt_secret, encrypt_secret
from app.models.retrieval_config import (
    PROVIDER_LOCAL,
    PROVIDER_REMOTE,
    SystemEmbeddingConfig,
    TeacherRerankConfig,
)


@dataclass
class ResolvedEmbedding:
    provider: str
    base_url: str
    api_key: str | None
    model: str
    model_path: str | None

    def fingerprint(self) -> str:
        """集合分片指纹：provider+模型+地址 决定向量空间，必须能区分不同 embedding。"""
        raw = f"{self.provider}|{self.model}|{(self.base_url or '').rstrip('/')}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class ResolvedRerank:
    provider: str
    base_url: str
    api_key: str | None
    model: str
    model_path: str | None


def _norm_base_url(url: str) -> str:
    base = (url or "").strip().rstrip("/")
    if base and not base.endswith("/v1") and not base.endswith("/api/v1"):
        base += "/v1"
    return base


# ---------------- 系统级 Embedding（单例） ----------------


def get_system_embedding(db: Session) -> SystemEmbeddingConfig | None:
    return db.scalar(select(SystemEmbeddingConfig).limit(1))


def upsert_system_embedding(
    db: Session,
    *,
    provider: str,
    base_url: str,
    api_key: str | None,
    model: str,
    model_path: str | None = None,
    enabled: bool = True,
) -> SystemEmbeddingConfig:
    row = get_system_embedding(db)
    if row is None:
        row = SystemEmbeddingConfig()
        db.add(row)
    row.provider = provider if provider in (PROVIDER_REMOTE, PROVIDER_LOCAL) else PROVIDER_REMOTE
    row.base_url = (base_url or "").strip().rstrip("/")
    if api_key:
        row.api_key_enc = encrypt_secret(api_key.strip())
    row.model = (model or "").strip()
    row.model_path = (model_path or "").strip() or None
    row.enabled = enabled
    db.commit()
    db.refresh(row)
    return row


def delete_system_embedding(db: Session) -> None:
    row = get_system_embedding(db)
    if row is not None:
        db.delete(row)
        db.commit()


def resolve_embedding(db: Session) -> ResolvedEmbedding | None:
    """解析系统级 embedding；未配置则回退全局 env（LLM_EMBED_MODEL 等）。"""
    from app.core.config import get_settings

    row = get_system_embedding(db)
    if row is not None and row.enabled and (row.model or "").strip():
        if row.provider == PROVIDER_LOCAL:
            if not (row.model_path or "").strip():
                return None
            return ResolvedEmbedding(
                provider=row.provider,
                base_url=row.base_url or "",
                api_key=None,
                model=row.model,
                model_path=row.model_path,
            )
        key = decrypt_secret(row.api_key_enc) if row.api_key_enc else ""
        if not key:
            return None
        return ResolvedEmbedding(
            provider=row.provider,
            base_url=row.base_url or "",
            api_key=key,
            model=row.model,
            model_path=row.model_path,
        )
    # 回退：全局环境变量（保持既有部署可用）
    settings = get_settings()
    model = (settings.LLM_EMBED_MODEL or "").strip()
    api_key = (settings.LLM_API_KEY or "").strip()
    if model and api_key:
        return ResolvedEmbedding(
            provider=PROVIDER_REMOTE,
            base_url=(settings.LLM_BASE_URL or "").strip().rstrip("/"),
            api_key=api_key,
            model=model,
            model_path=None,
        )
    return None


# ---------------- 教师级 Rerank（可选） ----------------


def get_rerank(db: Session, owner_id: uuid.UUID) -> TeacherRerankConfig | None:
    return db.scalars(
        select(TeacherRerankConfig).where(TeacherRerankConfig.owner_id == owner_id).limit(1)
    ).first()


def upsert_rerank(
    db: Session,
    *,
    owner_id: uuid.UUID,
    provider: str,
    base_url: str,
    api_key: str | None,
    model: str,
    model_path: str | None = None,
    enabled: bool = True,
) -> TeacherRerankConfig:
    row = get_rerank(db, owner_id)
    if row is None:
        row = TeacherRerankConfig(owner_id=owner_id)
        db.add(row)
    row.provider = provider if provider in (PROVIDER_REMOTE, PROVIDER_LOCAL) else PROVIDER_REMOTE
    row.base_url = (base_url or "").strip().rstrip("/")
    if api_key:
        row.api_key_enc = encrypt_secret(api_key.strip())
    row.model = (model or "").strip()
    row.model_path = (model_path or "").strip() or None
    row.enabled = enabled
    db.commit()
    db.refresh(row)
    return row


def delete_rerank(db: Session, owner_id: uuid.UUID) -> None:
    db.execute(delete(TeacherRerankConfig).where(TeacherRerankConfig.owner_id == owner_id))
    db.commit()


def resolve_rerank(db: Session, owner_id: uuid.UUID) -> ResolvedRerank | None:
    """未配置 / 停用 / 密钥缺失 → None（检索退化为单层向量召回）。"""
    row = get_rerank(db, owner_id)
    if row is None or not row.enabled or not (row.model or "").strip():
        return None
    if row.provider == PROVIDER_LOCAL:
        if not (row.model_path or "").strip():
            return None
        return ResolvedRerank(row.provider, "", None, row.model, row.model_path)
    key = decrypt_secret(row.api_key_enc) if row.api_key_enc else ""
    if not key or not (row.base_url or "").strip():
        return None
    return ResolvedRerank(row.provider, row.base_url, key, row.model, row.model_path)


__all__ = [
    "ResolvedEmbedding",
    "ResolvedRerank",
    "delete_rerank",
    "delete_system_embedding",
    "get_rerank",
    "get_system_embedding",
    "resolve_embedding",
    "resolve_rerank",
    "upsert_rerank",
    "upsert_system_embedding",
]