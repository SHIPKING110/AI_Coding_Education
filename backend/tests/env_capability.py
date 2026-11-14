"""测试环境能力探测：区分"代码缺陷"与"环境缺依赖"。

本地/CI 常常没有可用的 embedding 模型（远程 API 凭据或本地 sentence-transformers 权重），
依赖真实向量化的用例会一直等到超时，把整轮测试拖死。这里给出统一的探测入口，
让这类用例在环境不具备条件时显式 skip（而不是假失败）。
"""

from __future__ import annotations

import os


def embedding_available() -> bool:
    """当前环境是否具备适合单测的向量化能力（远程 embedding API）。

    判定依据是应用层真实的解析结果（system_settings 配置 + 全局 env 回退），
    而不是只看环境变量——只有解析为远程 provider 时才可用：

    - 本地 provider（sentence-transformers / Qwen 权重）首次加载需数分钟，
      不适合放进常规单测（会拖死整轮），应作为独立的慢测试单独运行；
    - 未配置任何可用 embedding 时，应用会回退本地权重，同样不适合单测。
    """
    try:
        from app.services import rag

        resolved = rag._resolve_embedding(force=True)
    except Exception:
        resolved = None
    if resolved is not None and getattr(resolved, "provider", "") != "local":
        return True
    # 未配置系统级 embedding 时，应用回退全局 env（需 LLM_EMBED_MODEL + LLM_API_KEY 同时存在）；
    # 两者缺一时仍会回退本地权重，故不视为可用。
    try:
        from app.core.config import get_settings

        s = get_settings()
        if (s.LLM_EMBED_MODEL or "").strip() and (s.LLM_API_KEY or "").strip():
            return True
    except Exception:
        pass
    return False


def llm_available() -> bool:
    """当前环境是否具备可用的 LLM 凭据（供需要真实模型调用的用例判定）。"""
    for env_key in (
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "LLM_API_KEY",
        "LLM_BASE_URL",
    ):
        if os.getenv(env_key):
            return True
    return False
