from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，可通过环境变量 / .env 覆盖。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    APP_NAME: str = "智能少儿编程教育管理系统"
    APP_VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    # 安全
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 数据库
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/child_code"
    # 业务时区：前端提交无时区本地时间，DB 会话按此时区解释（容器默认 UTC 会导致 +8 偏移）
    BUSINESS_TIMEZONE: str = "Asia/Shanghai"
    # 生产通过 CORS_ORIGINS 追加前端域名（逗号分隔）；同域部署可留空
    CORS_ORIGINS: str = ""

    # 素材存储（M3+：反馈照片/视频等本地文件，OQ-04 决策=本地磁盘，可配置路径）
    UPLOAD_DIR: str = "uploads"
    # 允许上传的媒体类型：image/* / video/*
    MAX_UPLOAD_SIZE_MB: int = 20

    # 模型（预留，供 M3+ 使用。默认 deepseek-v4-pro，可配置）
    LLM_MODEL: str = "deepseek-v4-pro"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    # RAG 知识库 embedding：留空则沿用各教师自配 embedding；两者都无时 RAG 不可用
    LLM_EMBED_MODEL: str = ""

    # 智能助手业务工具规划层预算（多轮工具调用的稳定性护栏）
    AGENT_TOOL_MAX_ROUNDS: int = 4       # 最多规划-执行轮数
    AGENT_TOOL_MAX_CALLS: int = 8        # 单次问答最多执行工具数
    AGENT_TOOL_TIME_BUDGET_MS: int = 20000  # 规划+执行总时间预算（毫秒）
    AGENT_TOOL_RESULT_CHARS: int = 1200  # 单个工具结果回灌给模型的最大字符数
    AGENT_TOOL_BLOCK_CHARS: int = 5000   # 注入最终回答的业务数据块最大字符数


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
