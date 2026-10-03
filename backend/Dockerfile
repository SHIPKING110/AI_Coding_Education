FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

# 系统依赖：psycopg-binary 无需 pg 编译环境；bcrypt 需要基本构建工具时用 pwdlib 纯实现
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# 上传目录与本地数据目录（compose 中挂载命名卷持久化）
RUN mkdir -p uploads data
VOLUME ["/srv/app/uploads", "/srv/app/data"]

EXPOSE 8000

# 生产用多 worker；表结构由 lifespan 内 create_all + 幂等 addcol 自动同步
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
