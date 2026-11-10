"""把种子数据集（JSONL）导入为后台评测集，供「RAG → 评测」直接跑回归。

典型用途：为家长客服建专属评测集（parent_seed.jsonl 已内置 15 条：
政策问答 / 隔离反例 / 高风险 / 闲聊）。

用法（容器内）：

    # 创建或复用同名评测集，导入种子用例（按 query 去重）
    python -m scripts.seed_eval_set --dataset evals/datasets/parent_seed.jsonl \
        --name "家长客服回归集" --domain parent_service --owner <用户名>

标注推断规则（可在导入后到评测页人工修正）：
- notes 含「反例/隔离/高风险/闲聊/致谢」且 relevant 为空 → answerability=unanswerable；
- relevant 为空且无上述标记 → unlabeled（待运营补标）；
- notes 含「高风险」→ business_criticality=critical；
- 默认 split=regression，可用 --split frozen 建冻结集。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.crud import rag_admin as crud
from app.models.user import User

_UNANSWERABLE_HINTS = ("反例", "隔离", "高风险", "闲聊", "致谢")


def _load_dataset(path: str) -> list[dict]:
    items: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(json.loads(line))
    return items


def _resolve_owner(db, username: str | None):
    if not username:
        return None
    u = db.scalars(select(User).where(User.username == username)).first()
    if u is None:
        sys.exit(f"未找到用户：{username}")
    return u.id


def _get_or_create_set(db, *, name: str, domain: str, owner_id):
    for es in crud.list_eval_sets(db):
        if es.name == name:
            return es, False
    es = crud.create_eval_set(
        db, name=name, description="由 scripts/seed_eval_set 从种子数据集导入",
        domain=domain, owner_id=owner_id, created_by=owner_id,
    )
    return es, True


def _infer_answerability(relevant: list, notes: str) -> str:
    if relevant:
        return "answerable"
    if any(h in notes for h in _UNANSWERABLE_HINTS):
        return "unanswerable"
    return "unlabeled"


def main() -> int:
    ap = argparse.ArgumentParser(description="种子数据集 → 后台评测集")
    ap.add_argument("--dataset", required=True, help="JSONL 数据集路径")
    ap.add_argument("--name", required=True, help="评测集名称（不存在则创建）")
    ap.add_argument("--domain", default="agent_teacher", help="业务域，家长客服用 parent_service")
    ap.add_argument("--owner", default=None, help="用户名（owner），默认留空")
    ap.add_argument("--split", default="regression", choices=["tuning", "regression", "frozen"])
    args = ap.parse_args()

    dataset = _load_dataset(args.dataset)
    if not dataset:
        sys.exit("数据集为空")
    db = SessionLocal()
    try:
        owner_id = _resolve_owner(db, args.owner)
        es, created = _get_or_create_set(db, name=args.name, domain=args.domain, owner_id=owner_id)
        existing = {c.query for c in crud.list_eval_cases(db, es.id)}
        added = skipped = 0
        for item in dataset:
            query = str(item.get("query") or "").strip()
            if not query or query in existing:
                skipped += 1
                continue
            relevant = [str(x) for x in (item.get("relevant") or []) if str(x).strip()]
            notes = str(item.get("notes") or "")
            crud.add_eval_case(
                db, set_id=es.id, query=query, relevant=relevant,
                answerability=_infer_answerability(relevant, notes),
                split=args.split,
                business_criticality="critical" if "高风险" in notes else "normal",
                query_type="fact" if relevant else "negative",
                notes=notes, source="seed",
            )
            existing.add(query)
            added += 1
        crud.add_audit(
            db, action="eval.set.seed", target=str(es.id),
            detail={"dataset": args.dataset, "added": added, "skipped": skipped,
                    "split": args.split, "domain": args.domain},
            operator_id=owner_id,
        )
        print(f"[seed_eval_set] set={es.name} ({'新建' if created else '复用'}) "
              f"导入 {added} 条，跳过重复/空 {skipped} 条")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
