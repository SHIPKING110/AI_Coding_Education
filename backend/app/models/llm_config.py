"""教师自配大模型（OpenAI 兼容）：一人多配置 + 按模块选模型。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 需要用模型的业务模块（agent=Agent工作台，report=报告总结，
# evaluation=学员评估，assignment=AI习题，feedback=客户反馈；
# parent_service=旧版家长客服映射，仅作共享模型未配置时的兼容回退，前端已不再展示）
LLM_MODULES = ("agent", "report", "evaluation", "assignment", "feedback", "parent_service")


class TeacherLLMConfig(Base):
    """教师自配模型：url + key + 模型名；api_key 落库时 Fernet 加密。"""

    __tablename__ = "teacher_llm_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(256))
    api_key_enc: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(128))
    # embedding 专用模型（留空则用 model 同源；部分厂商如 DeepSeek 无 embedding 接口，需另配）
    embed_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class SystemParentLLMConfig(Base):
    """家长客服共享对话模型（管理员配置，全校共用）：指向某个管理员的 TeacherLLMConfig。

    为空时回退到环境变量/教师映射（兼容旧部署）。
    """

    __tablename__ = "system_parent_llm_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teacher_llm_configs.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TeacherModuleModel(Base):
    """教师按模块选模型：module -> config；无记录时用该教师默认配置。"""

    __tablename__ = "teacher_module_models"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    module: Mapped[str] = mapped_column(String(32), primary_key=True)
    config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teacher_llm_configs.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
