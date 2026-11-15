"""Agent 行为评测命令行：种子用例、同步跑批、基线输出。

用法（容器内，backend 目录）：

    python -m scripts.agent_eval_cli seed                # 幂等创建默认评测集 + 30 条用例
    python -m scripts.agent_eval_cli run --set 默认      # 同步跑批并打印指标与闸门
    python -m scripts.agent_eval_cli run --set <id> --limit 5 --dry-run   # 只显示将跑哪些用例

跑批链路与线上一致（真实 SSE 端点 + agent span），单次 30 条约 1-3 分钟、少量模型费用。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.rag_admin import AgentEvalCase, AgentEvalRun, AgentEvalSet
from scripts.agent_eval_seed import DEFAULT_SET_NAME, seed_default_set


def _find_set(db, key: str) -> AgentEvalSet | None:
    try:
        return db.get(AgentEvalSet, uuid.UUID(key))
    except Exception:
        return db.scalars(
            select(AgentEvalSet).where(AgentEvalSet.name == key).order_by(AgentEvalSet.created_at)
        ).first()


def cmd_seed(args) -> int:
    db = SessionLocal()
    try:
        created, skipped = seed_default_set(db, name=args.name or DEFAULT_SET_NAME)
        print(f"评测集「{args.name or DEFAULT_SET_NAME}」：新建 {created} 条，已存在跳过 {skipped} 条")
        return 0
    finally:
        db.close()


def cmd_run(args) -> int:
    db = SessionLocal()
    try:
        eset = _find_set(db, args.set)
        if eset is None:
            print(f"评测集不存在：{args.set}（先执行 seed）")
            return 2
        cases = list(
            db.scalars(
                select(AgentEvalCase)
                .where(AgentEvalCase.set_id == eset.id)
                .order_by(AgentEvalCase.created_at.asc())
            ).all()
        )
        if args.limit:
            cases = cases[: args.limit]
        if not cases:
            print("评测集为空，先执行 seed 或导入用例")
            return 2
        if args.dry_run:
            print(f"将运行 {len(cases)} 条用例（dry-run 不调用模型）：")
            for c in cases:
                tools = ",".join(c.expected_tools or []) or ("<拒答>" if c.expect_abstain else "<无工具>")
                print(f"  [{c.split}/{c.business_criticality}] {c.query[:46]}  → {tools}")
            return 0

        run = AgentEvalRun(
            set_id=eset.id,
            status="pending",
            stage="pending",
            total_cases=len(cases),
            agent_id=args.agent or "assistant",
            model_name=args.model or "",
            eval_snapshot={"limit": int(args.limit or 0) or None},
        )
        db.add(run)
        db.commit()
        print(f"运行 {run.id}：{len(cases)} 条用例，agent={run.agent_id} …")

        # 同步执行（CLI 场景直接跑完打印，不启后台线程）
        from app.services import agent_eval_runner

        agent_eval_runner._run(str(run.id))

        db.expire_all()
        run = db.get(AgentEvalRun, run.id)
        if run is None or run.status != "done":
            print(f"运行失败：{getattr(run, 'error', '未知错误')}")
            return 1
        m = (run.metrics or {}).get("overall") or {}
        print("\n=== 总体指标 ===")
        print(json.dumps(m, ensure_ascii=False, indent=2))
        for split, sm in ((run.metrics or {}).get("splits") or {}).items():
            print(f"\n--- split={split} ---")
            print(json.dumps(sm, ensure_ascii=False, indent=2))
        print("\n=== 闸门 ===")
        print(json.dumps(run.gate or {}, ensure_ascii=False, indent=2))
        return 0 if (run.gate or {}).get("gate") != "fail" else 1
    finally:
        db.close()


def cmd_status(args) -> int:
    db = SessionLocal()
    try:
        eset = _find_set(db, args.set) if args.set else None
        stmt = select(AgentEvalRun).order_by(AgentEvalRun.created_at.desc()).limit(args.last)
        if eset is not None:
            stmt = (
                select(AgentEvalRun)
                .where(AgentEvalRun.set_id == eset.id)
                .order_by(AgentEvalRun.created_at.desc())
                .limit(args.last)
            )
        rows = db.scalars(stmt).all()
        for r in rows:
            metrics = (r.metrics or {}).get("overall") or {}
            print(
                f"{r.id}  {r.status:8s}  {r.created_at.astimezone().strftime('%Y-%m-%d %H:%M') if r.created_at else ''}"
                f"  通过率={metrics.get('pass_rate')}  序列={metrics.get('seq_score')}"
                f"  闸门={(r.gate or {}).get('gate') or '-'}"
            )
        return 0
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent 行为评测 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("seed", help="幂等创建默认评测集与用例")
    sp.add_argument("--name", default=None)
    sp.set_defaults(func=cmd_seed)

    rp = sub.add_parser("run", help="同步执行一次评测运行")
    rp.add_argument("--set", default=DEFAULT_SET_NAME)
    rp.add_argument("--limit", type=int, default=0)
    rp.add_argument("--agent", default="assistant")
    rp.add_argument("--model", default="")
    rp.add_argument("--dry-run", action="store_true")
    rp.set_defaults(func=cmd_run)

    tp = sub.add_parser("status", help="查看最近运行")
    tp.add_argument("--set", default=None)
    tp.add_argument("--last", type=int, default=10)
    tp.set_defaults(func=cmd_status)

    args = ap.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
