"""RAG / Agent 评估指标（纯函数，无外部依赖，便于单测）。

检索质量（文档级，命中以「文档标题」或 doc_id 匹配）：
- hit@k        前 k 条里是否至少命中 1 个相关文档
- recall@k     前 k 条命中的相关文档数 / 全部相关文档数
- precision@k  前 k 条里相关文档占比
- mrr          首个相关命中的排名倒数（1/rank）
- ndcg@k       归一化折损累计增益（二元相关）

答案质量（LLM 评判，见 run_rag_eval 的 judge 部分）：faithfulness / relevance 由裁判模型打分。
"""

from __future__ import annotations

import math


def _rank_of_first_relevant(
    ranked_keys: list[str], relevant: set[str]
) -> int | None:
    for i, k in enumerate(ranked_keys):
        if k in relevant:
            return i + 1  # 1-based
    return None


def hit_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if _rank_of_first_relevant(ranked_keys[:k], relevant) else 0.0


def recall_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    got = len(set(ranked_keys[:k]) & relevant)
    return got / len(relevant)


def precision_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float:
    top = ranked_keys[:k]
    if not top:
        return 0.0
    got = len(set(top) & relevant)
    return got / len(top)


def mrr(ranked_keys: list[str], relevant: set[str]) -> float:
    r = _rank_of_first_relevant(ranked_keys, relevant)
    return 1.0 / r if r else 0.0


def ndcg_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float:
    """二元相关 nDCG@k。同一相关文档在 ranked 里重复出现只计一次（去重，保证 ≤1）。"""
    top = ranked_keys[:k]
    seen_hit: set[str] = set()
    dcg = 0.0
    for i, key in enumerate(top):
        if key in relevant and key not in seen_hit:
            seen_hit.add(key)
            dcg += 1.0 / math.log2(i + 2)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def evaluate_retrieval(
    cases: list[dict], k_values: tuple[int, ...] = (1, 3, 5)
) -> dict:
    """对一组检索用例汇总指标。

    每个 case 形如：
        {"query": str, "relevant": [key, ...], "ranked": [key, ...]}
    其中 key 为文档标题或 doc_id（需与数据集标注一致）。
    返回各 k 下的命中率/召回/精度/ndcg 均值，以及整体 MRR。
    """
    n = len(cases)
    if n == 0:
        return {"cases": 0}
    agg: dict[str, float] = {f"hit@{k}": 0.0 for k in k_values}
    agg.update({f"recall@{k}": 0.0 for k in k_values})
    agg.update({f"precision@{k}": 0.0 for k in k_values})
    agg.update({f"ndcg@{k}": 0.0 for k in k_values})
    agg["mrr"] = 0.0
    for c in cases:
        ranked = list(dict.fromkeys(c.get("ranked") or []))  # doc 级去重：同文档多切片只计首次位次
        relevant = set(c.get("relevant") or [])
        for k in k_values:
            agg[f"hit@{k}"] += hit_at_k(ranked, relevant, k)
            agg[f"recall@{k}"] += recall_at_k(ranked, relevant, k)
            agg[f"precision@{k}"] += precision_at_k(ranked, relevant, k)
            agg[f"ndcg@{k}"] += ndcg_at_k(ranked, relevant, k)
        agg["mrr"] += mrr(ranked, relevant)
    return {"cases": n, **{name: round(v / n, 4) for name, v in agg.items()}}


def compare_runs(baseline: dict, candidate: dict, key: str = "hit@3") -> dict:
    """对比两次运行（如：关闭重排 vs 开启重排），返回关键指标的增减。"""
    keys = [k for k in baseline if k not in ("cases",)]
    delta = {k: round(candidate.get(k, 0.0) - baseline.get(k, 0.0), 4) for k in keys}
    return {"key": key, "baseline": baseline.get(key, 0.0), "candidate": candidate.get(key, 0.0), "delta": delta}


def tool_scores(expected: list[str], called: list[str], forbid: list[str] | None = None) -> dict:
    """Agent 工具调用评估：精确率/召回率/漏调/误调。

    - 期望空 & 调用空 → 完美（闲聊不调工具）；
    - 期望空但调了工具 → precision=0（多余调用）；
    - forbid 里的工具被调用 → 计入误调，ok=False。
    """
    exp, got = set(expected), set(called)
    tp = len(exp & got)
    precision = (tp / len(got)) if got else (1.0 if not exp else 0.0)
    recall = (tp / len(exp)) if exp else 1.0
    extra = sorted(got - exp)
    missing = sorted(exp - got)
    forbidden_hit = sorted(got & set(forbid or []))
    ok = not extra and not missing and not forbidden_hit
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "extra": extra,              # 误调（不该调却调了）
        "missing": missing,          # 漏调（该调没调）
        "forbidden_hit": forbidden_hit,
        "ok": ok,
    }


__all__ = [
    "hit_at_k",
    "recall_at_k",
    "precision_at_k",
    "mrr",
    "ndcg_at_k",
    "evaluate_retrieval",
    "compare_runs",
    "tool_scores",
]