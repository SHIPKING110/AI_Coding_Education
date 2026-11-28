"""题库解析质量诊断与修复脚本。

用法（在 backend 容器或本地后端虚拟环境内运行）：
    # 仅诊断（默认，只读，不会改库）
    docker exec child_code-backend-1 .venv/bin/python scripts/qb_audit.py

    # 仅看某一套卷
    docker exec child_code-backend-1 .venv/bin/python scripts/qb_audit.py --set 中国电子学会四级

    # 修复：题号重排为 1..N
    docker exec child_code-backend-1 .venv/bin/python scripts/qb_audit.py --renumber

    # 修复：把「草稿」套卷及其题目直接置为「已发布」，使其可被练习/考试抽取
    docker exec child_code-backend-1 .venv/bin/python scripts/qb_audit.py --publish-draft

诊断会逐套卷列出：
  - 套卷状态（草稿/已发布…）与是否可用于练习/考试（仅 reviewed/published 可用）
  - 题型分布
  - 各类结构缺陷计数：单选/多选缺选项(null)、选项不足(有效<2)、缺答案、判断缺答案、编程缺参考代码、题干为空/占位
本脚本默认只读；只有显式传 --renumber / --publish-draft 才会改库。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.question_bank import (  # noqa: E402
    BankQuestionStatus,
    BankSetStatus,
    QuestionBankQuestion,
    QuestionBankSet,
)

CHOICE_TYPES = ("single_choice", "multiple_choice")


def _nonblank_options(options) -> list[str]:
    if not isinstance(options, list):
        return []
    return [str(o).strip() for o in options if str(o).strip()]


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def audit_set(db, bank_set: QuestionBankSet, samples: int = 5) -> dict:
    questions = list(
        db.scalars(
            select(QuestionBankQuestion)
            .where(QuestionBankQuestion.bank_set_id == bank_set.id)
            .order_by(QuestionBankQuestion.order_no)
        ).all()
    )
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    issues: dict[str, list[int]] = {
        "选项为空(null)": [],
        "选项不足(有效<2)": [],
        "缺答案": [],
        "编程缺参考代码": [],
        "题干为空/占位": [],
    }
    for q in questions:
        by_status[q.status] = by_status.get(q.status, 0) + 1
        by_type[q.type] = by_type.get(q.type, 0) + 1
        no = q.order_no
        if q.type in CHOICE_TYPES:
            opts = _nonblank_options(q.options)
            if q.options is None:
                issues["选项为空(null)"].append(no)
            elif len(opts) < 2:
                issues["选项不足(有效<2)"].append(no)
        if q.type in (*CHOICE_TYPES, "judgement") and _is_blank(q.answer):
            issues["缺答案"].append(no)
        if q.type == "programming" and _is_blank(q.reference_code):
            issues["编程缺参考代码"].append(no)
        stem = q.stem or ""
        if stem.strip() == "" or stem.startswith("（新题目"):
            issues["题干为空/占位"].append(no)

    usable = bank_set.status in (BankSetStatus.REVIEWED.value, BankSetStatus.PUBLISHED.value)

    print("=" * 72)
    print(f"套卷：{bank_set.name}  [{bank_set.id}]")
    print(f"  状态：{bank_set.status}  → 练习/考试{'可用' if usable else '不可用（需发布）'}")
    print(f"  学科/级别：{bank_set.subject or '-'} / {bank_set.level or '-'}  题目总数：{len(questions)}")
    print(f"  题型分布：{by_type}")
    print(f"  状态分布：{by_status}")
    any_issue = False
    for key, nos in issues.items():
        if nos:
            any_issue = True
            show = nos[:samples]
            more = f" …共{len(nos)}题" if len(nos) > samples else ""
            print(f"  ⚠ {key}：题号 {show}{more}")
    if not any_issue:
        print("  ✓ 未发现结构缺陷")
    return {"set": bank_set, "questions": questions, "issues": issues, "usable": usable}


def do_renumber(db, questions: list[QuestionBankQuestion]) -> int:
    qs = sorted(questions, key=lambda q: (q.order_no or 0, str(q.id)))
    # 先转负避免 (bank_set_id, order_no) 唯一约束冲突
    for i, q in enumerate(qs):
        q.order_no = -(i + 1)
    db.flush()
    for i, q in enumerate(qs):
        q.order_no = i + 1
    db.flush()
    return len(qs)


def do_publish_draft(db, bank_set: QuestionBankSet, questions: list[QuestionBankQuestion]) -> int:
    n = 0
    for q in questions:
        if q.status in (BankQuestionStatus.DRAFT.value, BankQuestionStatus.REVIEWED.value):
            q.status = BankQuestionStatus.PUBLISHED
            n += 1
    if bank_set.status != BankSetStatus.PUBLISHED.value:
        bank_set.status = BankSetStatus.PUBLISHED
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="题库解析质量诊断/修复")
    ap.add_argument("--set", dest="set_name", default=None, help="只处理名称包含该子串的套卷")
    ap.add_argument("--renumber", action="store_true", help="修复：题号重排为 1..N")
    ap.add_argument("--publish-draft", action="store_true", help="修复：草稿/已审套卷及题目置为已发布")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        sets = list(db.scalars(select(QuestionBankSet).order_by(QuestionBankSet.created_at.desc())).all())
        if args.set_name:
            sets = [s for s in sets if args.set_name in (s.name or "")]
        if not sets:
            print("未找到匹配的套卷")
            return 0
        for bank_set in sets:
            report = audit_set(db, bank_set)
            if args.renumber:
                n = do_renumber(db, report["questions"])
                db.commit()
                print(f"  ✎ 已重排题号 {n} 题")
            if args.publish_draft:
                n = do_publish_draft(db, report["set"], report["questions"])
                db.commit()
                print(f"  ✎ 已发布 {n} 题，套卷状态→published")
        if not args.renumber and not args.publish_draft:
            print("\n（只读诊断。如需修复加 --renumber 和/或 --publish-draft）")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
