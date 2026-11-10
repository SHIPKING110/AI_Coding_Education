"""上线前评测闸门：读取指定评测集最近一次完成的运行，校验验收闸门与裁判可信度。

用法（容器内，部署前执行）：

    python -m scripts.deploy_gate --set-id <评测集UUID>
    python -m scripts.deploy_gate --set-name "家长常见问答回归集"
    python -m scripts.deploy_gate --json      # 机器可读输出
    # 也可用环境变量 RAG_GATE_SET_ID / RAG_GATE_SET_NAME（发版 wrapper 使用）

退出码（可直接用于 CI/发布脚本拦截）：
    0 = 闸门通过（或 --allow-missing 且无历史运行）
    1 = 闸门未通过（冻结集/关键用例回退、无依据回答率或异常率超限、Kappa 不达标）
    2 = 找不到评测集 / 没有完成的运行（默认阻断发布）
    3 = 运行数据异常（gate 缺失且无法现场补算）

闸门规则（与后台评测页一致，见 app/services/rag_evaluation.py）：
- 冻结集 / 关键用例 hit@3 相对上一次完成运行下降 > 2pp → fail
- 无依据回答率 > 5% → fail；检索异常率 > 0.1% → fail
- 人工复核样本 ≥ 10 对且 quadratic kappa < 0.6 → fail（自动评测结论不可信）
- 无冻结集/关键用例切片时 gate=skip，本脚本按“未配置验收”处理，默认阻断（--allow-missing 可放行）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

from app.core.database import SessionLocal
from app.crud import rag_admin as crud
from app.services import rag_evaluation


def _resolve_set(db, set_id: str | None, set_name: str | None):
    if set_id:
        try:
            sid = uuid.UUID(set_id)
        except ValueError:
            return None, f"评测集 ID 非法：{set_id}"
        es = crud.get_eval_set(db, sid)
        return (es, None) if es else (None, f"评测集不存在：{set_id}")
    if set_name:
        for es in crud.list_eval_sets(db):
            if es.name == set_name:
                return es, None
        return None, f"评测集名称未找到：{set_name}"
    return None, "必须提供 --set-id 或 --set-name"


def _fmt(v) -> str:
    return "-" if v is None else f"{v:.4f}" if isinstance(v, float) else str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description="RAG 评测验收闸门（部署前校验）")
    ap.add_argument("--set-id", default=os.environ.get("RAG_GATE_SET_ID") or None,
                    help="评测集 UUID（也可用环境变量 RAG_GATE_SET_ID）")
    ap.add_argument("--set-name", default=os.environ.get("RAG_GATE_SET_NAME") or None,
                    help="评测集名称（也可用环境变量 RAG_GATE_SET_NAME，与 --set-id 二选一）")
    ap.add_argument("--allow-missing", action="store_true",
                    help="没有完成的运行时放行（默认阻断）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        es, err = _resolve_set(db, args.set_id, args.set_name)
        if es is None:
            print(f"[deploy_gate] {err}", file=sys.stderr)
            return 2
        runs = [r for r in crud.list_eval_runs(db, set_id=es.id, limit=50) if r.status == "done"]
        if not runs:
            msg = f"评测集「{es.name}」没有完成的运行"
            if args.allow_missing:
                print(f"[deploy_gate] {msg}（--allow-missing 放行）")
                return 0
            print(f"[deploy_gate] {msg}，阻断发布", file=sys.stderr)
            return 2
        run = runs[0]
        metrics = run.metrics if isinstance(run.metrics, dict) else {}
        gate = metrics.get("gate") if isinstance(metrics.get("gate"), dict) else None
        if gate is None:
            prev = runs[1] if len(runs) > 1 else None
            try:
                gate = rag_evaluation.evaluate_run_gate(metrics, prev.metrics if prev else None)
            except Exception as exc:  # noqa: BLE001
                print(f"[deploy_gate] 无法补算闸门：{exc}", file=sys.stderr)
                return 3

        state = gate.get("gate") or ("pass" if gate.get("passed") else "fail")
        frozen = (metrics.get("frozen") or {}).get("hit@3")
        critical = (metrics.get("critical") or {}).get("hit@3")
        unsupported = (metrics.get("answer") or {}).get("unsupported_answer_rate")
        error_rate = metrics.get("eval_error_rate")
        calib = metrics.get("calibration") or {}
        payload = {
            "set": es.name,
            "run_id": str(run.id),
            "config_version": run.config_version,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "gate": state,
            "reasons": gate.get("reasons") or [],
            "frozen_hit3": frozen,
            "critical_hit3": critical,
            "unsupported_answer_rate": unsupported,
            "eval_error_rate": error_rate,
            "kappa_pairs": calib.get("pairs"),
            "kappa": calib.get("kappa"),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"[deploy_gate] set={es.name} run={run.id} v{run.config_version} gate={state}")
            print(
                f"  冻结集 hit@3={_fmt(frozen)} 关键用例 hit@3={_fmt(critical)} "
                f"无依据率={_fmt(unsupported)} 异常率={_fmt(error_rate)} "
                f"kappa={_fmt(calib.get('kappa'))}（{calib.get('pairs') or 0} 对）"
            )
            for reason in gate.get("reasons") or []:
                print(f"  - {reason}")

        if state == "pass":
            return 0
        if state == "skip":
            # 未配置冻结集/关键用例：不算通过；允许用 --allow-missing 显式豁免
            print("[deploy_gate] 闸门被跳过（未配置冻结集/关键用例），请先补齐验收切片", file=sys.stderr)
            return 0 if args.allow_missing else 1
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
