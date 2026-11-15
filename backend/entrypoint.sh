#!/bin/sh
# 容器启动入口：先对齐数据库迁移，再启动主进程。
#
# 迁移策略（ADR-0029 re-baseline 之后）：
# - 全新库：a00000000000 基线一次性建全量 schema；
# - 存量库：首次升级本镜像前需一次性 `alembic stamp a00000000000`（见 DEPLOY.md），
#   未 stamp 时 upgrade 会因「找不到旧 revision」失败——此时降级为告警并继续启动，
#   由 schema_ensure 兜底补齐（过渡期策略，M-B 完成后改为硬失败）。
set -u

if ! .venv/bin/alembic upgrade head; then
    echo "[entrypoint] WARN: alembic upgrade 失败（旧版本库未 stamp？），继续启动并由 schema_ensure 兜底" >&2
fi

exec "$@"
