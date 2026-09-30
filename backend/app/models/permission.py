"""教师操作权限：管理员可按教师逐项开关；无记录视为默认值。

权限键（PERMISSION_KEYS），按模块分组：
- 学员管理：student_create（新增）、student_edit（编辑基本信息）、
  student_records（查看课时流水）、student_adjust（调课时）、
  student_refund（续费/退费）、student_stop（停课/恢复/跟进）、
  student_delete（删除归档）、class_unenroll（调整学员班级 / 退班）
- 班级管理：class_view（查看详情）、class_create（新建）、
  class_edit（编辑，仅本人所带，硬性规则）、class_delete（删除，仅本人所带空班，硬性规则）
- 教师管理：teacher_add（新增）、teacher_view（查看）、teacher_edit（编辑）、teacher_delete（删除）
- 排课与考勤：schedule_create（新建排课）
- 课时包：package_create（新建）、package_off（下架）
- 订单管理：order_visible（可见；教师默认不可见）
- 导航可见：nav_students/nav_classes/nav_teachers/nav_schedules/nav_packages/
  nav_feedbacks/nav_reports/nav_evaluations/nav_agents/nav_assignments
  （教师端侧边栏显隐；默认全部可见，保持现有行为）

硬性规则（即使权限全开也不突破）：
- 教师只能增删改「本人所带」的班级；
- 只有空班级（无在册学员）才能删除。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base
from app.models.user import User

# 权限键 → 中文说明（供管理端展示）
PERMISSION_KEYS: dict[str, str] = {
    "student_create": "学员管理-新增学员",
    "student_edit": "学员管理-编辑",
    "student_records": "学员管理-流水查看",
    "student_adjust": "学员管理-调课时",
    "student_refund": "学员管理-退费/续费",
    "student_stop": "学员管理-停课/跟进",
    "student_delete": "学员管理-删除",
    "class_unenroll": "班级管理-退班/调班",
    "class_view": "班级管理-查看详情",
    "class_create": "班级管理-新建班级",
    "class_edit": "班级管理-编辑班级（仅本人所带）",
    "class_delete": "班级管理-删除班级（仅本人所带空班）",
    "teacher_add": "教师管理-新增教师",
    "teacher_view": "教师管理-查看详情",
    "teacher_edit": "教师管理-编辑",
    "teacher_delete": "教师管理-删除",
    "schedule_create": "排课与考勤-查看与新建排课",
    "package_create": "课时包-新建课时包",
    "package_off": "课时包-下架",
    "order_visible": "订单管理-可见",
    "settings_manage": "设置模块-可见与管理",
    "finance_view": "财务管理-可见",
    "nav_students": "导航可见-学员管理",
    "nav_classes": "导航可见-班级管理",
    "nav_teachers": "导航可见-教师管理",
    "nav_schedules": "导航可见-排课与考勤",
    "nav_packages": "导航可见-课时包管理",
    "nav_feedbacks": "导航可见-课后反馈",
    "nav_reports": "导航可见-报告·总结",
    "nav_evaluations": "导航可见-学员评估",
    "nav_agents": "导航可见-Agent工作台",
    "nav_assignments": "导航可见-AI习题",
}

# 各键默认值（无记录时生效；默认 = 现有行为，避免升级后权限放大）
KEY_DEFAULTS: dict[str, bool] = {
    "student_create": True,
    "student_edit": True,
    "student_records": True,
    "student_adjust": True,
    "student_refund": True,
    "student_stop": True,
    "student_delete": False,
    "class_unenroll": True,
    "class_view": True,
    "class_create": True,
    "class_edit": True,
    "class_delete": True,
    "teacher_add": False,
    "teacher_view": True,
    "teacher_edit": False,
    "teacher_delete": False,
    "schedule_create": True,
    "package_create": False,
    "package_off": False,
    "order_visible": False,
    "settings_manage": False,
    "finance_view": False,
    "nav_students": True,
    "nav_classes": True,
    "nav_teachers": True,
    "nav_schedules": True,
    "nav_packages": True,
    "nav_feedbacks": True,
    "nav_reports": True,
    "nav_evaluations": True,
    "nav_agents": True,
    "nav_assignments": True,
}


class TeacherPermission(Base):
    __tablename__ = "teacher_permissions"

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    student_create: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    student_edit: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    student_records: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    student_adjust: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    student_refund: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    student_stop: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    student_delete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    class_unenroll: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    class_view: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    class_create: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    class_edit: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    class_delete: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    teacher_add: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    teacher_view: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    teacher_edit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    teacher_delete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    schedule_create: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    package_create: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    package_off: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    order_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    settings_manage: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    finance_view: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    nav_students: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_classes: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_teachers: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_schedules: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_packages: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_feedbacks: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_reports: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_evaluations: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_agents: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    nav_assignments: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def get_or_create(db: Session, teacher_id: uuid.UUID) -> TeacherPermission:
    row = db.get(TeacherPermission, teacher_id)
    if row is None:
        row = TeacherPermission(teacher_id=teacher_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def effective(db: Session, user: User) -> dict[str, bool]:
    """某用户的生效权限：管理员/教务全开；教师按配置（无记录视为默认值）。"""
    if user.role != "teacher":
        return {k: True for k in PERMISSION_KEYS}
    row = db.get(TeacherPermission, user.id)
    if row is None:
        return dict(KEY_DEFAULTS)
    return {k: bool(getattr(row, k, KEY_DEFAULTS[k])) for k in PERMISSION_KEYS}


def check(db: Session, user: User, key: str) -> bool:
    return effective(db, user).get(key, False)


__all__ = [
    "KEY_DEFAULTS",
    "PERMISSION_KEYS",
    "TeacherPermission",
    "check",
    "effective",
    "get_or_create",
]
