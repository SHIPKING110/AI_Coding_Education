"""联网搜索配置 CRUD：系统级单例（管理员配置，全校共用）。

Key 只进不出：加密存储，读取接口只返回掩码。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secretbox import decrypt_secret, encrypt_secret
from app.models.search_config import PROVIDER_TAVILY, SystemSearchConfig


@dataclass
class ResolvedSearch:
    """联网搜索的生效配置（已解出明文 Key）。"""

    provider: str
    base_url: str
    api_key: str
    search_depth: str
    max_results: int
    language: str


def get_system_search(db: Session) -> SystemSearchConfig | None:
    return db.scalar(select(SystemSearchConfig).limit(1))


def upsert_system_search(
    db: Session,
    *,
    provider: str = PROVIDER_TAVILY,
    base_url: str = "",
    api_key: str | None = None,
    enabled: bool = True,
    search_depth: str = "basic",
    max_results: int = 5,
    language: str = "zh",
) -> SystemSearchConfig:
    row = get_system_search(db)
    if row is None:
        row = SystemSearchConfig()
        db.add(row)
    row.provider = provider if provider == PROVIDER_TAVILY else PROVIDER_TAVILY
    row.base_url = (base_url or "").strip().rstrip("/") or "https://api.tavily.com"
    if api_key:
        row.api_key_enc = encrypt_secret(api_key.strip())
    row.enabled = enabled
    row.search_depth = search_depth if search_depth in ("basic", "advanced", "fast") else "basic"
    row.max_results = max(1, min(int(max_results or 5), 20))
    row.language = (language or "").strip()[:16]
    db.commit()
    db.refresh(row)
    return row


def delete_system_search(db: Session) -> None:
    row = get_system_search(db)
    if row is not None:
        db.delete(row)
        db.commit()


def resolve_search(db: Session) -> ResolvedSearch | None:
    """解析生效的联网搜索配置；未配置/停用/无 Key → None（工具自动不可用）。"""
    row = get_system_search(db)
    if row is None or not row.enabled:
        return None
    key = ""
    if row.api_key_enc:
        try:
            key = decrypt_secret(row.api_key_enc) or ""
        except Exception:
            key = ""
    if not key.strip():
        return None
    return ResolvedSearch(
        provider=row.provider or PROVIDER_TAVILY,
        base_url=(row.base_url or "https://api.tavily.com").rstrip("/"),
        api_key=key.strip(),
        search_depth=row.search_depth or "basic",
        max_results=max(1, min(int(row.max_results or 5), 20)),
        language=(row.language or "").strip(),
    )


__all__ = [
    "ResolvedSearch",
    "delete_system_search",
    "get_system_search",
    "resolve_search",
    "upsert_system_search",
]
