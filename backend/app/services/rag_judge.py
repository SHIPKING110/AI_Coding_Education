"""LLM 裁判答案质量：给定「问题 + 检索片段 + 回答」，打质量分。

- faithfulness（忠实度）：回答是否只基于检索片段，未编造片段之外的事实；
- relevance（相关性）：回答是否真正回答了问题；
- completeness（完整性）：是否覆盖回答该问题所需的关键信息；
- logic（逻辑性）：论述是否自洽、有条理；
- correctness（正确性）：与标准答案事实是否一致（有标准答案时）。
- 每维 0-5 整数 + 一句话理由；输出严格 JSON，便于评估脚本解析。

调用方：evals/run_rag_eval.py --judge（复用教师在 agent 模块配置的对话模型）。
无模型可用时抛 LLMConfigError，由调用方降级为「跳过裁判」。
"""

from __future__ import annotations

import json

JUDGE_SYS = (
    "你是 RAG 答案质量裁判。只根据给定的检索片段判断回答质量，"
    "不要引入你自己的外部知识。只返回 JSON，不要多余文字。"
)

JUDGE_TEMPLATE = """问题：
{question}

检索片段（共 {n} 段）：
{contexts}

待评回答：
{answer}

请从四维打分（每维 0-5 整数，必须全部输出）：
- faithfulness（忠实度）：回答中的事实断言是否有片段支撑；无支撑的编造扣分；
  回答明确说"不知道/片段不足"不扣分。
- relevance（相关性）：回答是否切题、是否解决了问题；答非所问扣分。
- completeness（完整性）：是否覆盖回答该问题所需的关键信息。
- logic（逻辑性）：论述是否自洽、有条理。

只返回如下 JSON：
{{"faithfulness": <int>, "relevance": <int>, "completeness": <int>, "logic": <int>, "reason": "<一句话理由>"}}"""


def judge_answer(question: str, contexts: list[str], answer: str) -> dict:
    """调当前上下文的对话模型打分；返回 {faithfulness, relevance, reason}。"""
    from app.services import llm
    from app.services.llm import LLMConfigError
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = JUDGE_TEMPLATE.format(
        question=(question or "").strip()[:1000],
        n=len(contexts),
        contexts="\n---\n".join(f"[{i+1}] {c[:800]}" for i, c in enumerate(contexts[:5])) or "（无检索片段）",
        answer=(answer or "").strip()[:2000] or "（空回答）",
    )
    try:
        model = llm._chat_model()
        resp = model.invoke([SystemMessage(content=JUDGE_SYS), HumanMessage(content=prompt)])
        text = (resp.content or "").strip() if isinstance(resp.content, str) else str(resp.content)
    except Exception as e:  # noqa: BLE001 —— 认证/超时/断网统一转中文
        raise LLMConfigError(llm.friendly_llm_error(e)) from e
    return parse_judge_json(text)


def parse_judge_json(text: str) -> dict:
    """宽容解析裁判输出；保留所有评分维度，解析失败时兜底 0 分。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e != -1 and e > s:
        t = t[s : e + 1]
    try:
        data = json.loads(t)
        if isinstance(data, dict):
            out: dict = {"reason": str(data.get("reason", ""))[:200]}
            for key in ("faithfulness", "relevance", "completeness", "logic", "expression", "correctness"):
                if key in data:
                    try:
                        out[key] = max(0, min(5, int(float(data[key]))))
                    except (TypeError, ValueError):
                        pass
            # 兼容旧调用方：至少保证 faithfulness / relevance 存在
            out.setdefault("faithfulness", 0)
            out.setdefault("relevance", 0)
            return out
    except (ValueError, TypeError):
        pass
    return {"faithfulness": 0, "relevance": 0, "reason": (text or "")[:200] or "解析失败"}


__all__ = ["judge_answer", "parse_judge_json"]
