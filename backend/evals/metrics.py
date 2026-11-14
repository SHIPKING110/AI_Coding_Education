"""RAG / Agent 评估指标（纯函数，无外部依赖，便于单测）。

检索质量（文档级，命中以「文档标题」或 doc_id 匹配）：
- hit@k        前 k 条里是否至少命中 1 个相关文档
- recall@k     前 k 条命中的相关文档数 / 全部相关文档数（Context Recall）
- precision@k  前 k 条里相关文档占比（Context Precision）
- mrr          首个相关命中的排名倒数（1/rank）
- ndcg@k       归一化折损累计增益（二元相关）

不可答 / 未标注用例不进入命中类指标，避免把正确拒答误判为检索失败。

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


def normalize_relevant_keys(ranked_keys: list[str], relevant_keys: list[str] | None) -> list[str]:
    """把“文档标题-板块/章节”形式的标注归一到实际文档标题。

    评测集里常见 ``家长常见540问-板块3课程体系`` 这种更细的板块标注，而检索
    返回的是文档级标题 ``家长常见540问``。若不归一，明明命中文档也会被算作
    未命中。这里只做“检索标题是标注前缀”的匹配，不改变原始用例数据。
    """
    ranked = {str(k) for k in ranked_keys if str(k)}
    out: list[str] = []
    for raw in relevant_keys or []:
        key = str(raw or "").strip()
        if not key:
            continue
        if key in ranked:
            out.append(key)
            continue
        matched = ""
        for ranked_key in ranked:
            if key.startswith(ranked_key + "-") or key.startswith(ranked_key + "—") or key.startswith(ranked_key + "–"):
                if len(ranked_key) > len(matched):
                    matched = ranked_key
        out.append(matched or key)
    return list(dict.fromkeys(out))


def hit_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if _rank_of_first_relevant(ranked_keys[:k], relevant) else 0.0


def recall_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    got = len(set(ranked_keys[:k]) & relevant)
    return got / len(relevant)


def precision_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float:
    """前 k 条中相关文档占比；不足 k 条时未返回的位置按不相关计。"""
    if k <= 0:
        return 0.0
    top = ranked_keys[:k]
    if not top:
        return 0.0
    got = len(set(top) & relevant)
    return got / k


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
        {"query": str, "relevant": [key, ...], "ranked": [key, ...],
         "answerable": bool, "case_kind": "answerable|unanswerable|unlabeled",
         "exec_status": "ok|error"（可选）}
    其中 key 为文档标题或 doc_id（需与数据集标注一致）。

    不可答（negative/abstention）与未标注用例不参与命中类指标：它们没有
    应命中文档，计入分母会把「正确拒答」误判为「检索失败」。两类数量
    分别通过 unanswerable_cases / unlabeled_cases 返回，供前端单列展示。

    检索链路异常（exec_status="error"）的用例单独计为 error_cases，
    不进入指标分母：服务故障导致的空结果不是检索能力问题，混入会让
    报告把「系统异常」误读成「模型效果差」。
    """
    def _is_answerable(c: dict) -> bool:
        value = c.get("answerable")
        return bool(value) if value is not None else bool(c.get("relevant"))

    def _is_error(c: dict) -> bool:
        return str(c.get("exec_status") or "ok") == "error"

    retrieval_modes: dict[str, int] = {}
    for case in cases:
        mode = str(case.get("retrieval_mode") or "unknown")
        retrieval_modes[mode] = retrieval_modes.get(mode, 0) + 1
    error_cases = sum(1 for c in cases if _is_error(c))
    usable = [c for c in cases if not _is_error(c)]
    answerable = [c for c in usable if _is_answerable(c)]
    skipped = [c for c in usable if not _is_answerable(c)]
    unanswerable = sum(1 for c in skipped if c.get("case_kind") == "unanswerable")
    unlabeled = sum(1 for c in skipped if c.get("case_kind") != "unanswerable")
    n = len(answerable)
    error_stats = {
        "error_cases": error_cases,
        "error_rate": round(error_cases / len(cases), 4) if cases else 0.0,
        "retrieval_modes": retrieval_modes,
    }
    if n == 0:
        return {
            "cases": 0, "answerable_cases": 0,
            "unanswerable_cases": unanswerable, "unlabeled_cases": unlabeled,
            "eval_error_rate": error_stats["error_rate"],
            **error_stats,
        }
    agg: dict[str, float] = {f"hit@{k}": 0.0 for k in k_values}
    agg.update({f"recall@{k}": 0.0 for k in k_values})
    agg.update({f"precision@{k}": 0.0 for k in k_values})
    agg.update({f"ndcg@{k}": 0.0 for k in k_values})
    agg["mrr"] = 0.0
    for c in answerable:
        ranked = list(dict.fromkeys(c.get("ranked") or []))  # doc 级去重：同文档多切片只计首次位次
        relevant = set(normalize_relevant_keys(ranked, c.get("relevant") or []))
        for k in k_values:
            agg[f"hit@{k}"] += hit_at_k(ranked, relevant, k)
            agg[f"recall@{k}"] += recall_at_k(ranked, relevant, k)
            agg[f"precision@{k}"] += precision_at_k(ranked, relevant, k)
            agg[f"ndcg@{k}"] += ndcg_at_k(ranked, relevant, k)
        agg["mrr"] += mrr(ranked, relevant)
    return {
        "cases": n,
        "answerable_cases": n,
        "unanswerable_cases": unanswerable,
        "unlabeled_cases": unlabeled,
        "eval_error_rate": error_stats["error_rate"],
        **error_stats,
        **{name: round(v / n, 4) for name, v in agg.items()},
    }


