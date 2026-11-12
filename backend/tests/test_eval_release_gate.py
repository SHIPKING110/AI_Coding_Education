"""评测口径与发布证据闸门单测。

覆盖：
- effective_parent_mode：显式指定优先；未指定时 parent_service 集自动走家长索引；
- check_release_evidence：answer_eval / Kappa 样本 / 基线运行三类发布证据缺失时的拦截。
"""

from app.services.rag_evaluation import effective_parent_mode
from scripts.deploy_gate import check_release_evidence


def test_effective_parent_mode_follows_set_domain():
    # 家长客服集未显式指定 → 家长索引（与生产链路一致）
    assert effective_parent_mode(None, "parent_service") is True
    # 教师集未显式指定 → 系统集合
    assert effective_parent_mode(None, "agent_teacher") is False
    assert effective_parent_mode(None, None) is False
    # 显式覆盖优先于 domain
    assert effective_parent_mode(True, "agent_teacher") is True
    assert effective_parent_mode(False, "parent_service") is False


def test_release_evidence_none_required_passes():
    assert check_release_evidence({}, done_runs=1) == []


def test_release_evidence_requires_answer_eval():
    problems = check_release_evidence(
        {"answer": {"cases": 0}}, done_runs=3, require_answer=True,
    )
    assert problems and "answer_eval" in problems[0]
    ok = check_release_evidence(
        {"answer": {"cases": 51}}, done_runs=3, require_answer=True,
    )
    assert ok == []


def test_release_evidence_requires_calibration_pairs_and_kappa():
    base = {"answer": {"cases": 51}}

    no_pairs = check_release_evidence(
        {**base, "calibration": {"pairs": 0}},
        done_runs=3, require_calibration=True,
    )
    assert no_pairs and "样本不足" in no_pairs[0]

    undefined = check_release_evidence(
        {**base, "calibration": {"pairs": 12, "kappa": None}},
        done_runs=3, require_calibration=True,
    )
    assert undefined and "Kappa 无定义" in undefined[0]

    low = check_release_evidence(
        {**base, "calibration": {"pairs": 12, "kappa": 0.42}},
        done_runs=3, require_calibration=True,
    )
    assert low and "低于 0.6" in low[0]

    trusted = check_release_evidence(
        {**base, "calibration": {"pairs": 12, "kappa": 0.71}},
        done_runs=3, require_calibration=True,
    )
    assert trusted == []


def test_release_evidence_requires_baseline_run():
    problems = check_release_evidence({}, done_runs=1, require_baseline=True)
    assert problems and "基线" in problems[0]
    assert check_release_evidence({}, done_runs=2, require_baseline=True) == []


def test_choose_inherited_calibration():
    from app.services.rag_evaluation import choose_inherited_calibration

    snap = {"eval_set_hash": "h1", "judge_model": "judge-a", "generation_model": "gen-a"}
    good_prev = (
        {"run_id": "prev-1", "eval_set_hash": "h1", "judge_model": "judge-a",
         "generation_model": "gen-a"},
        {"calibration": {"pairs": 12, "kappa": 0.72}},
    )
    # 本次已有足够人工样本 → 不继承
    assert choose_inherited_calibration({"pairs": 10, "kappa": 0.7}, snap, [good_prev]) is None
    # 同裁判+同生成+同数据集 → 继承并标注来源
    got = choose_inherited_calibration({"pairs": 0, "kappa": None}, snap, [good_prev])
    assert got and got["pairs"] == 12 and got["kappa"] == 0.72
    assert got["inherited_from_run"] == "prev-1"
    # 换裁判 / 换生成模型 / 数据集变了 → 不继承
    assert choose_inherited_calibration(
        {"pairs": 0}, {**snap, "judge_model": "judge-b"}, [good_prev],
    ) is None
    assert choose_inherited_calibration(
        {"pairs": 0}, {**snap, "generation_model": "gen-b"}, [good_prev],
    ) is None
    assert choose_inherited_calibration(
        {"pairs": 0}, {**snap, "eval_set_hash": "h2"}, [good_prev],
    ) is None
    # 历史校准样本不足 → 不继承
    weak_prev = (good_prev[0], {"calibration": {"pairs": 3, "kappa": 0.5}})
    assert choose_inherited_calibration({"pairs": 0}, snap, [weak_prev]) is None
