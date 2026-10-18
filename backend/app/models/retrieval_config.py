"""检索模型配置：Embedding（系统级，全校共用一套）+ Rerank（教师级，可选）。

与对话模型（TeacherLLMConfig）彻底解耦：
- 对话模型按「模块」选用，变更频繁、作用域=教师；
- Embedding 是「索引期资产」：决定向量空间，必须全校统一，否则同一集合混入
  不同向量空间会跨教师串味、维度不同会直接查询失败。故收敛为系统级单例。
- Rerank 是「查询期无状态」：可安全地按教师自选，未配置即退化为单层向量检索。

provider 预留本地模型接口：
- remote：Claude 兼容 embedding / rerank（多数云厂商）
- local ：本地 sentence-transformers / ollama / vllm（预留，后续接入不改表结构）
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# provider 类型：remote=云端 API，local=本地模型（预留）
PROVIDER_REMOTE = "remote"
PROVIDER_LOCAL = "local"


class SystemEmbeddingConfig(Base):
    """系统级 Embedding 配置（单例）：全校共用，决定向量空间与索引集合。

    embedding 模型一旦更换，指纹变化 → 自动落到新集合（旧集合数据不丢，
    可离线清理/重建），避免新旧向量混存。
    """

    __tablename__ = "system_embedding_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(16), default=PROVIDER_REMOTE)
    base_url: Mapped[str] = mapped_column(String(256), default="")
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    # 本地模型预留：model_path 指向本地权重目录（local provider 使用）
    model_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TeacherRerankConfig(Base):
    """教师级 Rerank 配置（可选，每教师最多一条）：用于查询期重排提升精准率。

    未配置 / 未启用 → 检索退化为单层向量召回（行为与现状一致）。
    """

    __tablename__ = "teacher_rerank_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16), default=PROVIDER_REMOTE)
    base_url: Mapped[str] = mapped_column(String(256), default="")
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    # 本地模型预留
    model_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "PROVIDER_LOCAL",
    "PROVIDER_REMOTE",
    "SystemEmbeddingConfig",
    "TeacherRerankConfig",
]