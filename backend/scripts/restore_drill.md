# 备份恢复演练手册（restore drill）

> 目标：季度执行一次，验证「备份可用 + 恢复流程熟练」。RPO 目标 ≤24h（WAL 增量落地后收紧到 15min）。
> 演练使用**临时库**，不触碰生产库；全程记录耗时。

## 前置

- 服务器上存在最近一次 `db_*.dump` 与 `uploads_*.tar.gz`（`backend/scripts/backup.sh` 产物）。
- 已知 `DATABASE_URL`（生产库账号建议演练用只读权限+临时库建库权限的账号）。

## 演练步骤

1. **建临时库**

```bash
createdb -h localhost -U postgres child_code_restore_drill
```

2. **恢复 dump**（记录耗时）

```bash
pg_restore --clean --if-exists --no-owner --no-privileges \
  -h localhost -U postgres -d child_code_restore_drill /data/backups/db_<TS>.dump
```

3. **校验数据完整性**（与生产库对比，允许当日新增差异）

```sql
SELECT count(*) FROM users;
SELECT count(*) FROM students;
SELECT count(*) FROM orders;
SELECT count(*) FROM lesson_records;
SELECT max(created_at) FROM lesson_records;
```

4. **校验素材归档**

```bash
mkdir -p /tmp/drill_uploads
tar -xzf /data/backups/uploads_<TS>.tar.gz -C /tmp/drill_uploads
ls /tmp/drill_uploads/uploads | head
```

5. **版本号核对**

```bash
psql -d child_code_restore_drill -c "SELECT version_num FROM alembic_version;"
# 期望：a00000000000（ADR-0029 基线之后）
```

6. **清理**

```bash
dropdb child_code_restore_drill
rm -rf /tmp/drill_uploads
```

## 记录模板

| 日期 | 备份时间戳 | dump 大小 | 恢复耗时 | 行数核对 | 版本号 | 结论 | 执行人 |
| ---- | ---------- | --------- | -------- | -------- | ------ | ---- | ------ |
|      |            |           |          |          |        |      |        |

## 异常处理

- `pg_restore` 报对象已存在：确认 `--clean --if-exists` 生效，或重建临时库；
- 恢复后 `alembic_version` 为空：执行 `alembic stamp a00000000000`（ADR-0029）；
- dump 校验失败（`pg_restore --list` 报错）：备份损坏 → 立即排查磁盘/备份任务，重跑备份并告警。
