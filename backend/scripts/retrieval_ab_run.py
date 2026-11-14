"""检索 A/B：按指定基线运行的配置再跑一次「仅检索」评测（answer_eval=off）。

用途（ADR-0023/ADR-0027）：检索/入库策略调整时先跑检索 A/B（不烧生成/裁判 Token），
达标后再进入答案评测与人工校准。

用法（容器内）：

    python -m scripts.retrieval_ab_run --from-run <基线run UUID> [--label "reindex后"]

输出：新 run 的 off/on 两套检索指标（hit@1/3/5、mrr、ndcg、异常率、低置信/关键词腿统计）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

from app.core.database import SessionLocal
from app.models import RagEvalRun
from app.services import rag_evaluation

_POLL_SECONDS = 6
_TIMEOUT_SECONDS = 1800

_METRIC_KEYS = (
    "cases", "hit@1", "hit@3", "hit@5", "mrr", "ndcg@1", "ndcg@3", "ndcg@5",
    "recall@5", "eval_error_rate",
)


def _summarize(metrics: dict | None) -> dict:
    out: dict = {}
    for side in ("off", "on"):
        block = (metrics or {}).get(side) or {}
        out[side] = {k: block.get(k) for k in _METRIC_KEYS if k in block}
    gate = (metrics or {}).get("gate")
    out["gate"] = gate if isinstance(gate, dict) else None
    return out


def _extra_stats(db, run_id: uuid.UUID) -> dict:
    """补充统计：低置信用例数、关键词腿贡献>0 的用例数。"""
    from app.models import RagEvalResult

    rows = db.query(RagEvalResult).filter(RagEvalResult.run_id == run_id).all()
    kw_used = sum(
        1 for r in rows
        if isinstance(r.metrics, dict) and int(r.metrics.get("keyword_leg_hits") or 0) > 0
    )
    low_conf = sum(
        1 for r in rows
        if isinstance(r.metrics, dict) and bool(r.metrics.get("low_confidence"))
    )
    return {"results": len(rows), "keyword_leg_used": kw_used, "low_confidence": low_conf}


def main() -> int:
    ap = argparse.ArgumentParser(description="按基线配置运行一次仅检索评测")
    ap.add_argument("--from-run", required=True, help="基线运行 UUID（复制其检索配置）")
    ap.add_argument("--label", default="", help="备注（仅打印用）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        base = db.get(RagEvalRun, uuid.UUID(args.from_run))
        if base is None:
            print(f"[retrieval_ab] 基线运行不存在：{args.from_run}", file=sys.stderr)
            return 2
        run = RagEvalRun(
            set_id=base.set_id, status="pending", owner_id=base.owner_id,
            top_k=base.top_k, rerank=base.rerank, retrieval_mode=base.retrieval_mode,
            parent_mode=base.parent_mode, answer_eval=False,
            generation_model="", judge_model="",
            created_by=base.created_by,
        )
        db.add(run)
        db.commit()
        run_id = run.id
        print(f"[retrieval_ab] {args.label or 'run'} -> {run_id}（set={base.set_id} mode={base.retrieval_mode}"
              f" parent_mode={base.parent_mode} top_k={base.top_k}）", file=sys.stderr)
        rag_evaluation.start_run(str(run_id))
        started = time.time()
        while True:
            time.sleep(_POLL_SECONDS)
            if time.time() - started > _TIMEOUT_SECONDS:
                print("[retrieval_ab] 超时未完成", file=sys.stderr)
                return 3
            db.expire_all()
            r = db.get(RagEvalRun, run_id)
            if r is None:
                print("[retrieval_ab] run 丢失", file=sys.stderr)
                return 3
            if r.status in ("done", "failed"):
                break
        summary = {
            "run_id": str(run_id),
            "status": r.status,
            "label": args.label,
            "config": {
                "retrieval_mode": r.retrieval_mode,
                "parent_mode": r.parent_mode,
                "top_k": r.top_k,
                "rerank": r.rerank,
            },
            "metrics": _summarize(r.metrics),
            "extra": _extra_stats(db, run_id) if r.status == "done" else {},
            "error": r.error,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if r.status == "done" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
