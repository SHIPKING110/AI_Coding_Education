# 生产部署手册（DEPLOY）

目标：单机 Docker Compose 一键起生产环境（Postgres + 后端 + 前端同域反代）。

## 1. 前置要求

- 服务器安装 Docker Engine 24+（含 compose v2 插件），开放 80/443（或自定义 `WEB_PORT`）。
- 如需 HTTPS，自行在 `web` 前加反代（如 Nginx/Caddy）做证书，本 compose 默认 HTTP。

## 2. 首次部署（约 5 分钟）

```bash
# 1) 取代码
git clone <repo> && cd Child_Code

# 2) 填写生产配置（逐项改，尤其是三个“请替换”）
cp .env.prod.example .env.prod
# SECRET_KEY 换随机值：python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3) 构建并启动（首次含 npm build + pip install，约 3-8 分钟）
docker compose --env-file .env.prod up -d --build

# 4) 创建首个管理员（幂等，可重复执行）
docker compose exec backend .venv/bin/python scripts/seed_admin.py

# 5) 打开 http://服务器IP:8080（或 WEB_PORT）登录
```



## 3. 表结构同步（ADR-0029：Alembic 基线接管）

- 新库：容器入口自动执行 `alembic upgrade head`（基线与 ORM 模型一致），无需手工操作。
- **存量库首次升级（一次性，发布窗口内）**：
  1. 先备份（见第 5 节 `backup.sh`）；
  2. 快照比对零漂移：用旧库结构对照基线 `alembic upgrade head --sql > diff.sql` 人工核对无意外 DDL；
  3. `docker compose exec backend /srv/app/.venv/bin/python -m alembic stamp a00000000000`；
  4. 重启后端，入口会自动 `upgrade head`（幂等）。
- 启动期 schema 策略由 `SCHEMA_ENSURE_MODE` 控制：
  - `auto` = 旧行为（自动建表/补列，兼容尚未 stamp 的库，过渡期默认）；
  - `verify` = 只读校验并告警，不执行任何 DDL（**存量库 stamp 验证通过后切换，推荐**）；
  - `off` = 完全跳过。
- 旧 alembic 迁移链已归档到 `backend/alembic/legacy_versions/`，不参与执行。



## 4. 已知生产约束（重要）

- **单 worker**：AI 出题/评估任务状态在进程内存，多 worker 会导致建任务与轮询落到不同进程。需要扩容时，先把任务状态外置（DB/Redis）再加 worker。
- **AI 重型依赖不在镜像内**：langchain/chromadb/sentence-transformers（torch，体积大）未进生产镜像，相关 AI 增强走兜底；PPT/PDF/DOCX 导出依赖已包含，正常可用。如需完整 AI 能力，服务器可科学上网后在镜像构建时加 --extra ai。
- **微信推送**：未接入（需商户资质），通知走应用内站内信。



## 5. 日常运维

```bash
docker compose ps                    # 看状态
docker compose logs -f backend       # 看后端日志
docker compose up -d --build         # 发版更新
```

**备份（标准化脚本，推荐）**：`backend/scripts/backup.sh`（pg_dump custom 格式 + uploads 归档 + 完整性校验 + 保留 30 天），接入 cron：

```bash
# 每日 02:30
30 2 * * * /srv/Child_Code/backend/scripts/backup.sh >> /var/log/child_code_backup.log 2>&1
```

**恢复演练（季度）**：按 `backend/scripts/restore_drill.md` 在临时库恢复并核对行数/版本号，记录留档。
手工应急备份仍可用：

```bash
docker compose exec db pg_dump -U app child_code > backup-$(date +%F).sql
cat backup.sql | docker compose exec -T db psql -U app child_code
docker run --rm -v child_code_uploads:/data -v $(pwd):/bak alpine tar czf /bak/uploads-$(date +%F).tgz /data
```



## 6. 生产 checklist（上线前逐项打勾）

> 完整发布流程（发版前/窗口内/发版后/回滚预案）见 **[docs/release-checklist.md](docs/release-checklist.md)**；本节保留核心勾选项。

