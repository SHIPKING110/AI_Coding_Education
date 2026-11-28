"""清理题库导入来源表中的孤儿记录（无对应套卷的 question_bank_sources）。

背景：历史版本“彻底删除”套卷时未同步删除 question_bank_sources，导致 file_hash
被永久占用，重新上传同一文档会被「该文档已经导入过」误拦截。本脚本只删
孤儿 source 行，不动已有套卷及其题目、历史记录。

用法（backend 容器内）：
    .venv/bin/python scripts/cleanup_orphan_qb_sources.py --list
    .venv/bin/python scripts/cleanup_orphan_qb_sources.py --apply
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import delete, exists, not_, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.question_bank import QuestionBankSet, QuestionBankSource  # noqa: E402


def find_orphans(db) -> list[tuple]:
    stmt = (
        select(
            QuestionBankSource.id,
            QuestionBankSource.filename,
            QuestionBankSource.file_hash,
            QuestionBankSource.created_at,
        )
        .where(
            not_(exists().where(QuestionBankSet.source_id == QuestionBankSource.id))
        )
        .order_by(QuestionBankSource.created_at)
    )
    return list(db.execute(stmt).all())


def main() -> int:
    ap = argparse.ArgumentParser(description="清理题库导入来源表中的孤儿记录（释放 file_hash）")
    ap.add_argument("--list", action="store_true", help="只列出，不删除")
    ap.add_argument("--apply", action="store_true", help="执行删除孤儿 source 行")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = find_orphans(db)
        if not rows:
            print("没有发现孤儿的题库导入来源记录，无需处理。")
            return 0
        print(f"发现 {len(rows)} 条孤儿来源记录（file_hash 将被释放）：")
        for src_id, filename, file_hash, created_at in rows:
            print(f"  id={src_id} 文件={filename} hash={file_hash} 创建={created_at}")
        if not args.apply:
            print("试运行结束，未删除任何数据；确认后加 --apply 执行。")
            return 0
        n = db.execute(
            delete(QuestionBankSource).where(
                not_(exists().where(QuestionBankSet.source_id == QuestionBankSource.id))
            )
        ).rowcount
        db.commit()
        print(f"已删除 {n} 条孤儿来源记录，相应的 file_hash 已释放，可重新上传同名文档。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
