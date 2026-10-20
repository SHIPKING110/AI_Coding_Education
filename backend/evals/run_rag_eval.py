"""RAG 检索评估运行器：对真实知识库跑标注好的查询集，算检索指标并做重排 A/B 对比。

用法（容器内）：
    python -m evals.run_rag_eval --owner <username> --dataset evals/datasets/rag_seed.jsonl
    python -m evals.run_rag_eval --owner 20634 --top-k 5 --json out.json

数据集格式（JSONL，每行一条）：
    {"query": "...", "relevant": ["文档标题A", "文档标题B"], "notes": "可选"}

- relevant 用「文档标题」标注（与命中 hit['title'] 对齐），无需关心内部 doc_id；
- 不传 --owner 时取库中第一个用户（仅调试用，建议显式指定）；
- 同时跑 rerank=关 / 开，输出 compare，直观回答「重排到底有没有用」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User
from app.services import rag as rag_service
from evals.metrics import compare_runs, evaluate_retrieval


def _load_dataset(path: str) -> list[dict]:
    items: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(json.loads(line))
    return items


def _resolve_owner(db, username: str | None):
    if username:
        u = db.scalars(select(User).where(User.username == username)).first()
        if u is None:
            sys.exit(f"未找到用户：{username}")
        return u.id
    u = db.scalars(select(User)).first()
    if u is None:
        sys.exit("库中无用户")
    return u.id


def _run_once(dataset: list[dict], db, owner_id, *, rerank: bool, top_k: int) -> tuple[dict, list[dict]]:
    cases: list[dict] = []
    rows: list[dict] = []
    for item in dataset:
        diag: dict = {}
        hits = rag_service.retrieve(
            item["query"], db=db, owner_id=owner_id, top_k=top_k, rerank=rerank, diag=diag
        )
        ranked = [h.get("title", "") for h in hits]
        relevant = list(item.get("relevant") or [])
        cases.append({"query": item["query"], "ranked": ranked, "relevant": relevant})
        rows.append({
            "query": item["query"],
            "ranked": ranked,
            "relevant": relevant,
            "retrieval": rag_service.retrieval_summary(diag),
        })
    return evaluate_retrieval(cases), rows


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG 检索评估")
    ap.add_argument("--dataset", required=True, help="数据集 JSONL 路径")
    ap.add_argument("--owner", default=None, help="用户名（owner），默认取库中第一个用户")
    ap.add_argument("--top-k", type=int, default=5, dest="top_k")
    ap.add_argument("--json", default=None, help="把结果写到该 JSON 文件")
    args = ap.parse_args()

    dataset = _load_dataset(args.dataset)
    if not dataset:
        sys.exit("数据集为空")

    db = SessionLocal()
    try:
        owner_id = _resolve_owner(db, args.owner)
        print(f"评估 owner={owner_id} 用例数={len(dataset)} top_k={args.top_k}\n")

        base_metrics, base_rows = _run_once(dataset, db, owner_id, rerank=False, top_k=args.top_k)
        rr_metrics, rr_rows = _run_once(dataset, db, owner_id, rerank=True, top_k=args.top_k)

        print("== 仅向量召回（rerank=off）==")
        print(json.dumps(base_metrics, ensure_ascii=False, indent=2))
        print("\n== 向量 + 重排（rerank=on）==")
        print(json.dumps(rr_metrics, ensure_ascii=False, indent=2))
        print("\n== 重排增益（on - off）==")
        print(json.dumps(compare_runs(base_metrics, rr_metrics, key="hit@3"), ensure_ascii=False, indent=2))

        print("\n== 逐条明细（rerank=on）==")
        for r in rr_rows:
            mark = "✓" if set(r["ranked"]) & set(r["relevant"]) else "✗"
            print(f"{mark} Q: {r['query']}")
            print(f"    命中顺序: {r['ranked']}")
            print(f"    标注相关: {r['relevant']}  检索链: {r['retrieval']}")

        if args.json:
            Path(args.json).write_text(
                json.dumps(
                    {"off": {"metrics": base_metrics, "rows": base_rows},
                     "on": {"metrics": rr_metrics, "rows": rr_rows}},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            print(f"\n已写出：{args.json}")
    finally:
        db.close()


if __name__ == "__main__":
    main()