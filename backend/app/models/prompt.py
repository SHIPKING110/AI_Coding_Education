import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User


class PromptScope(enum.StrEnum):
    SYSTEM = "system"       # 系统内置默认模板（所有用户可见，仅管理员可编辑/删除）
    PERSONAL = "personal"   # 个人自定义模板（仅创建者可见，账号隔离）
    PUBLISHED = "published"  # 管理员发布（所有教师可见，仅管理员可编辑/删除）


class PromptTemplate(Base):
    """提示词模板：用于 AI 生成/润色课堂评价等。

    三档可见性：
    - system：迁移 seed 的内置模板，所有用户可见可用
    - personal：个人自定义，仅 owner 可见/编辑/删除
    - published：管理员将模板发布为全校教师可用，仅管理员可编辑/删除
    """

    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    # 模板正文，支持占位符：{student_name} {class_name} {subject} {topic}
    # {content} {performance} {homework} {evaluation}
    content: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(
        Enum(
            PromptScope,
            native_enum=False,
            length=16,
            values_callable=lambda e: [x.value for x in e],
        ),
        default=PromptScope.PERSONAL,
        index=True,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    # 使用场景：feedback 课后反馈评价 / report 报告总结 / evaluation 学员评估
    scene: Mapped[str] = mapped_column(String(32), default="feedback", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id])


__all__ = ["PromptScope", "PromptTemplate"]
