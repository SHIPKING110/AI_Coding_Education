"""Agent 任务评估运行器：跑标注任务集，评估工具选择（precision/recall）与任务是否被规划处理。

用法（容器内）：
    python -m evals.run_agent_eval --owner <username> --dataset evals/datasets/agent_seed.jsonl

数据集格式（JSONL，每行一条）：
    {"task": "...", "expect_tools": ["get_class_attendance"], "forbid_tools": [], "notes": "可选"}

评估口径：
- expect_tools：该任务「应调用」的工具（缺=漏调）；forbid_tools：明确「不该调用」的工具（现=误调）；
- precision/recall 基于实际调用工具集与 expect_tools；
- ok = 无漏调且无误调。
工具名以规划层实际调用为准（见 PlanOutcome.tools）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User
from app.services import agent_planner
from app.services import llm_context
from evals.metrics import tool_scores


def _load_dataset(path: str) -> list[dict]:
    items: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(json.loads(line))
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent 工具选择评估")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--owner", default=None, help="用户名，默认取库中第一个")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    dataset = _load_dataset(args.dataset)
    if not dataset:
        sys.exit("数据集为空")

    db = SessionLocal()
    try:
        if args.owner:
            user = db.scalars(select(User).where(User.username == args.owner)).first()
        else:
            user = db.scalars(select(User)).first()
        if user is None:
            sys.exit("未找到用户")

        # 解析该用户在「agent 模块」使用的模型配置并注入上下文：
        # 否则规划层拿不到 Key，会静默降级为启发式（评估就测不到 LLM 规划）。
        resolved = llm_context.resolve_override(db, user.id, "agent")

        rows: list[dict] = []
        n_ok = 0
        for item in dataset:
            with llm_context.use_llm(resolved):
                outcome = agent_planner.plan_and_run(db, user, item["task"])
            called = list(dict.fromkeys(outcome.tools))
            exp = list(item.get("expect_tools") or [])
            forbid = list(item.get("forbid_tools") or [])
            sc = tool_scores(exp, called, forbid)
            ok = sc["ok"]
            n_ok += 1 if ok else 0
            rows.append({
                "task": item["task"], "called": called, "expect": exp,
                "precision": sc["precision"], "recall": sc["recall"],
                "missing": sc["missing"], "extra": sc["extra"],
                "forbidden_hit": sc["forbidden_hit"], "ok": ok,
                "degraded": outcome.degraded,
            })

        total = len(dataset)
        print(f"Agent 评估：{n_ok}/{total} 通过（工具选择完全正确）\n")
        for r in rows:
            mark = "✓" if r["ok"] else "✗"
            print(f"{mark} {r['task']}")
            print(f"    调用={r['called']} 期望={r['expect']} "
                  f"P={r['precision']} R={r['recall']}")
            if r["missing"]:
                print(f"    漏调={r['missing']}")
            if r["extra"] or r["forbidden_hit"]:
                print(f"    误调={r['extra'] or r['forbidden_hit']}")
            if r["degraded"]:
                print("    （启发式降级：未走 LLM 规划）")
        print(f"\n通过率 = {round(n_ok / total, 4) if total else 0.0}")

        if args.json:
            Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"已写出：{args.json}")
    finally:
        db.close()


if __name__ == "__main__":
    main()