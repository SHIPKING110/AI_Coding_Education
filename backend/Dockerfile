FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    UV_LINK_MODE=copy

# PyPI 镜像：国内网络直连官方源易超时，默认走清华镜像；
# 如需官方源，构建时 --build-arg UV_INDEX_URL=https://pypi.org/simple 覆盖
ARG UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV UV_DEFAULT_INDEX=$UV_INDEX_URL

# tzdata：让容器内 datetime.now() 与 DB 会话时区一致（业务时间为北京时间）
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

# uv 可执行文件（多阶段复制，避免残留构建工具）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 依赖安装层：仅当 pyproject/uv.lock 变化时重建（uv.lock 纳入版本库保证可复现）
# --extra ai：装 AI 运行依赖（langchain/chromadb 等走清华镜像，国内可直连）；
# 不含 ai-local（sentence-transformers+torch 体积大，生产 embedding 走 API，无需本地权重）
# cache 挂载复用已下载的 wheel，重试构建不用从头下载
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra ai
# 构建期冒烟：AI 关键依赖缺失直接失败，不流到运行时才暴露
RUN .venv/bin/python -c "import langchain_openai, chromadb; print('ai deps ok')"

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
