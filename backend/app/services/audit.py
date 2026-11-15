"""审计写入服务。

使用约定：
- 在业务 db.commit() 之后调用（record 默认自带 commit=True）；
- record 内部吞掉一切异常，审计失败只记日志、绝不阻断业务；
- before/after 会做敏感字段脱敏（password/api_key/token 等一律 `***`），
  长字符串截断，避免把密钥/大文本写进审计表。
"""

import json
import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

_SENSITIVE_KEYWORDS = ("password", "secret", "api_key", "apikey", "token", "credential", "private_key")
_MAX_STR = 500


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {
            k: ("***" if any(w in str(k).lower() for w in _SENSITIVE_KEYWORDS) else _sanitize(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in value][:50]
    if isinstance(value, str):
        return value[:_MAX_STR] + ("…" if len(value) > _MAX_STR else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_STR]


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    return (
        (request.headers.get("x-real-ip") or "").strip()
        or (request.client.host if request.client else None)
    )


def record(
    db: Session,
    actor: User | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> None:
    """写一条审计日志（失败不抛异常）。调用方应已提交自身业务事务。"""
    try:
        row = AuditLog(
            actor_id=actor.id if actor is not None else None,
            actor_name=actor.name if actor is not None else None,
            actor_role=actor.role if actor is not None else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            before=_sanitize(before) if before is not None else None,
            after=_sanitize(after) if after is not None else None,
            ip=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:256] if request else None,
        )
        db.add(row)
        if commit:
            db.commit()
    except Exception:  # noqa: BLE001 —— 审计失败绝不阻断业务
        logger.exception("审计日志写入失败：action=%s target=%s", action, target_id)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def diff(before: dict | None, after: dict | None) -> dict:
    """只保留发生变化的键（用于设置/权限类更新的审计快照）。"""
    before = before or {}
    after = after or {}
    changed = {k: v for k, v in after.items() if before.get(k) != v}
    return json.loads(json.dumps(changed, ensure_ascii=False, default=str))
