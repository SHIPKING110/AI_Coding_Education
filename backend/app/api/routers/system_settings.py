"""全局个性化设置：公开读（登录页需未登录读取）；写需设置权限（默认管理员）。

另提供桌面背景图 / 登录 Logo 图上传（本地磁盘存储，复用 /uploads 静态服务）。
"""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, require_teacher_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.models.system_setting import SystemSetting
from app.models.user import Role, User

router = APIRouter(prefix="/system-settings", tags=["system-settings"])
settings = get_settings()

ALLOWED_LOGIN_THEMES = ("default", "light", "dark", "poster")
ALLOWED_UI_THEMES = ("default", "fresh", "calm", "warm")

DEFAULTS = {
    "login_title": "智能少儿编程教育",
    "login_subtitle": "教务管理系统 · 教师效率提升 家长服务闭环",
    "login_logo": "",
    "login_accent": "",
    "login_hero": "排课 · 考勤 · 课时 · 反馈，一站式教务",
    "sidebar_sub": "Child Code Studio",
    "sidebar_theme": "navy",
}

ALLOWED_SIDEBAR_THEMES = ("navy", "light", "brand")


class SystemSettingUpdate(BaseModel):
    login_theme: str | None = None
    desktop_bg: str | None = None
    ui_theme: str | None = None
    login_title: str | None = None
    login_subtitle: str | None = None
    login_logo: str | None = None
    login_accent: str | None = None
    login_hero: str | None = None
    sidebar_sub: str | None = None
    sidebar_theme: str | None = None
    nav_order: list[str] | None = None
    # 家长客服配额与词表（落库可配，设置页可改）
    parent_anon_daily_limit: int | None = None
    parent_daily_limit: int | None = None
    parent_risk_words: list[str] | str | None = None
    parent_quick_replies: list[str] | str | None = None
    # 会话自动关闭阈值（小时）：open 闲置 / escalated 闲置
    parent_open_idle_hours: int | None = None
    parent_escalated_idle_hours: int | None = None


def _ensure_columns(db: Session) -> None:
    """轻量自迁移：给已存在的 system_settings 表补新增列（无 alembic 时期的过渡方案）。"""
    dialect = db.bind.dialect.name if db.bind else ""
    if dialect == "sqlite":
        cols = {c["name"] for c in db.execute(text("PRAGMA table_info(system_settings)")).all()}
    else:
        cols = {
            r[0]
            for r in db.execute(
                text("SELECT column_name FROM information_schema.columns "
                     "WHERE table_name='system_settings'")
            ).all()
        }
    ddl = {
        "login_title": "ALTER TABLE system_settings ADD COLUMN login_title VARCHAR(64)",
        "login_subtitle": "ALTER TABLE system_settings ADD COLUMN login_subtitle VARCHAR(128)",
        "login_logo": "ALTER TABLE system_settings ADD COLUMN login_logo VARCHAR(512)",
        "login_accent": "ALTER TABLE system_settings ADD COLUMN login_accent VARCHAR(32)",
        "login_hero": "ALTER TABLE system_settings ADD COLUMN login_hero VARCHAR(128)",
        "sidebar_sub": "ALTER TABLE system_settings ADD COLUMN sidebar_sub VARCHAR(64)",
        "sidebar_theme": "ALTER TABLE system_settings ADD COLUMN sidebar_theme VARCHAR(16)",
        "nav_order": "ALTER TABLE system_settings ADD COLUMN nav_order TEXT DEFAULT '[]'",
        "parent_anon_daily_limit": "ALTER TABLE system_settings ADD COLUMN parent_anon_daily_limit INTEGER DEFAULT 3",
        "parent_daily_limit": "ALTER TABLE system_settings ADD COLUMN parent_daily_limit INTEGER DEFAULT 50",
        "parent_risk_words": "ALTER TABLE system_settings ADD COLUMN parent_risk_words TEXT DEFAULT '[]'",
        "parent_quick_replies": "ALTER TABLE system_settings ADD COLUMN parent_quick_replies TEXT DEFAULT '[]'",
        "parent_open_idle_hours": "ALTER TABLE system_settings ADD COLUMN parent_open_idle_hours INTEGER DEFAULT 24",
        "parent_escalated_idle_hours": "ALTER TABLE system_settings ADD COLUMN parent_escalated_idle_hours INTEGER DEFAULT 48",
    }
    for col, sql in ddl.items():
        if col not in cols:
            db.execute(text(sql))
    db.commit()


def _get_or_create(db: Session) -> SystemSetting:
    _ensure_columns(db)
    row = db.get(SystemSetting, 1)
    if row is None:
        row = SystemSetting(id=1, **DEFAULTS)  # type: ignore[arg-type]
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _parse_str_list(raw: str | None) -> list[str]:
    try:
        arr = json.loads(raw or "[]")
        return [str(x) for x in arr] if isinstance(arr, list) else []
    except (ValueError, TypeError):
        return []