- [ ] `SECRET_KEY` / `POSTGRES_PASSWORD` / `SEED_ADMIN_PASSWORD` 均为随机强密码
- [ ] `DEBUG=false`；`.env.prod` 未提交版本库
- [ ] 如前后端分域名：`CORS_ORIGINS` 填前端域名；同域反代可留空
- [ ] LLM key 按需配置（不配则 AI 出题/评估走兜底，不影响主流程）
- [ ] `SCHEMA_ENSURE_MODE`：存量库 stamp 验证通过后置为 `verify`
- [ ] 备份 cron 已接 `backend/scripts/backup.sh`（数据库 + uploads）；恢复演练记录 ≤1 个季度
- [ ] 首个 admin 已创建；`SEED_ADMIN_*` 可从 `.env.prod` 删除
- [ ] CI 全绿：后端 `ruff` + `alembic upgrade head`（空库）+ `pytest --cov-fail-under`；前端 `lint` + `test` + `build`
- [ ] **发布冒烟**：`docs/smoke-checklist.md` A–F 全过
- [ ] **审计日志可用**：后台「审计日志」能查到最近操作（`GET /api/audit/logs` 仅管理员）
- [ ] **评测闸门通过**：`GATE_SET_NAME="行舟-家长客服回归集" make release`（闸门与证据校验失败都会中止发版；手动校验 `docker compose exec backend /srv/app/.venv/bin/python -m scripts.deploy_gate --set-name <名> --require-answer --require-calibration --require-baseline` exit 0）

### 评测闸门（部署前必跑）

推荐直接用发版 wrapper（构建新镜像 → 用新镜像跑闸门 → 通过才上线）：

```bash
GATE_SET_NAME="行舟-家长客服回归集" make release
```

标准发布顺序（缺一不可）：

1. **基线运行**：家长客服集，hybrid + rerank on + answer_eval on，检索口径=家长索引（`domain=parent_service` 自动）；
2. **人工复核**：按分层抽样协议复核 ≥10 对（目标 12 对），Kappa ≥ 0.6；
3. **发行候选运行**：同集合、同配置再跑一次；
4. `make release`（wrapper 会带 `--require-answer --require-calibration --require-baseline`，证据缺失直接阻断）。

等价手动流程与排障命令（注意 `python` 需用 venv 路径，镜像内 PATH 指向的系统 Python 没有依赖）：

```bash
# 闸门通过返回 0；未通过返回 1 并打印原因；无运行返回 2
docker compose exec backend /srv/app/.venv/bin/python -m scripts.deploy_gate --set-id <评测集UUID>
docker compose exec backend /srv/app/.venv/bin/python -m scripts.deploy_gate --set-name "行舟-家长客服回归集" --json

# 历史运行对比
docker compose exec backend /srv/app/.venv/bin/python -m scripts.compare_eval_runs <评测集UUID>

# 库内标注与仓库 JSONL 对齐（早期导入丢过 split/criticality 字段；默认 dry-run）
docker compose exec backend /srv/app/.venv/bin/python -m scripts.sync_eval_case_meta \
  --set-name "行舟-家长客服回归集" --dataset evals/datasets/zhouxing_parent_eval.jsonl
```

判定规则：冻结集/关键用例 hit@3 较上次下降 >2pp、无依据回答率 >5%、检索异常率 >0.1%、或人工复核 ≥10 对时 Kappa <0.6，均判 fail，应回滚到上一个通过的配置版本（后台「RAG → 设置」可一键回滚）。应急时可 `make release` 不带 GATE_SET_NAME 跳过闸门（会打印警告，不推荐）。

> 家长客服集的冻结集构成：14 条关键用例 + 6 条高频稳定用例 = 20 条，冻结后不再修改；调参只在剩余 31 条回归用例上进行。评测运行的检索口径会显示在运行表「模式 / 口径」列，家长集默认打家长索引（`parent_knowledge__*`）。



## 7. 回滚

```bash
# 代码回滚：回到上一个通过闸门的 tag/commit，重建镜像
git checkout <上一个tag/commit> && docker compose up -d --build
```

规则与优先级：

1. **优先应用层回滚**（上面命令），数据不回滚：大多数问题（逻辑 bug/UI 回归）修完重发即可；
2. **禁止对生产库执行 `alembic downgrade`**：基线 downgrade 会清空业务表；结构回退一律走「备份恢复」；
3. 数据回滚用第 5 节备份恢复（custom 格式：`pg_restore -d <临时库>` 先验证，再切库）；注意新代码产生的数据可能与旧代码不兼容，**必须先在测试环境验证**；
4. 评测/检索类问题不走代码回滚，直接在后台「RAG → 设置」一键回滚配置版本（见评测闸门判定规则）。