def compare_runs(baseline: dict, candidate: dict, key: str = "hit@3") -> dict:
    """对比两次运行（如：关闭重排 vs 开启重排），返回关键指标的增减。

    同时透出两边的检索异常数：error_cases 不为 0 时 delta 不可直接当作
    效果差异解读，应先排查服务故障再做比较。
    """
    skip = {"cases", "answerable_cases", "unanswerable_cases", "unlabeled_cases", "error_cases", "error_rate", "eval_error_rate", "retrieval_modes"}
    keys = [k for k in baseline if k not in skip]
    delta = {k: round(candidate.get(k, 0.0) - baseline.get(k, 0.0), 4) for k in keys}
    return {
        "key": key, "baseline": baseline.get(key, 0.0),
        "candidate": candidate.get(key, 0.0), "delta": delta,
        "baseline_error_cases": int(baseline.get("error_cases") or 0),
        "candidate_error_cases": int(candidate.get("error_cases") or 0),
        "baseline_retrieval_modes": baseline.get("retrieval_modes") or {},
        "candidate_retrieval_modes": candidate.get("retrieval_modes") or {},
    }


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


def cohen_kappa(
    ratings_a: list[int], ratings_b: list[int], *, weights: str = "quadratic",
) -> float | None:
    """计算两名评分者对同一批样本的 Cohen's Kappa（一致性）。

    LLM 裁判 vs 人工复核的 0-5 分是**有序**评分，默认用二次加权 Kappa
    （quadratic weighted kappa），对大偏差惩罚更重、更贴近“严重错误”的
    业务含义。weights 可为 "quadratic" / "linear" / "none"（普通 Kappa）。

    两串评分长度需一致且按同一批样本对齐；返回 None 表示样本不足或
    期望一致度退化（pe≈1，Kappa 无定义），调用方应视为“样本不足以校准”。
    """
    if len(ratings_a) != len(ratings_b) or not ratings_a:
        return None
    n = len(ratings_a)
    # 评分范围（0-5），聚类到整数档
    k = max(max(ratings_a), max(ratings_b)) + 1
    # 观测一致矩阵与边际分布
    observed = [[0] * k for _ in range(k)]
    row_tot = [0] * k
    col_tot = [0] * k
    for a, b in zip(ratings_a, ratings_b):
        observed[a][b] += 1
        row_tot[a] += 1
        col_tot[b] += 1
    # 权重矩阵：惩罚评分差异
    def w(i: int, j: int) -> float:
        if weights == "none":
            return 1.0 if i == j else 0.0
        diff = abs(i - j) / max(k - 1, 1)
        if weights == "linear":
            return 1.0 - diff
        return 1.0 - diff * diff  # quadratic（默认）
    po = sum(w(i, j) * observed[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(
        w(i, j) * row_tot[i] * col_tot[j] for i in range(k) for j in range(k)
    ) / (n * n)
    if pe >= 1.0:
        return None  # 两名评分者都只用一个档位，Kappa 无定义
    return round((po - pe) / (1.0 - pe), 4)


# —— 人工校准 SLA（ADR-0027）——
# 6 档密集评分下二次加权 Kappa 对少量严重分歧过于敏感（5 分档集中导致期望一致度
# 接近 0.83），单用 0.6 门槛会把“总体高度一致、仅个别口径分歧”误判为不可信。
# 生产验收改为四指标组合，Kappa 保留为观察/趋势指标。
CALIB_MIN_PAIRS = 10        # 少于该样本对数不做 SLA 判定
CALIB_SEVERE_MAX = 0.05     # 严重分歧率（|Δ|≥3）上限 5%
CALIB_WITHIN1_MIN = 0.85    # ±1 内一致率下限 85%
CALIB_EXACT_MIN = 0.6       # 严格一致率下限 60%
CALIB_BIAS_MAX = 0.3        # 系统偏差上限 |LLM均值 − 人工均值|


def calibration_sla(report: dict) -> dict:
    """按四指标组合判定校准 SLA；样本不足返回 skip。

    输入为 calibration_from_pairs 的产物（含 exact_rate/within1_rate/
    severe_rate/bias）。Kappa 仅记录，不参与判定。
    """
    pairs = int(report.get("pairs") or 0)
    if pairs < CALIB_MIN_PAIRS:
        return {"passed": None, "reasons": [f"人工样本 {pairs} 对 < {CALIB_MIN_PAIRS} 对，无法判定"]}
    reasons: list[str] = []
    if float(report.get("severe_rate") or 0.0) > CALIB_SEVERE_MAX:
        reasons.append(
            f"严重分歧率 {round(float(report['severe_rate']) * 100, 1)}% 超过 {int(CALIB_SEVERE_MAX * 100)}%"
            f"（|Δ|≥3 需逐条仲裁归因）"
        )
    if float(report.get("within1_rate") or 0.0) < CALIB_WITHIN1_MIN:
        reasons.append(
            f"±1 内一致率 {round(float(report['within1_rate']) * 100, 1)}% 低于 {int(CALIB_WITHIN1_MIN * 100)}%"
        )
    if float(report.get("exact_rate") or 0.0) < CALIB_EXACT_MIN:
        reasons.append(
            f"严格一致率 {round(float(report['exact_rate']) * 100, 1)}% 低于 {int(CALIB_EXACT_MIN * 100)}%"
        )
    if abs(float(report.get("bias") or 0.0)) > CALIB_BIAS_MAX:
        reasons.append(f"系统偏差 {report.get('bias')} 超过 ±{CALIB_BIAS_MAX}")
    return {"passed": not reasons, "reasons": reasons}


def calibration_from_pairs(
    pairs: list[dict], *, dimension: str = "correctness", weights: str = "quadratic",
) -> dict:
    """把「LLM 裁判分 + 人工分」成对样本汇总成校准报告。

    pairs 每条形如：
        {"llm": {"correctness": 4, ...} | None, "human_score": 4 | None}
    只在两边都有整数分的样本上计算 Kappa，同时给出各档分布和平均绝对差，
    便于判断是“系统性偏高”还是“随机不一致”。验收口径见 ADR-0027：
    四指标 SLA（严重分歧率/±1 一致率/严格一致率/偏差）做闸门，
    Kappa 保留为观察指标。
    """
    llm_vals: list[int] = []
    human_vals: list[int] = []
    abs_diffs: list[int] = []
    for p in pairs:
        judge = p.get("llm") if isinstance(p.get("llm"), dict) else None
        if judge is None:
            continue
        lv = judge.get(dimension)
        hv = p.get("human_score")
        if isinstance(lv, (int, float)) and isinstance(hv, (int, float)):
            li, hi = int(round(lv)), int(round(hv))
            llm_vals.append(li)
            human_vals.append(hi)
            abs_diffs.append(abs(li - hi))
    n = len(llm_vals)
    if n == 0:
        return {"pairs": 0, "kappa": None}
    kappa = cohen_kappa(llm_vals, human_vals, weights=weights)
    mean_diff = round(sum(llm_vals) / n - sum(human_vals) / n, 2)
    report = {
        "pairs": n,
        "kappa": kappa,
        "weights": weights,
        "dimension": dimension,
        "mean_abs_diff": round(sum(abs_diffs) / n, 2),
        "llm_mean": round(sum(llm_vals) / n, 2),
        "human_mean": round(sum(human_vals) / n, 2),
        "bias": mean_diff,  # 正数表示 LLM 系统性偏高
        "exact_rate": round(sum(1 for d in abs_diffs if d == 0) / n, 4),
        "within1_rate": round(sum(1 for d in abs_diffs if d <= 1) / n, 4),
        "severe_rate": round(sum(1 for d in abs_diffs if d >= 3) / n, 4),
        "trusted": kappa is not None and kappa >= 0.6,  # 兼容旧字段：仅作观察
    }
    report["sla"] = calibration_sla(report)
    return report


__all__ = [
    "hit_at_k",
    "recall_at_k",
    "precision_at_k",
    "mrr",
    "ndcg_at_k",
    "normalize_relevant_keys",
    "evaluate_retrieval",
    "compare_runs",
    "tool_scores",
    "cohen_kappa",
    "calibration_from_pairs",
    "calibration_sla",
]