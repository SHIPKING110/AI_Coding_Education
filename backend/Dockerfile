FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    TZ=Asia/Shanghai

# tzdata：让容器内 datetime.now() 与 DB 会话时区一致（业务时间为北京时间）
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

# uv 可执行文件（多阶段复制，避免残留构建工具）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 依赖安装层：仅当 pyproject/uv.lock 变化时重建（uv.lock 纳入版本库保证可复现）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

# 上传目录与本地数据目录（compose 中挂载命名卷持久化）
RUN mkdir -p uploads data
VOLUME ["/srv/app/uploads", "/srv/app/data"]

EXPOSE 8000

# 单 worker：AI 出题/评估任务状态在进程内存（ThreadPool + dict），多 worker 会导致
# 建任务与轮询落到不同进程而 404；需要扩容时先把任务状态外置（DB/Redis）再加 worker
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
