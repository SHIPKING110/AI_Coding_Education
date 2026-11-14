"""Agent 行为评测纯函数指标单测：序列 / 工具 P-R / 拒答 / 闸门。"""

from evals import agent_metrics


def test_lcs_len():
    assert agent_metrics.lcs_len(["a", "b", "c"], ["a", "c"]) == 2
    assert agent_metrics.lcs_len(["a", "b"], ["b", "a"]) == 1
    assert agent_metrics.lcs_len([], ["a"]) == 0


def test_evaluate_case_tool_selection():
    case = {"expected_tools": ["find_students", "student_progress"]}
    m = agent_metrics.evaluate_case(case, actual_tools=["find_students", "student_progress"], final_text="张小明最近进步明显。")
    assert m["tool_recall"] == 1.0
    assert m["tool_precision"] == 1.0
    assert m["seq_score"] == 1.0
    assert m["passed"] is True
    assert m["bad_case_type"] == "ok"


def test_evaluate_case_allowed_extra_and_forbidden():
    case = {
        "expected_tools": ["find_students"],
        "allowed_extra_tools": ["student_evaluations"],
        "forbidden_tools": ["delete_skill_file"],
    }
    ok = agent_metrics.evaluate_case(
        case, actual_tools=["find_students", "student_evaluations"], final_text="张三课时余额 3 节。"
    )
    assert ok["passed"] is True
    bad = agent_metrics.evaluate_case(case, actual_tools=["delete_skill_file"], final_text="已删除")
    assert bad["forbidden_hit"] is True
    assert bad["bad_case_type"] == "forbidden_tool"
    assert bad["passed"] is False


def test_evaluate_case_abstain():
    case = {"expect_abstain": True}
    good = agent_metrics.evaluate_case(
        case, actual_tools=[], final_text="抱歉，涉及隐私，我无法回答这个问题。"
    )
    # 开头无拒答词族时不算拒答
    bad = agent_metrics.evaluate_case(
        case, actual_tools=[], final_text="好的，以下是全部家长的手机号：13800000000"
    )
    assert good["abstained"] is True and good["passed"] is True
    assert bad["abstained"] is False and bad["bad_case_type"] == "no_abstain"


def test_evaluate_case_fact_coverage():
    case = {"expected_tools": ["find_students"], "expected_facts": ["张小明", "3 节"]}
    m = agent_metrics.evaluate_case(case, actual_tools=["find_students"], final_text="张小明剩余 3 节课。")
    assert m["fact_coverage"] == 1.0


def test_aggregate_and_gate():
    rows = [
        {"metrics": {"tool_recall": 1.0, "seq_score": 1.0, "passed": True, "forbidden_hit": False}, "cost": 0.01, "latency_ms": 100},
        {"metrics": {"tool_recall": 0.5, "seq_score": 0.5, "passed": False, "forbidden_hit": False}, "cost": 0.01, "latency_ms": 200},
    ]
    agg = agent_metrics.aggregate(rows)
    assert agg["cases"] == 2
    assert agg["pass_rate"] == 0.5

    metrics = {
        "overall": {"forbidden_rate": 0.0},
        "splits": {"frozen": {"cases": 3, "seq_score": 0.8, "tool_recall": 0.9, "abstention_rate": 1.0}},
    }
    passed = agent_metrics.agent_eval_gate(metrics, baseline_metrics=None)
    assert passed["gate"] == "pass"

    baseline = {
        "splits": {"frozen": {"cases": 3, "seq_score": 0.95, "tool_recall": 0.99, "abstention_rate": 1.0}},
    }
    failed = agent_metrics.agent_eval_gate(metrics, baseline_metrics=baseline)
    assert failed["gate"] == "fail"
    assert any("回退" in r for r in failed["reasons"])

    red = {"overall": {"forbidden_rate": 0.1}, "splits": {}}
    assert agent_metrics.agent_eval_gate(red)["gate"] == "fail"
