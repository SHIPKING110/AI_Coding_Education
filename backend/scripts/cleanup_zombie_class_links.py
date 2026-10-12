"""僵尸学员清理：删除已归档学员残留的班级关联（student_classes）。

背景：历史归档学员（如被删时仍有余额的）在班级详情里阴魂不散，
导致退班/调班/删班全部失败。本脚本只删关联行，不动学员与账目。

用法（backend 容器内）：
    .venv/bin/python scripts/cleanup_zombie_class_links.py --list
    .venv/bin/python scripts/cleanup_zombie_class_links.py --apply [--class he_python_1班]
"""

from __future__ import annotations

import argparse
import sys
import uuid

sys.path.insert(0, ".")

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.enrollment import Class, Student, StudentClass  # noqa: E402
from app.models.schedule import AttendanceStatus  # noqa: E402  # noqa: F401 (ensure models registered)


def find_zombie_links(db, class_name: str | None):
    stmt = (
        select(StudentClass, Student, Class)
        .join(Student, Student.id == StudentClass.student_id)
        .join(Class, Class.id == StudentClass.class_id)
        .where(Student.status == "archived")
    )
    if class_name:
        stmt = stmt.where(Class.name == class_name)
    return list(db.execute(stmt).all())


def main() -> int:
    ap = argparse.ArgumentParser(description="清理已归档学员的残留班级关联")
    ap.add_argument("--list", action="store_true", help="只列出，不删除")
    ap.add_argument("--apply", action="store_true", help="执行删除关联行")
    ap.add_argument("--class", dest="class_name", default=None, help="仅处理指定班级名")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = find_zombie_links(db, args.class_name)
        if not rows:
            print("没有发现已归档学员的残留班级关联，无需处理。")
            return 0
        print(f"发现 {len(rows)} 条僵尸关联：")
        for link, stu, cls in rows:
            print(
                f"  学员 {stu.name}（{stu.phone}，余额 {stu.lesson_balance}，{stu.status}）"
                f" <-> 班级 {cls.name}（{cls.status}）"
            )
        if not args.apply:
            print("试运行结束，未删除任何数据；确认后加 --apply 执行。")
            return 0
        n = 0
        for link, _stu, _cls in rows:
            db.execute(
                delete(StudentClass).where(
                    StudentClass.student_id == link.student_id,
                    StudentClass.class_id == link.class_id,
                )
            )
            n += 1
        db.commit()
        print(f"已删除 {n} 条僵尸关联。学员档案与课时/订单数据保留。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
