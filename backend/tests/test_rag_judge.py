"""裁判 JSON 解析：保留完整性 / 逻辑性 / 正确性等新增维度。"""

from app.services.rag_evaluation import _ABSTAIN_RE, _agg_answer_subset
from app.services.rag_judge import parse_judge_json


def test_parse_judge_json_keeps_all_scores():
    parsed = parse_judge_json(
        '{"faithfulness":5,"relevance":4,"completeness":3,"logic":2,'
        '"correctness":1,"reason":"ok"}'
    )
    assert parsed["faithfulness"] == 5
    assert parsed["relevance"] == 4
    assert parsed["completeness"] == 3
    assert parsed["logic"] == 2
    assert parsed["correctness"] == 1
    assert parsed["reason"] == "ok"


def test_parse_judge_json_clamps_and_defaults():
    parsed = parse_judge_json('{"faithfulness":9,"relevance":-2,"completeness":"4"}')
    assert parsed["faithfulness"] == 5
    assert parsed["relevance"] == 0
    assert parsed["completeness"] == 4
    assert "logic" not in parsed


def test_abstain_pattern_and_rate():
    assert _ABSTAIN_RE.search("文档未提供")
    assert _ABSTAIN_RE.search("这个问题无法回答")
    assert not _ABSTAIN_RE.search("Scratch 可以制作小游戏")
    agg = _agg_answer_subset([
        {"keyword_hit": 0.5, "abstained": True, "judge": {"faithfulness": 5}},
        {"keyword_hit": 0.0, "abstained": False, "judge": {"faithfulness": 4}},
    ])
    assert agg["abstention_rate"] == 0.5
    assert agg["faithfulness"] == 4.5
