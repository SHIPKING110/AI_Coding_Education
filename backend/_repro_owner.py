"""临时排查：3d0bdefd... 这个作业 404 —— 是否已被删除？通知还指着它。"""

import uuid as uuid_mod

from app.core.database import SessionLocal
from app.models.assignment import Assignment
from app.models.notification import Notification, NotificationType

db = SessionLocal()
try:
    aid = "3d0bdefd-dfab-4b56-95ad-00d76f87489b"
    a = db.get(Assignment, uuid_mod.UUID(aid))
    notis = (
        db.query(Notification)
        .filter(Notification.type == NotificationType.SUBMISSION_SUBMITTED.value)
        .order_by(Notification.created_at.desc())
        .all()
    )
    lines = [f"assignment {aid} exists: {a is not None}"]
    lines.append(f"total submitted-notifications: {len(notis)}")
    missing = 0
    for n in notis:
        d = n.data or {}
        x = d.get("assignment_id")
        exists = db.get(Assignment, uuid_mod.UUID(x)) is not None if x else False
        if not exists:
            missing += 1
            lines.append(
                f"STALE -> noti {n.created_at} assignment_id={x} "
                f"content={n.content[:50]} read_at={n.read_at}"
            )
    lines.append(f"stale notifications: {missing}")
    with open("_repro_out.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("done")
finally:
    db.close()
