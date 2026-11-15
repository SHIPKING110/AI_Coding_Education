#!/usr/bin/env bash
# 生产备份脚本：PostgreSQL 全量 dump + uploads 素材归档 + 保留策略 + 校验。
#
# 用法（服务器 cron / systemd timer 每日执行）：
#   DATABASE_URL='postgresql+psycopg://user:pass@localhost:5432/child_code' \
#   BACKUP_DIR=/data/backups KEEP_DAYS=30 backend/scripts/backup.sh
#
# 退出码非 0 = 备份失败（cron 邮件 / 监控告警接入此信号）。
set -euo pipefail

DATABASE_URL="${DATABASE_URL:?请设置 DATABASE_URL}"
BACKUP_DIR="${BACKUP_DIR:-/data/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
UPLOAD_DIR="${UPLOAD_DIR:-$(cd "$(dirname "$0")/.." && pwd)/uploads}"

TS="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# 从 SQLAlchemy URL 提取 pg_dump 连接串（去掉 +psycopg 方言标记）
PG_URL="${DATABASE_URL/postgresql+psycopg/postgresql}"

echo "[backup] $(date '+%F %T') 开始：db -> ${BACKUP_DIR}/db_${TS}.dump"
pg_dump --format=custom --compress=6 --no-owner --no-privileges \
    --file "${BACKUP_DIR}/db_${TS}.dump" "$PG_URL"

# 校验 dump 可读（能列出目录即视为完整）
pg_restore --list "${BACKUP_DIR}/db_${TS}.dump" > /dev/null
echo "[backup] db dump 校验通过"

if [ -d "$UPLOAD_DIR" ]; then
    echo "[backup] uploads -> ${BACKUP_DIR}/uploads_${TS}.tar.gz"
    tar -czf "${BACKUP_DIR}/uploads_${TS}.tar.gz" -C "$(dirname "$UPLOAD_DIR")" "$(basename "$UPLOAD_DIR")"
else
    echo "[backup] WARN: UPLOAD_DIR 不存在：$UPLOAD_DIR（跳过素材归档）" >&2
fi

# 保留策略：删除超过 KEEP_DAYS 的备份
find "$BACKUP_DIR" -name 'db_*.dump' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'uploads_*.tar.gz' -mtime +"$KEEP_DAYS" -delete

echo "[backup] $(date '+%F %T') 完成：db_${TS}.dump"
echo "[backup] 最近备份："
ls -lh "$BACKUP_DIR" | tail -5
