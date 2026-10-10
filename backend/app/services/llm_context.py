"""当前请求的模型上下文：路由层解析出教师个人配置后，用 use_llm 包住调用。

解析顺序（crud.llm_config.resolve）：模块映射 → 个人默认 → 全局环境变量 → 无。
下游所有 generate_*/stream/plan 函数无需改签名，自动使用当前上下文。
"""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.crud.llm_config import ResolvedLLM

_current: ContextVar["ResolvedLLM | None"] = ContextVar("current_llm", default=None)


def get_current() -> "ResolvedLLM | None":
    return _current.get()


@contextmanager
def use_llm(resolved: "ResolvedLLM | None"):
    # 注意：不用 token.reset——SSE 生成器/后台线程可能在不同线程进出，
    # 跨线程 reset 会报 "created in a different thread"；用 set(prev) 恢复。
    prev = _current.get()
    _current.set(resolved)
    try:
        yield resolved
    finally:
        _current.set(prev)


def run_with(resolved: "ResolvedLLM | None", fn, *args, **kwargs):
    """后台线程/任务 runner 专用：线程不继承 contextvar，在此重新压入。"""
    with use_llm(resolved):
        return fn(*args, **kwargs)


def require_llm(db=None, user_id=None, module: str = "agent") -> "ResolvedLLM":
    """解析并压入上下文；无可用模型时抛中文 LLMConfigError（前端弹 toast）。"""
    from app.crud import llm_config as crud
    from app.services.llm import LLMConfigError

    if user_id is None:
        raise LLMConfigError("未登录，无法使用 AI")
    resolved = crud.resolve(db, user_id, module)
    if resolved is None:
        raise LLMConfigError(
            "你还没有可用的 AI 模型：请到 设置 → 模型配置 添加（接口地址/API Key/模型名），"
            "可用“检查”按钮验证连通性后再试"
        )
    return resolved


@contextmanager
def use_teacher_llm(db, user_id, module: str):
    """路由层一行接入：with use_teacher_llm(db, user.id, "report"): ..."""
    resolved = require_llm(db, user_id=user_id, module=module)
    with use_llm(resolved):
        yield resolved


def resolve_override(db, user_id, module: str, config_id: str | uuid.UUID | None = None):
    """Agent 工作台切换模型：显式 config_id 优先（须属于本人），否则走模块映射。"""
    import uuid as _uuid

    from app.crud import llm_config as crud
    from app.services.llm import LLMConfigError

    if config_id:
        try:
            cid = config_id if isinstance(config_id, _uuid.UUID) else _uuid.UUID(str(config_id))
        except ValueError:
            raise ValueError("模型配置 ID 非法")
        cfg = crud.get_config(db, cid)
        if cfg is None or cfg.owner_id != user_id:
            raise ValueError("所选模型配置不存在或不属于你")
        from app.core.secretbox import decrypt_secret

        return crud.ResolvedLLM(
            base_url=cfg.base_url,
            api_key=decrypt_secret(cfg.api_key_enc),
            model=cfg.model,
            embed_model=cfg.embed_model,
            config_id=cfg.id,
            config_name=cfg.name,
        )
    resolved = crud.resolve(db, user_id, module)
    if resolved is None:
        raise LLMConfigError(
            "你还没有可用的 AI 模型：请到 设置 → 模型配置 添加（接口地址/API Key/模型名），"
            "可用“检查”按钮验证连通性后再试"
        )
    return resolved


def optional_resolved(db, user_id, module: str):
    """优雅降级场景：有个人/全局模型返回 resolved，否则 None（不抛错）。"""
    from app.crud import llm_config as crud

    try:
        return crud.resolve(db, user_id, module)
    except Exception:
        return None


def active_model_name(default: str = "") -> str:
    cur = get_current()
    if cur is not None:
        return cur.model or default
    try:
        from app.core.config import get_settings

        return get_settings().LLM_MODEL or default
    except Exception:
        return default
