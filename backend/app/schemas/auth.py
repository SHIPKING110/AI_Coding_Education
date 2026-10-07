import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import Role


class RegisterIn(BaseModel):
    role: Role = Field(default=Role.PARENT)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    campus: str | None = Field(
        default=None, max_length=64, description="所属校区（如 一校/二校/三校）"
    )
    title: str | None = Field(default=None, max_length=64, description="职务标签（如 主教/助教）")


class LoginIn(BaseModel):
    username: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    role: Role
    username: str
    name: str
    phone: str | None
    gender: str | None = None
    campus: str | None = None
    title: str | None = None
    teacher_level_id: str | None = None
    teacher_level_name: str | None = None
    base_salary: str | None = None
    status: str
    created_at: datetime

    @field_validator("base_salary", mode="before")
    @classmethod
    def _stringify_salary(cls, v):
        return None if v is None else str(v)

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    """教师账号编辑（admin/staff）。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    gender: str | None = Field(default=None, max_length=16, description="性别：male/female/空")
    campus: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=64, description="职务标签；变更时自动套用该职务预设权限")
    teacher_level_id: str | None = Field(default=None, description="教师级别id")
    base_salary: str | None = Field(default=None, description="基本工资，为空取职务工资")
    password: str | None = Field(default=None, min_length=6, max_length=128)
    status: str | None = None


class UserSelfUpdate(BaseModel):
    """个人信息修改（本人）。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    campus: str | None = Field(default=None, max_length=64)


class ChangePasswordIn(BaseModel):
    """本人修改密码：校验原密码后设置新密码。"""

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class AdminPasswordResetIn(BaseModel):
    """管理员重置他人账号密码（家长/学员/教师等）。"""

    new_password: str = Field(min_length=6, max_length=128)
