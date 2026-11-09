"""对比同一评测集最近两次完成的评测运行，打印闸门判断与指标增量。

用于人工触发的验收回溯或 CI 回归前人工复核：

    python -m scripts.compare_eval_runs <set_id>

输出示例：

    set: 家长常见问答回归集 (owner: ...)
    prev v17 done 2026-06-16 10:00 | hit@3 off=0.82→on=0.89 | frozen=0.95
    curr v18 done 2026-06-16 11:30 | hit@3 off=0.84→on=0.89 | frozen=0.88
    gate: fail  — 冻结集 hit@3 下降 7.00%，超过容忍 2.00%

非零退出码表示闸门未通过，适合在部署前人工拦截。
"""

from __future__ import annotations

import sys
import uuid

from app.core.database import SessionLocal
from app.crud import rag_admin as crud
from app.models.rag_admin import RagEvalRun
from app.services import rag_evaluation


def _fixed(v) -> str:
    return "-" if v is None else f"{v:.4f}"


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：python -m scripts.compare_eval_runs <set_id>")
        return 2
    set_id = uuid.UUID(sys.argv[1])
    db = SessionLocal()
    try:
        es = crud.get_eval_set(db, set_id)
        if es is None:
            print(f"评测集不存在: {set_id}")
            return 1
        runs = crud.list_eval_runs(db, set_id=set_id, limit=20)
        done = [r for r in runs if r.status == "done"]
        if len(done) < 2:
            print(f"评测集「{es.name}」完成运行不足两次，无法对比")
            return 0
        prev, curr = done[1], done[0]
        ps, cs = prev.metrics or {}, curr.metrics or {}

        def hit3(m: dict) -> str:
            return f"off={_fixed(m.get('off', {}).get('hit@3'))} → on={_fixed(m.get('on', {}).get('hit@3'))}"

        print(f"set: {es.name}")
        print(f"prev v{prev.config_version} done {prev.finished_at} | {hit3(ps)} | frozen={_fixed(_slice(ps, 'frozen', 'hit@3'))}")
        print(f"curr v{curr.config_version} done {curr.finished_at} | {hit3(cs)} | frozen={_fixed(_slice(cs, 'frozen', 'hit@3'))}")

        gate = curr.metrics.get("gate") if isinstance(curr.metrics, dict) else None
        if gate:
            state = gate.get("gate")
            if state == "fail":
                print(f"gate: fail — " + "；".join(gate.get("reasons") or []))
                return 1
            if state == "pass":
                print("gate: pass — 冻结集/关键用例无回退，无依据回答率与异常率未超限")
                return 0
            print(f"gate: skip — " + "；".join(gate.get("reasons") or []))
            return 0

        # 兜底：历史运行未带 gate 字段，现场补判断
        res = rag_evaluation.evaluate_run_gate(cs, ps)
        if res["passed"] is None:
            print("gate(现场补判断): skip — " + "；".join(res["reasons"]))
            return 0
        if res["passed"]:
            print("gate(现场补判断): pass")
            return 0
        print("gate(现场补判断): fail — " + "；".join(res["reasons"]))
        return 1
    finally:
        db.close()


def _slice(m: dict, *path):
    cur: dict | None = m
    for p in path:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur if isinstance(cur, (int, float)) else None


if __name__ == "__main__":
    raise SystemExit(main())
