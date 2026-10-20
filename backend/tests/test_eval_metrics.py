"""评估指标纯函数单测：检索命中/召回/MRR/NDCG 与工具选择评分。"""

from evals.metrics import (
    compare_runs,
    evaluate_retrieval,
    hit_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    tool_scores,
)

REL = {"A", "B"}


def test_hit_recall_precision():
    ranked = ["X", "A", "B", "Y"]
    assert hit_at_k(ranked, REL, 1) == 0.0     # 第 1 名不相关
    assert hit_at_k(ranked, REL, 2) == 1.0     # 第 2 名命中 A
    assert recall_at_k(ranked, REL, 4) == 1.0  # 前 4 全覆盖 A、B
    assert recall_at_k(ranked, REL, 2) == 0.5
    assert precision_at_k(ranked, REL, 4) == 0.5
    assert precision_at_k(ranked, REL, 2) == 0.5


def test_mrr_and_ndcg():
    assert mrr(["X", "A"], REL) == 0.5            # A 在第 2 位
    assert mrr(["A"], REL) == 1.0
    assert mrr(["X", "Y"], REL) == 0.0
    # 完美排序：A、B 在前 → ndcg=1
    assert ndcg_at_k(["A", "B", "X"], REL, 3) == 1.0
    # 差排序：ndcg < 1
    assert ndcg_at_k(["X", "A", "B"], REL, 3) < 1.0
    # 同一相关文档重复出现只计一次，ndcg 不会 > 1
    assert ndcg_at_k(["A", "A", "A"], REL, 3) == 1.0
    assert ndcg_at_k(["A", "A", "A", "B"], {"A", "B"}, 4) <= 1.0


def test_evaluate_retrieval_dedupes_doc_level():
    # 同一文档多切片重复命中，doc 级指标只按首次位次计
    res = evaluate_retrieval(
        [{"query": "q", "ranked": ["A", "A", "A", "B"], "relevant": ["A", "B"]}],
        k_values=(1, 4),
    )
    assert res["cases"] == 1
    assert res["hit@1"] == 1.0
    assert res["recall@4"] == 1.0
    assert res["ndcg@4"] <= 1.0


def test_evaluate_retrieval_aggregate():
    cases = [
        {"query": "q1", "ranked": ["A", "X"], "relevant": ["A"]},
        {"query": "q2", "ranked": ["X", "Y"], "relevant": ["A"]},
    ]
    res = evaluate_retrieval(cases, k_values=(1, 3))
    assert res["cases"] == 2
    assert res["hit@1"] == 0.5   # 仅 q1 命中
    assert res["hit@3"] == 0.5
    assert res["mrr"] == 0.5     # q1=1.0, q2=0.0


def test_compare_runs():
    off = {"cases": 2, "hit@3": 0.5, "mrr": 0.5}
    on = {"cases": 2, "hit@3": 0.75, "mrr": 0.6}
    cmp = compare_runs(off, on, key="hit@3")
    assert cmp["baseline"] == 0.5 and cmp["candidate"] == 0.75
    assert cmp["delta"]["hit@3"] == 0.25


def test_tool_scores():
    ok = tool_scores(["a", "b"], ["a", "b"])
    assert ok["ok"] and ok["precision"] == 1.0 and ok["recall"] == 1.0
    # 期望空 & 调用空 → 完美（闲聊不调工具）
    empty = tool_scores([], [])
    assert empty["ok"] and empty["precision"] == 1.0 and empty["recall"] == 1.0
    # 期望空但调了 → 误调
    noisy = tool_scores([], ["z"])
    assert not noisy["ok"] and noisy["extra"] == ["z"]
    miss = tool_scores(["a", "b"], ["a"])
    assert not miss["ok"] and miss["missing"] == ["b"] and miss["recall"] == 0.5
    extra = tool_scores(["a"], ["a", "z"])
    assert not extra["ok"] and extra["extra"] == ["z"] and extra["precision"] == 0.5
    # forbid 命中 → ok=False
    forb = tool_scores([], ["bad"], forbid=["bad"])
    assert not forb["ok"] and forb["forbidden_hit"] == ["bad"]
