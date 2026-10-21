"""测试环境能力探测：区分"代码缺陷"与"环境缺依赖"。

本地/CI 常常没有可用的 embedding 模型（远程 API 凭据或本地 sentence-transformers 权重），
依赖真实向量化的用例会一直等到超时，把整轮测试拖死。这里给出统一的探测入口，
让这类用例在环境不具备条件时显式 skip（而不是假失败）。
"""

from __future__ import annotations

import os


def embedding_available() -> bool:
    """当前环境是否具备可用的向量化能力（远程 embedding API 或本地模型权重）。"""
    # 1) 远程 embedding 凭据（任一 key 存在即认为可用）
    for env_key in (
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "EMBEDDING_MODEL",
    ):
        if os.getenv(env_key):
            return True
    # 2) 本地模型权重
    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception:
        return False
    for attr in ("EMBEDDING_MODEL_PATH", "LOCAL_EMBEDDING_MODEL_PATH"):
        path = getattr(settings, attr, None) or os.getenv(attr)
        if path and os.path.isdir(str(path)):
            return True
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
