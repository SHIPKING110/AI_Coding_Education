# 上线发布检查单（Release Checklist）

> 配套文档：部署手册 [DEPLOY.md](../DEPLOY.md) · 冒烟清单 [smoke-checklist.md](smoke-checklist.md) · 恢复演练 [restore_drill.md](../backend/scripts/restore_drill.md) · 加固计划 [architecture-v2-hardening.md](plan/architecture-v2-hardening.md)
>
> 适用：单机 Docker Compose 部署（M-B 之后的标准流程）。每次正式发版逐项打勾并在发布记录里留痕。

## 一、发版前三道闸（缺一不可）

### 1. 代码闸（CI 全绿）

- [ ] 后端：`ruff` 零告警；空库 `alembic upgrade head` 一次成功；`pytest` 全量通过且 `--cov-fail-under` 达标（当前护栏 63%）
- [ ] 前端：`eslint` 0 问题；`vitest` 全绿；`vue-tsc -b && vite build` 通过
- [ ] 变更涉及迁移：新迁移从基线 `a00000000000` 串联，本地空库重放 + `--autogenerate` 零 diff

### 2. 评测闸（RAG/Agent 变更必跑）

- [ ] 基线运行 → 人工复核（≥10 对，Kappa ≥0.6）→ 发行候选运行
- [ ] `GATE_SET_NAME="行舟-家长客服回归集" make release` exit 0（判定规则见 DEPLOY.md §6）

### 3. 备份闸

- [ ] 发布窗口前手工执行一次 `backend/scripts/backup.sh`（或确认当日 cron 成功），备份文件校验通过
- [ ] 若涉及表结构：核对最近一次恢复演练记录（≤1 个季度）

## 二、发布窗口（服务器操作）

- [ ] 记录当前版本：`git describe --tags` / 镜像 tag 留档
- [ ] 存量库首次升级（仅 M-B 上线这一窗口需要，一次性）：按 DEPLOY.md §3 执行
      备份 → 零漂移比对 → `alembic stamp a00000000000` → 重启
- [ ] `.env.prod` 确认：`SECRET_KEY` 强随机、`DEBUG=false`、`SCHEMA_ENSURE_MODE=verify`、`CORS_ORIGINS` 按部署形态
- [ ] `docker compose up -d --build`；观察 `docker compose logs -f backend`：
      - [ ] 入口日志显示 `alembic upgrade head` 成功（或已是最新）
      - [ ] 无 schema 校验告警（`verify` 模式应当零告警）
      - [ ] 无启动异常/循环重启

## 三、发版后验证（15 分钟内完成）

- [ ] `GET /api/health` 200；首页可登录
- [ ] 冒烟清单 [smoke-checklist.md](smoke-checklist.md) A–F 全过（P0）
- [ ] 审计日志：后台能查到本次测试操作记录（写入链路正常）
- [ ] 关键页面抽查：排课列表、课后反馈、订单支付、RAG 后台（如变更涉及）
- [ ] 观察 30 分钟：错误日志无新增高频异常、慢查询无明显堆积（`docker compose logs backend | grep ERROR`）

## 四、回滚预案（触发即执行，不等待排查完）

**触发条件（任一）**：健康检查持续失败 >5 分钟；核心链路（登录/排课/支付）不可用；数据损坏迹象；评测闸后线上指标显著劣化。

**回滚步骤**（详见 DEPLOY.md §7）：

1. `git checkout <上一个通过闸门的 tag>` → `docker compose up -d --build`；
2. 数据问题才动数据：按 `restore_drill.md` 先恢复到临时库验证，再切库；
3. **禁止 `alembic downgrade`**（基线 downgrade 会清空业务表）；
4. RAG/评测类问题：后台「RAG → 设置」一键回滚配置版本，不回滚代码；
5. 回滚完成后同样跑一遍冒烟 A–F，记录事故时间线与原因。

## 五、发布记录模板

```text
日期：YYYY-MM-DD
版本：git tag / commit
变更摘要：（一句话）
三道闸：CI ✅ 评测 ✅ 备份 ✅（闸门 exit code / 备份文件名）
窗口操作：stamp ✅ / 无迁移
冒烟：A–F 全过（执行人）
观察期结论：正常 / 异常（处理方式）
回滚：无 / 已回滚（原因）
```