def _out(row: SystemSetting) -> dict:
    try:
        nav_order = json.loads(row.nav_order or "[]")
        if not isinstance(nav_order, list):
            nav_order = []
    except (ValueError, TypeError):
        nav_order = []
    return {
        "login_theme": row.login_theme,
        "desktop_bg": row.desktop_bg,
        "ui_theme": row.ui_theme,
        "login_title": row.login_title or DEFAULTS["login_title"],
        "login_subtitle": row.login_subtitle if row.login_subtitle is not None else DEFAULTS["login_subtitle"],
        "login_logo": row.login_logo or "",
        "login_accent": row.login_accent or "",
        "login_hero": row.login_hero or DEFAULTS["login_hero"],
        "sidebar_sub": row.sidebar_sub if row.sidebar_sub is not None else DEFAULTS["sidebar_sub"],
        "sidebar_theme": row.sidebar_theme or DEFAULTS["sidebar_theme"],
        "nav_order": nav_order,
        "parent_anon_daily_limit": int(getattr(row, "parent_anon_daily_limit", 3) or 3),
        "parent_daily_limit": int(getattr(row, "parent_daily_limit", 50) or 50),
        "parent_risk_words": _parse_str_list(getattr(row, "parent_risk_words", None)),
        "parent_quick_replies": _parse_str_list(getattr(row, "parent_quick_replies", None)),
        "parent_open_idle_hours": int(getattr(row, "parent_open_idle_hours", 24) or 24),
        "parent_escalated_idle_hours": int(getattr(row, "parent_escalated_idle_hours", 48) or 48),
    }


@router.get("")
def read_settings(db: Session = Depends(get_db)) -> dict:
    """读取全局个性化设置（公开，登录页渲染用）。"""
    return _out(_get_or_create(db))


@router.put("")
def update_settings(
    payload: SystemSettingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """更新全局个性化设置（需个性化 tab 权限或设置总管权限）。"""
    from app.models.permission import check as _check

    if user.role not in (Role.ADMIN.value, Role.STAFF.value) and not (
        _check(db, user, "settings_manage") or _check(db, user, "settings_tab_personalize")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂无个性化设置操作权限，请联系管理员开通")
    row = _get_or_create(db)
    data = payload.model_dump(exclude_unset=True)
    if "login_theme" in data and data["login_theme"] not in ALLOWED_LOGIN_THEMES:
        raise HTTPException(status_code=400, detail=f"login_theme 非法，可选：{ALLOWED_LOGIN_THEMES}")
    if "ui_theme" in data and data["ui_theme"] not in ALLOWED_UI_THEMES:
        raise HTTPException(status_code=400, detail=f"ui_theme 可选：{ALLOWED_UI_THEMES}")
    if "sidebar_theme" in data and data["sidebar_theme"] not in ALLOWED_SIDEBAR_THEMES:
        raise HTTPException(
            status_code=400, detail=f"sidebar_theme 可选：{ALLOWED_SIDEBAR_THEMES}"
        )
    for k, v in data.items():
        if v is None:
            continue
        if k in ("parent_anon_daily_limit", "parent_daily_limit"):
            iv = int(v)
            if iv < 0 or iv > 1000:
                raise HTTPException(status_code=400, detail=f"{k} 需在 0~1000 之间")
            setattr(row, k, iv)
        elif k in ("parent_open_idle_hours", "parent_escalated_idle_hours"):
            iv = int(v)
            if iv < 1 or iv > 720:
                raise HTTPException(status_code=400, detail=f"{k} 需在 1~720 小时之间")
            setattr(row, k, iv)
        elif k in ("parent_risk_words", "parent_quick_replies"):
            arr = v if isinstance(v, list) else [s.strip() for s in str(v).split("\n") if s.strip()]
            setattr(row, k, json.dumps(arr, ensure_ascii=False))
        else:
            setattr(row, k, json.dumps(v) if k == "nav_order" else v)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_setting_image(
    file: UploadFile = File(...),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """上传桌面背景图 / 登录 Logo 图（仅管理员，图片 ≤10MB，返回 /uploads 路径）。"""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持图片文件")
    size_limit = 10 * 1024 * 1024
    suffix = Path(file.filename or "file").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 png/jpg/webp/gif")
    fname = f"{uuid.uuid4().hex}{suffix}"
    target_dir = Path(settings.UPLOAD_DIR) / "personalize"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / fname
    written = 0
    with open(target, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > size_limit:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="文件过大，最大 10MB",
                )
            out.write(chunk)
    return {"url": f"/uploads/personalize/{fname}"}


__all__ = ["router"]
