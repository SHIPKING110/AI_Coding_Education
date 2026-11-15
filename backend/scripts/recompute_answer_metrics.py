"""离线重算某次运行的答案聚合指标（不调用 LLM）。

用途：评分口径（拒答判定等）修正后，对历史运行回溯重算 answer 指标与闸门，
避免为一个统计口径变更整跑十几分钟。

用法（容器内）：

    python -m scripts.recompute_answer_metrics --run <run UUID>
"""

from __future__ import annotations

import argparse
import json
import uuid

from app.core.database import SessionLocal
from app.models import RagEvalResult, RagEvalRun
from app.services import rag_evaluation
from app.crud import rag_admin as crud


def main() -> int:
    ap = argparse.ArgumentParser(description="离线重算运行的 answer 指标")
    ap.add_argument("--run", required=True, help="评测运行 UUID")
    args = ap.parse_args()
    run_id = uuid.UUID(args.run)

    db = SessionLocal()
    try:
        run = db.get(RagEvalRun, run_id)
        if run is None:
            print(f"run 不存在：{run_id}")
            return 2
        results = (
            db.query(RagEvalResult)
            .filter(RagEvalResult.run_id == run_id)
            .order_by(RagEvalResult.id)
            .all()
        )
        answers: list[dict] = []
        for r in results:
            metrics = dict(r.metrics or {})
            ans = metrics.get("answer")
            if not isinstance(ans, dict):
                continue
            ans = dict(ans)
            head = str(ans.get("answer") or "")[: rag_evaluation._ABSTAIN_HEAD_CHARS]
            abstained = bool(rag_evaluation._ABSTAIN_RE.search(head))
            judge = ans.get("judge") if isinstance(ans.get("judge"), dict) else {}
            faith = judge.get("faithfulness")
            unsupported = bool(
                ans.get("answer") and not abstained
                and isinstance(faith, (int, float)) and faith < 3
            )
            changed = (ans.get("abstained") != abstained) or (ans.get("unsupported") != unsupported)
            ans["abstained"] = abstained
            ans["unsupported"] = unsupported
            if changed:
                metrics["answer"] = ans
                r.metrics = metrics
            answers.append(ans)
        if not answers:
            print("该运行没有答案数据（answer_eval 关闭？）")
            return 1
        aggregate = rag_evaluation._aggregate_answer([{"answer": a} for a in answers])
        run_metrics = dict(run.metrics or {})
        run_metrics["answer"] = aggregate
        prev = crud.previous_done_run(db, run.set_id, run.id)
        try:
            run_metrics["gate"] = rag_evaluation.evaluate_run_gate(
                run_metrics, prev.metrics if prev else None,
            )
        except Exception as exc:  # noqa: BLE001
            run_metrics["gate"] = {"passed": None, "gate": "skip", "reasons": [str(exc)[:200]]}
        run.metrics = run_metrics
        db.commit()
        print(json.dumps({
            "run_id": str(run_id),
            "cases": aggregate.get("cases"),
            "abstention_rate": aggregate.get("abstention_rate"),
            "answerable_abstention": (aggregate.get("answerable") or {}).get("abstention_rate"),
            "unanswerable_abstention": (aggregate.get("unanswerable") or {}).get("abstention_rate"),
            "unsupported_rate": aggregate.get("unsupported_answer_rate"),
            "gate": run_metrics.get("gate"),
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
