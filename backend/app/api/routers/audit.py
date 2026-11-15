"""审计日志查询（仅管理员）：按动作/操作者/时间筛选，分页返回。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User

router = APIRouter(prefix="/audit", tags=["audit"])


def _out(row: AuditLog) -> dict:
    return {
        "id": str(row.id),
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "actor_name": row.actor_name,
        "actor_role": row.actor_role,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "before": row.before,
        "after": row.after,
        "ip": row.ip,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/logs")
def list_audit_logs(
    action: str | None = Query(default=None, description="动作前缀，如 user. / permissions."),
    actor_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at <= end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return {"items": [_out(r) for r in rows], "total": total, "limit": limit, "offset": offset}
