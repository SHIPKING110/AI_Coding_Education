"""联网搜索配置（Tavily）：系统级单例，管理员配置，全校共用。

与检索模型配置（Embedding/Rerank）同款范式：
- Key 加密存储（secretbox），对外只出掩码；
- 单例表：搜索服务的账号/额度是共享资产，不需要按教师拆分；
- 未配置或停用 → 联网搜索工具不可用，Agent 自动跳过（不报错、不影响正常对话）。

provider 预留扩展（当前仅 tavily）：
- tavily：https://api.tavily.com/search（POST，Bearer 鉴权）
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PROVIDER_TAVILY = "tavily"


class SystemSearchConfig(Base):
    """系统级联网搜索配置（单例）：决定 Agent 能否联网，以及搜什么。"""

    __tablename__ = "system_search_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(16), default=PROVIDER_TAVILY)
    base_url: Mapped[str] = mapped_column(String(256), default="https://api.tavily.com")
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 搜索深度：basic=1 credit/次，advanced=2 credit/次（更高精度）
    search_depth: Mapped[str] = mapped_column(String(16), default="basic")
    # 单次返回条数上限（Tavily max_results，默认 10）
    max_results: Mapped[int] = mapped_column(default=5)
    # 语言偏好（ISO 639-1，如 zh/en）；空表示不限定
    language: Mapped[str] = mapped_column(String(16), default="zh")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["PROVIDER_TAVILY", "SystemSearchConfig"]
