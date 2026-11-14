"""家长客服会话留存清理（分级保留，幂等可重跑）。

用法（容器内）：
    docker compose exec backend python scripts/cleanup_parent_threads.py [--dry-run]

策略：
- 匿名会话（parent_id 为空）7 天无活动 → 删除全部消息（保留会话行做统计）
- closed 会话 90 天 → 删除会话（含消息级联）
- escalated 会话 180 天 → 删除会话（含消息级联）
- open 且登录家长的会话：不清（体验连续性）

挂 cron 示例（每周日凌晨 3 点）：
    0 3 * * 0 docker compose -f /srv/app/docker-compose.yml exec -T backend python scripts/cleanup_parent_threads.py
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.parent_service import (  # noqa: E402
    THREAD_CLOSED,
    THREAD_ESCALATED,
    ParentServiceMessage,
    ParentServiceThread,
)

ANON_DAYS = 7
CLOSED_DAYS = 90
ESCALATED_DAYS = 180


def main() -> None:
    ap = argparse.ArgumentParser(description="家长客服会话分级清理")
    ap.add_argument("--dry-run", action="store_true", help="只统计不删除")
    ap.add_argument("--anon-days", type=int, default=ANON_DAYS)
    ap.add_argument("--closed-days", type=int, default=CLOSED_DAYS)
    ap.add_argument("--escalated-days", type=int, default=ESCALATED_DAYS)
    args = ap.parse_args()

    now = datetime.now()
    db = SessionLocal()
    try:
        # 1) 匿名：删消息内容，留会话壳
        anon_cut = now - timedelta(days=args.anon_days)
        anon_ids = list(db.scalars(
            select(ParentServiceThread.id).where(
                ParentServiceThread.parent_id.is_(None),
                ParentServiceThread.updated_at < anon_cut,
            )
        ).all())
        anon_msgs = 0
        if anon_ids:
            from sqlalchemy import func as _func

            anon_msgs = db.scalar(
                select(_func.count(ParentServiceMessage.id)).where(
                    ParentServiceMessage.thread_id.in_(anon_ids)
                )
            ) or 0
            if not args.dry_run:
                db.execute(
                    delete(ParentServiceMessage).where(ParentServiceMessage.thread_id.in_(anon_ids))
                )
                db.commit()

        # 2) closed / escalated：整会话删除（消息 CASCADE）
        def _expired(status: str, days: int):
            cut = now - timedelta(days=days)
            return list(db.scalars(
                select(ParentServiceThread.id).where(
                    ParentServiceThread.status == status,
                    ParentServiceThread.updated_at < cut,
                )
            ).all())

        closed_ids = _expired(THREAD_CLOSED, args.closed_days)
        esc_ids = _expired(THREAD_ESCALATED, args.escalated_days)
        gone = 0
        if not args.dry_run:
            for tid in closed_ids + esc_ids:
                th = db.get(ParentServiceThread, tid)
                if th is not None:
                    db.delete(th)
                    gone += 1
            db.commit()
        else:
            gone = len(closed_ids) + len(esc_ids)

        print(
            f"{'DRY-RUN ' if args.dry_run else ''}anon_threads={len(anon_ids)} anon_msgs_cleared~{anon_msgs} "
            f"closed_deleted={len(closed_ids)} escalated_deleted={len(esc_ids)} applied={gone if not args.dry_run else 0}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
