"""把仓库 JSONL 的显式标注同步回线上评测集（按 query 原地更新，不增删用例）。

背景：早期导入路径会丢字段——split 全部回归为 regression、business_criticality
全部回归为 normal、负例 answerability 落成 unlabeled——导致冻结/关键切片为空，
发布闸门直接 skip。此脚本以仓库 JSONL 为唯一事实源，把标注补回库内用例。

用法（容器内，默认 dry-run，只打印差异不写库）：

    python -m scripts.sync_eval_case_meta \
        --set-name "家长测评集" \
        --dataset evals/datasets/zhouxing_parent_eval.jsonl

    # 确认后应用；可同时改名与修正 domain（发布闸门按名称匹配评测集）
    python -m scripts.sync_eval_case_meta \
        --set-name "家长测评集" \
        --dataset evals/datasets/zhouxing_parent_eval.jsonl \
        --rename "行舟-家长客服回归集" --domain parent_service --apply

只同步 JSONL 中显式给出的字段（split / business_criticality / answerability /
query_type / difficulty / gt_answer / gt_keywords / notes），按 query 精确匹配；
JSONL 有的字段才覆盖，未匹配到或用例缺失都会逐条报告并以非零码退出。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.crud import rag_admin as crud

_SYNC_FIELDS = (
    "split",
    "business_criticality",
    "answerability",
    "query_type",
    "difficulty",
    "gt_answer",
    "gt_keywords",
    "notes",
)


def _load_dataset(path: str) -> list[dict]:
    items: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(json.loads(line))
    return items


def _normalize(field: str, value):
    if field in ("gt_keywords", "relevant"):
        return [str(x) for x in (value or []) if str(x).strip()]
    return str(value or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="同步 JSONL 标注到线上评测集（原地更新）")
    ap.add_argument("--set-name", required=True, help="要修复的评测集名称")
    ap.add_argument("--dataset", required=True, help="事实源 JSONL 路径（相对 /srv/app）")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    ap.add_argument("--rename", default=None, help="同时把评测集改名为该名称")
    ap.add_argument(
        "--domain", default=None, choices=["agent_teacher", "parent_service"],
        help="同时修正评测集 domain（家长客服集应设为 parent_service）",
    )
    args = ap.parse_args()

    dataset = _load_dataset(args.dataset)
    if not dataset:
        sys.exit("数据集为空或不存在")

    db = SessionLocal()
    try:
        es = next((x for x in crud.list_eval_sets(db) if x.name == args.set_name), None)
        if es is None:
            sys.exit(f"评测集不存在：{args.set_name}")
        cases = crud.list_eval_cases(db, es.id)
        by_query = {c.query.strip(): c for c in cases}
        file_queries = {str(item.get("query") or "").strip() for item in dataset}

        updated_cases = 0
        changed_fields: dict[str, int] = {}
        missing_in_db: list[str] = []
        diffs: list[str] = []
        for item in dataset:
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            case = by_query.get(query)
            if case is None:
                missing_in_db.append(query)
                continue
            row_changed = False
            for field in _SYNC_FIELDS:
                if field not in item:
                    continue
                new = _normalize(field, item.get(field))
                old = _normalize(field, getattr(case, field))
                if old != new:
                    diffs.append(f"  [{field}] {query[:32]}…：{old!r} → {new!r}")
                    changed_fields[field] = changed_fields.get(field, 0) + 1
                    if args.apply:
                        setattr(case, field, new)
                    row_changed = True
            if row_changed:
                updated_cases += 1

        db_not_in_file = [c.query.strip() for c in cases if c.query.strip() not in file_queries]

        print(f"[sync_eval_case_meta] set={es.name} 用例 {len(cases)} 条 / 文件 {len(dataset)} 条"
              f"（{'APPLY' if args.apply else 'DRY-RUN'}）")
        print(f"  将有/已有变化的用例：{updated_cases} 条；字段分布：{changed_fields or '无'}")
        for line in diffs[:40]:
            print(line)
        if len(diffs) > 40:
            print(f"  ……其余 {len(diffs) - 40} 处差异省略")
        if missing_in_db:
            print(f"  [警告] 文件中有但库里没有的 query {len(missing_in_db)} 条：")
            for q in missing_in_db[:10]:
                print(f"    - {q[:48]}")
        if db_not_in_file:
            print(f"  [提示] 库里有但文件中没有的 query {len(db_not_in_file)} 条（不会删除）：")
            for q in db_not_in_file[:10]:
                print(f"    - {q[:48]}")

        if args.apply:
            if args.rename and args.rename != es.name:
                print(f"  评测集改名：{es.name} → {args.rename}")
                es.name = args.rename
            if args.domain and args.domain != es.domain:
                print(f"  评测集 domain：{es.domain} → {args.domain}")
                es.domain = args.domain
            crud.add_audit(
                db, action="eval.set.meta_sync", target=str(es.id),
                detail={
                    "dataset": args.dataset,
                    "updated_cases": updated_cases,
                    "changed_fields": changed_fields,
                    "missing_in_db": len(missing_in_db),
                    "db_not_in_file": len(db_not_in_file),
                    "renamed_to": args.rename or None,
                    "domain": args.domain or None,
                },
                operator_id=None,
            )
            db.commit()
            print("  已写库并记录审计 eval.set.meta_sync")
        else:
            print("  dry-run 结束；确认无误后加 --apply 执行")
        return 1 if missing_in_db else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
