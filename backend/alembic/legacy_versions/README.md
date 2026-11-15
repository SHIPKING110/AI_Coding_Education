# 历史迁移归档（legacy_versions）

本目录是 **Alembic re-baseline（ADR-0029）之前的 67 个迁移文件**，仅作追溯留档：

- 不参与 `alembic upgrade`（Alembic 只扫描 `../versions/`）；
- 空库/新环境由 `versions/a00000000000_baseline_full_schema.py` 一次性建全量 schema；
- 存量库升级前执行一次 `alembic stamp a00000000000`（见 `docs/adr/adr-0029-alembic-rebaseline.md`）；
- **禁止修改本目录文件**；schema 变更请新建迁移，并遵守幂等探测约定。
