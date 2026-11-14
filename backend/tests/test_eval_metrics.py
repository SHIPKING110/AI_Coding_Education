"""评估指标纯函数单测：检索命中/召回/MRR/NDCG 与工具选择评分。"""

from evals.metrics import (
    compare_runs,
    evaluate_retrieval,
    hit_at_k,
    mrr,
    ndcg_at_k,
    normalize_relevant_keys,
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
    # 不足 k 条时，未返回的位置按不相关计
    assert precision_at_k(["A"], REL, 4) == 0.25


def test_mrr_and_ndcg():
    assert mrr(["X", "A"], REL) == 0.5            # A 在第 2 位
    assert mrr(["A"], REL) == 1.0
    assert mrr(["X", "Y"], REL) == 0.0
    # 完美排序：A、B 在前 → ndcg=1
    assert ndcg_at_k(["A", "B", "X"], REL, 3) == 1.0
    # 差排序：ndcg < 1
    assert ndcg_at_k(["X", "A", "B"], REL, 3) < 1.0
    # 同一相关文档重复出现只计一次，ndcg 不会 > 1；
    # 注意：relevant 有 A、B 两篇，只命中 A 时 ndcg < 1（ideal 覆盖两篇）
    assert ndcg_at_k(["A", "A", "A"], REL, 3) < 1.0
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


def test_evaluate_retrieval_excludes_execution_errors_from_quality_denominator():
    cases = [
        {"query": "ok", "ranked": ["A"], "relevant": ["A"], "answerable": True, "exec_status": "ok"},
        {"query": "backend error", "ranked": [], "relevant": ["A"], "answerable": True, "exec_status": "error"},
        {"query": "empty but successful", "ranked": [], "relevant": ["A"], "answerable": True, "exec_status": "ok"},
    ]
    res = evaluate_retrieval(cases, k_values=(1, 3))
    assert res["cases"] == 2
    assert res["error_cases"] == 1
    assert res["eval_error_rate"] == 0.3333
    assert res["hit@1"] == 0.5


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


def test_evaluate_retrieval_excludes_unanswerable_and_unlabeled():
    cases = [
        {"query": "q1", "ranked": ["A"], "relevant": ["A"], "answerable": True, "case_kind": "answerable"},
        {"query": "q2", "ranked": ["X"], "relevant": [], "answerable": False, "case_kind": "unanswerable"},
        {"query": "q3", "ranked": ["Y"], "relevant": [], "answerable": False, "case_kind": "unlabeled"},
    ]
    res = evaluate_retrieval(cases, k_values=(1, 3))
    assert res["cases"] == 1
    assert res["answerable_cases"] == 1
    assert res["unanswerable_cases"] == 1
    assert res["unlabeled_cases"] == 1
    assert res["hit@1"] == 1.0
    assert res["mrr"] == 1.0


def test_normalize_relevant_keys_maps_subsection_to_doc_title():
    assert normalize_relevant_keys(
        ["家长常见540问", "A1 课程体系总览"],
        ["家长常见540问-板块3课程体系与学习路径", "A1 课程体系总览"],
    ) == ["家长常见540问", "A1 课程体系总览"]
    # 未命中的标注保持原样，方便复核
    assert normalize_relevant_keys(["A1"], ["D2 报考操作手册"]) == ["D2 报考操作手册"]


def test_evaluate_retrieval_matches_subsection_label():
    res = evaluate_retrieval(
        [{
            "query": "q",
            "ranked": ["家长常见540问", "A1 课程体系总览"],
            "relevant": ["家长常见540问-板块3课程体系与学习路径"],
            "answerable": True,
        }],
        k_values=(1, 3),
    )
    assert res["hit@1"] == 1.0
    assert res["mrr"] == 1.0


def test_compare_runs():
    off = {"cases": 2, "answerable_cases": 2, "hit@3": 0.5, "mrr": 0.5}
    on = {"cases": 2, "answerable_cases": 2, "hit@3": 0.75, "mrr": 0.6}
    cmp = compare_runs(off, on, key="hit@3")
    assert cmp["baseline"] == 0.5 and cmp["candidate"] == 0.75
    assert cmp["delta"]["hit@3"] == 0.25
    assert "answerable_cases" not in cmp["delta"]


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


def test_parse_citations_and_grounding_metrics():
    from app.services.rag_evaluation import _agg_answer_subset, _parse_citations

    # 常见引用写法都要能解析
    cite = _parse_citations("退费需前台办理[1]，到账 3-5 天[1][2]。", n_contexts=2)
    assert cite["indices"] == [1, 2]
    assert cite["invalid"] == []
    assert cite["present"] is True
    # 超出上下文范围的编号 → 无效引用
    bad = _parse_citations("依据片段【3】", n_contexts=2)
    assert bad["invalid"] == [3]
    # 无语义引用的回答
    none = _parse_citations("文档未提供。", n_contexts=2)
    assert none["present"] is False

    answers = [
        {  # 正常：有引用、有依据
            "answer": "前台办理[1]", "abstained": False, "citation": {"present": True, "invalid": []},
            "unsupported": False, "keyword_hit": 1.0, "judge": {"faithfulness": 4.5},
        },
        {  # 未拒答但裁判判低忠实度 → 无依据回答
            "answer": "我猜是三天", "abstained": False, "citation": {"present": False, "invalid": []},
            "unsupported": True, "keyword_hit": 0.0, "judge": {"faithfulness": 2.0},
        },
        {  # 正确拒答：不计入引用覆盖率分母
            "answer": "文档未提供", "abstained": True, "citation": {"present": False, "invalid": []},
            "unsupported": False, "keyword_hit": None, "judge": {"faithfulness": 5},
        },
    ]
    agg = _agg_answer_subset(answers)
    assert agg["citation_coverage"] == 0.5       # 2 条未拒答中 1 条带引用
    assert agg["invalid_citation_rate"] == 0.0
    assert agg["unsupported_answer_rate"] == round(1 / 3, 4)
    assert agg["abstention_rate"] == round(1 / 3, 4)


def test_run_gate_skip_without_frozen():
    from app.services.rag_evaluation import evaluate_run_gate

    res = evaluate_run_gate(
        {"answer": {"unsupported_answer_rate": 0.0}, "eval_error_rate": 0.0},
        None,
    )
    assert res["passed"] is None and res["gate"] == "skip"


def test_run_gate_pass_and_fail():
    from app.services.rag_evaluation import evaluate_run_gate

    base_prev = {
        "frozen": {"hit@3": 0.9},
        "critical": {"hit@3": 0.85},
        "answer": {"unsupported_answer_rate": 0.02},
        "eval_error_rate": 0.0,
    }
    ok = evaluate_run_gate(
        {
            "frozen": {"hit@3": 0.9},
            "critical": {"hit@3": 0.84},
            "answer": {"unsupported_answer_rate": 0.04},
            "eval_error_rate": 0.0,
        },
        base_prev,
    )
    assert ok["passed"] is True and ok["gate"] == "pass"

    fail = evaluate_run_gate(
        {
            "frozen": {"hit@3": 0.87},   # 下降 0.03 > 0.02
            "critical": {"hit@3": 0.84},
            "answer": {"unsupported_answer_rate": 0.08},
            "eval_error_rate": 0.01,
        },
        base_prev,
    )
    assert fail["passed"] is False and fail["gate"] == "fail"
    assert len(fail["reasons"]) >= 3


def test_cohen_kappa_quadratic():
    from evals.metrics import cohen_kappa

    # 完全一致
    assert cohen_kappa([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5]) == 1.0
    # 完全相反（0<->5）
    k = cohen_kappa([0, 1, 2, 3, 4, 5], [5, 4, 3, 2, 1, 0])
    assert k is not None and k < 0
    # 单一档位（pe≈1）→ Kappa 无定义
    assert cohen_kappa([3, 3, 3], [3, 3, 3]) is None
    # 长度不一致
    assert cohen_kappa([1, 2], [1]) is None
    # 空
    assert cohen_kappa([], []) is None


def test_calibration_from_pairs_trusted_threshold():
    from evals.metrics import calibration_from_pairs

    # LLM 与人工完全一致 → kappa 1.0，trusted
    pairs = [{"llm": {"correctness": i}, "human_score": i} for i in [0, 1, 2, 3, 4, 5] * 2]
    cal = calibration_from_pairs(pairs, dimension="correctness")
    assert cal["pairs"] == 12 and cal["kappa"] == 1.0 and cal["trusted"] is True

    # 系统性偏高但顺序一致 → bias=2，且二次加权下 kappa 明显低于完全一致
    pairs2 = [{"llm": {"correctness": min(5, i + 2)}, "human_score": i} for i in [0, 1, 2, 3] * 3]
    cal2 = calibration_from_pairs(pairs2, dimension="correctness")
    assert cal2["pairs"] == 12
    assert cal2["bias"] == 2.0
    assert cal2["kappa"] is not None and cal2["kappa"] < 1.0

    # 样本不足（1 对）→ kappa 无定义，trusted False
    cal3 = calibration_from_pairs([{"llm": {"correctness": 3}, "human_score": 3}])
    assert cal3["pairs"] == 1 and cal3["kappa"] is None and cal3["trusted"] is False

    # 完全随机不一致 → kappa 低，trusted False
    import random
    random.seed(0)
    rand_pairs = [{"llm": {"correctness": random.randint(0, 5)}, "human_score": random.randint(0, 5)} for _ in range(30)]
    cal4 = calibration_from_pairs(rand_pairs, dimension="correctness")
    assert cal4["pairs"] == 30 and cal4["kappa"] is not None and cal4["kappa"] < 0.4 and cal4["trusted"] is False
