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
    # 运行环境：dev / test / prod。prod 下启动时强校验密钥等安全配置，不合规直接拒绝启动
    APP_ENV: str = "dev"

    # 安全
    SECRET_KEY: str = "change-me-in-production"
    # 密钥轮换：旧密钥逗号分隔（解密兼容，加密始终用当前 SECRET_KEY）
    SECRET_KEY_PREVIOUS: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # 自助注册开关：关闭后仅管理员/教务可创建账号（家长/学员由教师建档激活）
    ALLOW_SELF_REGISTRATION: bool = False
    # 媒体访问签名 URL 有效期（秒）：/uploads/ 下的文件必须携带签名才可读取
    MEDIA_URL_TTL_SECONDS: int = 86400

    # 数据库
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/child_code"
    # 启动期 schema 策略（ADR-0029）：
    #   auto   = 自动建表/补列（旧行为，兼容未 stamp 的存量库）
    #   verify = 只读校验并告警，不执行任何 DDL（配合 alembic 迁移，推荐）
    #   off    = 完全跳过
    # 过渡期默认 auto；8080 完成基线 stamp 后切 verify。
    SCHEMA_ENSURE_MODE: str = "auto"
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
    # 知识库增量同步：后台轮询间隔（秒，0=关闭）。检测源文件新增/变更 → 自动重索引；
    # 未变更文档按内容哈希跳过，不重复消耗 Token。
    KNOWLEDGE_SYNC_INTERVAL: int = 900

    # 智能助手业务工具规划层预算（多轮工具调用的稳定性护栏）
    AGENT_TOOL_MAX_ROUNDS: int = 4       # 最多规划-执行轮数
    AGENT_TOOL_MAX_CALLS: int = 8        # 单次问答最多执行工具数
    AGENT_TOOL_TIME_BUDGET_MS: int = 20000  # 规划+执行总时间预算（毫秒）
    AGENT_TOOL_RESULT_CHARS: int = 1200  # 单个工具结果回灌给模型的最大字符数
    AGENT_TOOL_BLOCK_CHARS: int = 5000   # 注入最终回答的业务数据块最大字符数

    # RAG 检索阈值门控（评估暴露：0.15 过松导致低相关过度召回）
    RAG_MIN_SIMILARITY: float = 0.35  # 向量相似度低于此直接丢弃；可用 env 覆盖

    # Agent 任务观测（run/span）：默认开启，失败不影响主链路
    AGENT_RUN_TRACE_ENABLED: bool = True
    AGENT_RUN_TRACE_SAMPLE_RATE: float = 1.0
    AGENT_RUN_RETENTION_DAYS: int = 30

    # Token 计量与成本记账（用量与成本仪表盘）：默认开启，失败不影响主链路
    LLM_USAGE_TRACKING_ENABLED: bool = True
    # 明细保留天数；更早的明细每月汇总进 llm_usage_monthly（永久保留）后清理
    LLM_USAGE_RETENTION_DAYS: int = 180

    # 意图分类：规则优先；低置信度时才交给轻量 LLM（默认关闭，避免额外 token）
    AGENT_INTENT_LLM_FALLBACK: bool = False
    AGENT_INTENT_CONFIDENCE_THRESHOLD: float = 0.55


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# 视为「未替换」的占位密钥：出现即判定为不安全配置
_INSECURE_SECRET_KEYS = {
    "",
    "change-me-in-production",
    "请替换为随机密钥",
    "secret",
    "changeme",
}


def validate_startup_security(current: Settings | None = None) -> list[str]:
    """生产环境安全配置强校验。

    返回告警列表（非致命）；致命问题直接抛 RuntimeError 拒绝启动。
    dev/test 环境只产生告警，不阻断本地开发与测试。
    """
    cfg = current or get_settings()
    problems: list[str] = []
    key = (cfg.SECRET_KEY or "").strip()
    if key in _INSECURE_SECRET_KEYS:
        problems.append("SECRET_KEY 仍为默认占位值，JWT 可被任意伪造")
    elif len(key) < 32:
        problems.append(f"SECRET_KEY 长度不足（当前 {len(key)}，要求 ≥32）")
    if cfg.APP_ENV.lower() in {"prod", "production"} and problems:
        raise RuntimeError(
            "生产环境安全配置不合规，拒绝启动：\n- " + "\n- ".join(problems)
            + "\n生成密钥：python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return problems
