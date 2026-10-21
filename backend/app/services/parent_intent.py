"""家长客服意图路由（生产级分层，规则先行，零 token 短路）。

设计目标（对齐「避免浪费 Token」）：
- 只有 POLICY（政策问答）与 MENU_FOLLOWUP 会走到 LLM；
- 元意图/闲聊/越界/工具全部确定性回复，零模型调用；
- 统一兜底话术只此一份，所有"答不了"分支复用；
- 每次分类结果落 retrieval_diag.intent，可观测排障。

意图表：
    SMALLTALK      寒暄致谢 → 固定短答
    CAPABILITY     能力清单/元问题（有哪些服务、你能做什么）→ 固定清单，不检索
    TOOL           数据查询（余额/历史课/课表/反馈），由 parent_tools.pick_tool 决定
    MENU_FOLLOWUP  菜单跟进：上轮回复是列表且本轮短句 → 视为选择上一轮条目
    POLICY         政策问答 → 家长域 RAG + LLM（唯一常规烧 token 路径）
    UNKNOWN        越界/无法分类 → 统一兜底（不调 LLM，不检索）

规则可信度说明（grill 后的明确取舍）：
- 模糊一律 UNKNOWN 走统一兜底（决策：纯规则，不加 LLM 分类兜底）；
- 菜单跟进用激进判定：上轮是菜单 + 本轮 ≤30 字即视为选择（决策：aggressive）。
"""

from __future__ import annotations

import re

from app.services import parent_tools

# —— 意图常量 ——
SMALLTALK = "smalltalk"
CAPABILITY = "capability"
TOOL = "tool"
MENU_FOLLOWUP = "menu_followup"
POLICY = "policy"
UNKNOWN = "unknown"

# —— 统一兜底话术（唯一一份，所有答不了的分支复用） ——
UNIFIED_FALLBACK = (
    "这个问题我暂时没法准确回答。我只负责课程、课时、请假、活动和孩子成长这几类咨询，"
    "您可以换个问法，或点右上角「转人工」让老师帮您确认。"
)

# —— 固定回复（零 token） ——
CAPABILITY_REPLY = (
    "我可以帮您：\n"
    "1) 查课时余额（试试：「课时还剩多少」）\n"
    "2) 查未来 7 天课表（试试：「这周有什么课」）\n"
    "3) 查上课历史与出勤（试试：「上过哪些课」「上了几次」）\n"
    "4) 看最近老师课后反馈（试试：「老师最近反馈」）\n"
    "5) 课程/请假/活动等政策问答\n"
    "费用、退费、安全类问题会自动转接人工老师确认。"
)
SMALLTALK_REPLY = (
    "您好呀，我是课程小助手～可以问我课时余额、课表、上课历史、老师反馈，"
    "或课程/请假/活动政策问题；复杂问题也可以点右上角「转人工」找老师。"
)

# —— 关键词表 ——
# 能力清单/元问题（注意：问句可以带"服务/功能/能做什么"而没有业务实体）
_CAPABILITY_HINTS = (
    "有哪些服务", "什么服务", "能做什么", "能干什么", "能帮我", "你会什么",
    "可以问什么", "怎么用", "你是谁", "你叫什么", "介绍一下你", "你的功能", "有什么功能",
)

# 纯寒暄（无信息量）：短句 + 匹配
_GREETING_RE = re.compile(
    r"^(你好|您好|你们好|嗨|hi+|hello+|在吗|在么|在不在|谢谢|谢谢你|感谢|多谢|"
    r"再见|拜拜|辛苦了|好的|好嘞|收到|明白|嗯|嗯嗯|哦|哈哈+|ok+)[!！~～。.，,、\s]*$",
    re.IGNORECASE,
)

# 明确越界（闲聊/通用知识/代写）：直接统一兜底，不检索
_OUT_OF_SCOPE_HINTS = (
    "讲个笑话", "写作业", "代写", "作文怎么写", "天气", "股票", "彩票", "游戏攻略", "追星", "聊天",
)

# 菜单检测：上一轮助手回复含编号列表/枚举（"1." "2)" "①" 或 "1、"）
_MENU_RE = re.compile(r"(^|\n)\s*(\d+[.、)）]|[①②③④⑤])")


def looks_like_menu(text: str) -> bool:
    """助手回复是否是"菜单/条目列表"（用于跟进判定）。"""
    t = text or ""
    if not t:
        return False
    return len(_MENU_RE.findall(t)) >= 2


def classify(
    content: str,
    *,
    last_assistant: str = "",
    last_user: str = "",
) -> dict:
    """规则分类。返回 {intent, tool?, retrieval_query?, reason}。

    - tool：intent==TOOL 时给出工具名；
    - retrieval_query：MENU_FOLLOWUP 时为「上轮用户问题 + 本轮」，供 RAG 检索；
    - reason：命中关键字/规则，便于排障（落 diag.intent_reason）。
    """
    text = (content or "").strip()
    if not text:
        return {"intent": UNKNOWN, "reason": "empty"}

    # 1) 纯寒暄
    if len(text) <= 12 and _GREETING_RE.match(text):
        return {"intent": SMALLTALK, "reason": "greeting"}

    # 2) 越界/闲聊（明确非业务）
    for h in _OUT_OF_SCOPE_HINTS:
        if h in text:
            return {"intent": UNKNOWN, "reason": f"out_of_scope:{h}"}

    # 3) 能力清单/元问题（先于工具：避免"能帮我查课时吗"误走工具）
    for h in _CAPABILITY_HINTS:
        if h in text:
            return {"intent": CAPABILITY, "reason": f"capability:{h}"}

    # 4) 数据工具（余额/历史课/课表/反馈）：直接数据查询优先于菜单跟进
    #    （如"课时还剩多少"恰是能力清单条目标题，也应直接查数）
    tool = parent_tools.pick_tool(text)
    if tool is not None:
        return {"intent": TOOL, "tool": tool, "reason": f"tool:{tool}"}

    # 5) 菜单跟进（激进判定）：上轮是菜单 + 本轮短句 → 视为选择上一轮条目
    if last_assistant and looks_like_menu(last_assistant) and len(text) <= 30 and last_user:
        return {
            "intent": MENU_FOLLOWUP,
            "retrieval_query": f"{last_user} {text}",
            "reason": "menu_followup",
        }

    # 6) 政策问答兜底路径（RAG+LLM 是唯一常规烧 token 的通道；
    #    检索零命中时路由层统一改走 UNIFIED_FALLBACK）
    return {"intent": POLICY, "reason": "policy_default"}


__all__ = [
    "CAPABILITY",
    "CAPABILITY_REPLY",
    "MENU_FOLLOWUP",
    "POLICY",
    "SMALLTALK",
    "SMALLTALK_REPLY",
    "TOOL",
    "UNIFIED_FALLBACK",
    "UNKNOWN",
    "classify",
    "looks_like_menu",
]
