import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PromptTemplateCreate(BaseModel):
    """新建提示词模板（个人自定义；管理员可创建后发布）。"""

    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)


class PromptTemplateUpdate(BaseModel):
    """编辑提示词模板（个人模板仅 owner，system/published 仅管理员）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, min_length=1)


class PromptTemplateOut(BaseModel):
    """提示词模板（含可见范围信息）。"""

    id: uuid.UUID
    name: str
    content: str
    scope: str  # system | personal | published
    owner_id: uuid.UUID | None = None
    owner_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
