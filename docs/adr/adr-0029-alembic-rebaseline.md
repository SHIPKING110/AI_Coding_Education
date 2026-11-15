# ADR-0029：Alembic re-baseline —— 以 ORM 模型为唯一事实源重建迁移基线

## 状态

已采纳（2026-11-15）

## 背景

迁移体系长期是「双轨制」：应用启动用 `create_all + schema_ensure(ADD COLUMN)` 兜底，
Alembic 迁移链作为并行副本维护。评审（2026-11 上线标准评估）确认了三类问题：

1. **空库不可重放**：迁移链在 `c0ffee000024` 即断（依赖 create_all 预建的
   `teacher_permissions` 表），从 0 执行 `alembic upgrade head` 必失败；
2. **链上大量非幂等**：`create_table`/`add_column` 未探测存在性（如 031 的
   `sandbox_settings`、032 的 `workspace_id`），与 create_all 同时存在时互相踩踏；
3. **版本号漂移**：开发库停在 `c0ffee000023`、8080 生产库停在 `c0ffee000052`，
   与代码实际 schema（create_all 已补齐）不一致，迁移记录失去可信度。

## 决策

**重建单一基线，ORM 模型成为 schema 唯一事实源：**

- 以当前 ORM 模型 `Base.metadata` 对空库 autogenerate 生成基线
  `a00000000000_baseline_full_schema`（`down_revision=None`），一次性建全量 schema；
- 基线 `upgrade()` 首行探测 `users` 表：已存在则跳过（兼容「应用先启动 create_all」的旧部署路径），保持幂等；
- 旧 67 个迁移文件移入 `backend/alembic/legacy_versions/`（不参与执行，仅留档追溯）；
- **存量库迁移路径**：升级前执行一次 `alembic stamp a00000000000`（版本号对齐，不执行 DDL）；
- 容器启动改为 `entrypoint.sh`：`alembic upgrade head` 后启动 uvicorn；
  旧库未 stamp 时 upgrade 失败仅告警并继续（schema_ensure 兜底），M-B 完成后改为硬失败；
- 之后所有 schema 变更必须走「模型 + 新迁移（带幂等探测）」双更新，CI 校验空库重放。

## 验收记录（2026-11-15）

- 空库 `alembic upgrade head` 一次成功，`alembic current` = `a00000000000 (head)`；
- 对基线库再跑 `--autogenerate` 为空（模型与基线零漂移）；
- 开发库已 `stamp` 到基线；8080 生产库在下次发布窗口按 DEPLOY 流程 stamp。

## 风险与对策

- **漏改迁移的存量环境**：stamp 前先跑 `alembic upgrade --sql` 人工比对或用
  `autogenerate` 对现网快照做 diff 校验，确认零漂移再 stamp；
- **多分支并行开发**：基线后新增迁移从 `a00000000000` 向下串联，冲突时 rebase 生成新 revision；
- **回退**：基线 downgrade 会清空全部业务表，生产禁止执行；回退依赖数据库备份（WS1-1.4 备份脚本）。
