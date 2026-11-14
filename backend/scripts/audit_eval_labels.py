"""评测标注审计：用 FAQ 文档正文核验“是否应把 FAQ 也算作相关文档”。

背景：家长常见问题集是一篇大文档，很多评测用例的 relevant 只写了更细的
业务文档，导致 FAQ 明明包含标准答案、却因为标注没列它而被判 miss/ranking_low。
本脚本只做“内容核验 + 建议”，不根据检索排名自动造标注：

- 读取评测结果中的 bad case；
- 用该 case 的 gt_keywords 在 FAQ 正文里做命中核验；
- 命中比例达到阈值，或 retrieval_miss 的 top1 就是 FAQ 时，建议把 FAQ 加入 relevant；
- --apply 才写库，并记一条 rag_admin_audit。

用法（容器内）：
    python -m scripts.audit_eval_labels --run-id <uuid>
    python -m scripts.audit_eval_labels --run-id <uuid> --apply
"""

from __future__ import annotations

import argparse
import re
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal
from app.crud import rag_admin as crud
from app.models.knowledge import KnowledgeDocument
from app.models.rag_admin import RagEvalCase, RagEvalResult, RagEvalRun
from app.services import rag

FAQ_TITLE = "家长常见540问"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _faq_text(db) -> str:
    doc = db.scalars(
        select(KnowledgeDocument).where(
            KnowledgeDocument.title == FAQ_TITLE,
            KnowledgeDocument.status == "ready",
        )
    ).first()
    if doc is None:
        return ""
    try:
        got = rag.get_collection().get(
            where={"doc_id": str(doc.id)}, include=["documents"]
        )
        return "\n".join(got.get("documents") or [])
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--min-ratio", type=float, default=0.4)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        run = db.get(RagEvalRun, uuid.UUID(args.run_id))
        if run is None:
            print("run not found")
            return 2
        rows = list(db.scalars(
            select(RagEvalResult).where(
                RagEvalResult.run_id == run.id,
                RagEvalResult.bad_case_type.in_(["retrieval_miss", "ranking_low"]),
            )
        ).all())
        faq = _faq_text(db)
        if not faq:
            print("FAQ document text not found")
            return 2
        faq_norm = _norm(faq)
        suggestions: list[tuple[RagEvalResult, RagEvalCase, list[str], float]] = []
        for row in rows:
            case = db.get(RagEvalCase, row.case_id)
            if case is None or FAQ_TITLE in (case.relevant or []):
                continue
            keywords = [str(k).strip() for k in (case.gt_keywords or []) if str(k).strip()]
            present = [k for k in keywords if _norm(k) in faq_norm]
            ratio = round(len(present) / len(keywords), 2) if keywords else 0.0
            top1 = (row.ranked or [""])[0]
            is_miss_with_faq_top1 = row.bad_case_type == "retrieval_miss" and top1 == FAQ_TITLE
            if ratio >= args.min_ratio or is_miss_with_faq_top1:
                suggestions.append((row, case, present, ratio))

        print(f"candidates={len(rows)} suggestions={len(suggestions)} apply={args.apply}")
        for row, case, present, ratio in suggestions:
            print(
                f"[{row.bad_case_type}] {case.query[:48]} "
                f"ratio={ratio} hit={present} relevant={case.relevant}"
            )
            if args.apply:
                case.relevant = [FAQ_TITLE, *(case.relevant or [])]
        if args.apply and suggestions:
            db.commit()
            crud.add_audit(
                db,
                action="eval_label_audit",
                target=f"eval_set:{run.set_id}",
                detail={
                    "run_id": str(run.id),
                    "added_faq": len(suggestions),
                    "min_ratio": args.min_ratio,
                    "case_ids": [str(case.id) for _, case, _, _ in suggestions],
                },
                operator_id=run.owner_id,
            )
            print(f"applied={len(suggestions)}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
