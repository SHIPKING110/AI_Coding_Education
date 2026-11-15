# Architecture V2 加固路线图（architecture-v2-hardening）

> 唯一进度台账在 `.tasks/current.md`（每批次完成即更新）；本文件是**计划与验收口径**的稳定快照，评审/排期以本文件为准。
> 关联：ADR-0029（Alembic re-baseline）、ADR-0028（Agent 评测闸门）。

## 总览

| 里程碑 | 内容 | 状态 |
| ------ | ---- | ---- |
| M-A 安全合规基线 | 注册收紧、密码策略+强制改密、限速、Media 签名、SECRET_KEY 校验、安全头、审计日志、历史清洗脚本 | ✅ 2026-11-15 完成 |
| M-B 工程与交付 | Alembic re-baseline、容器入口迁移、备份与恢复演练、CI | 🔄 进行中 |
| WS1 可复现交付 | 迁移治理、部署脚本化、监控告警 | 🔄 部分完成（见下） |
| WS2 前端质量 | ESLint 体系 + 类型债清零（any/unused 归零并提级 error） | ✅ 2026-11-15 完成 |
| WS3 测试体系 | 前端 Vitest 基建 + 后端覆盖率基线 65% + CI 护栏 | ✅ 2026-11-15 完成（Agent 模块持续补测） |
| WS4 文档治理 | ADR 索引重建 + API 总览自动生成（403 端点） | ✅ 2026-11-15 完成 |
| WS5 性能 | echarts 按需引入（路由包 601→34KB）+ 索引盘点（无需新增） | ✅ 2026-11-15 完成 |
| WS6 上线检查单 | 发布前三道闸 + 发布窗口 + 发版后验证 + 回滚预案（docs/release-checklist.md） | ✅ 2026-11-15 完成 |

## M-A 验收记录（已完成）

- 0.1 注册收紧：`/auth/register` 登录态感知，未登录默认拒绝（`ALLOW_SELF_REGISTRATION`）；空库引导可建初始管理员
- 0.2 密码策略 + 强制改密：强度校验（≥8、字母+数字、拒弱口令）；`must_change_password` 门禁（仅放行 `/auth/me`、`/auth/me/password`）；代建账号一次性临时密码；前端 `ForcePasswordDialog`
- 0.3 限速：登录 IP/账号双维度、注册、刷新（nginx auth_zone 兜底）
- 0.4 Media 签名：HMAC 签名 URL，中间件自动签名，`POST /api/media/sign`
- 0.5 SECRET_KEY 强校验 + secretbox `v1:` 版本化与轮换兼容
- 0.7 安全响应头（后端 + nginx），HSTS 待 HTTPS 启用
- 0.8 审计日志：`audit_logs` 表 + `services/audit.py`（脱敏、截断、失败不阻断）；挂钩建号/改密/重置/权限/职务/设置/知识库删除；`GET /api/audit/logs`（仅管理员）
- 0.6 历史清洗脚本已备（`purge_backups_from_history.ps1`），待人工确认执行
- 验证：`tests/test_security_hardening.py` 20 例 + `tests/test_audit_log.py` 3 例；后端全量 355 通过/1 跳过；前端 vue-tsc + vite build 通过

## WS1 可复现交付（进行中）

### 1.1 Alembic re-baseline（✅ 2026-11-15）

- 基线 `a00000000000_baseline_full_schema`（`down_revision=None`），ORM 模型为唯一事实源；`upgrade()` 探测 `users` 表保证幂等
- 旧 67 个迁移移入 `backend/alembic/legacy_versions/`（仅留档，不参与执行）
- 验收：空库 `alembic upgrade head` 一次成功；`--autogenerate` 对基线库零 diff；开发库已 `stamp` 到基线
- **待办**：8080 生产库（`c0ffee000052`）在发布窗口按 DEPLOY 流程 `alembic stamp a00000000000`（先快照比对零漂移再 stamp）

### 1.2 容器入口迁移（✅ 代码完成，待 8080 验证）

- `backend/entrypoint.sh`：`alembic upgrade head` → `exec uvicorn`；旧库未 stamp 时告警继续（过渡期），M-B 收口后改硬失败
- Dockerfile 增加 `ENTRYPOINT`

### 1.3 schema_ensure 降级为只读校验（✅ 代码完成，待 8080 切换）

- 新增 `SCHEMA_ENSURE_MODE`（auto/verify/off，过渡期默认 auto 保持兼容）
- `verify` 模式：`verify_business_schema()` 只读比对模型 vs 库（缺表/缺列），差异仅告警「请执行 alembic upgrade head」，零 DDL
- 回归：`tests/test_schema_mode.py` 3 例（一致零差异、缺表识别且不自动重建、缺列识别）
- **待办**：8080 完成基线 stamp 后把 `.env` 切 `verify`；稳定一个发布周期后考虑移除 auto 分支

### 1.4 备份与恢复演练（✅ 脚本完成，待服务器定时接入）

- `backend/scripts/backup.sh`：pg_dump custom + uploads 归档 + 校验 + 保留 30 天
- `backend/scripts/restore_drill.md`：季度演练手册（临时库恢复、行数核对、版本号核对、记录模板）
- **待办**：服务器 cron/systemd timer 接入 + 首次演练记录

### 1.5 CI（✅ 工作流已建，待首次流水线验证）

- `.github/workflows/ci.yml`：后端（ruff + 空库迁移重放 + pytest 全量，PG16 service）、前端（npm ci + build）、Docker 构建冒烟
- **待办**：推送到远端后确认首次绿灯；评测闸门（deploy_gate）接入 CD 留到 WS6

## WS2 前端质量基线（✅ 完成 2026-11-15）

### 2.1 ESLint 落地（✅ 2026-11-15）

- ESLint 9 flat config（`frontend/eslint.config.js`）：`js.recommended` + `typescript-eslint.recommended` + `vue/flat/essential`
- 存量债口径：`no-explicit-any`、`no-unused-vars` 降为 **warn**（可见、不阻断），其余 recommended 规则维持 error
- 基线（2026-11-15）：**0 error / 239 warning**（any 214、unused-vars 25，涉及 38 个文件）；目标每批次只降不升
- `npm run lint` 已接入 CI 前端 job（error 阻断）

### 2.2 仓库卫生（✅ 2026-11-15）

- 移除误提交的 tsc 产物：`vite.config.js`、`vite.config.d.ts`、`tsconfig.node.tsbuildinfo`；`.gitignore` 补 `frontend/vite.config.js|d.ts`
- `tsconfig.node.json` 改为产物/缓存落 `node_modules/.tmp`（修复 TS6310 引用项目 noEmit 冲突）
- 根目录一次性脚本（`check_compare.cjs` 等 3 个）移入 `frontend/scripts/`

### 2.3 any 债收敛（✅ 完成 2026-11-15，四批清零）

- 第一批：`src/api/ragAdmin.ts` 全量类型化（12 个接口），评测动态指标收口为唯一 `EvalMetricsBag`（214 → 194）
- 第二批：`apiErrorDetail`/`apiErrorStatus` 统一错误提取；4 视图清零（194 → 128）
- 第三批：4 视图清零（128 → 86）
- 第四批（扫尾全量）：
  - 21 个文件统一 catch 收敛 + 8 个遗留视图/组件类型化（Mermaid 用 `typeof import` 模块类型、ECharts formatter unknown 收窄、judge_results 用 `JudgeEntry`/`EvalAnswerBag` 显式接口、家长会话/RAG 路由用 ragAdmin 接口）
  - 顺带清理 ~12 个 dead code 函数/常量（离屏片预览簇、goAssignments、fmtDate 等）
  - 修复 2 个被 any 掩盖的潜在 bug（家长会话 `selected.thread_id` 应为 `selected.thread.thread_id`）
- **终态：`no-explicit-any` 214 → 0，`no-unused-vars` 25 → 0，error/warn 全归零**
- 规则提级：`no-explicit-any` 与 `no-unused-vars` 已从 warn 改为 **error**（新债直接阻断 CI）
- 每批均验证：`eslint src` 0 问题、`vue-tsc -b` 零错误、`vite build` 通过

## WS3 测试体系（进行中）

### 3.1 前端 Vitest 基建（✅ 2026-11-15）

- 引入 Vitest 3 + `@vue/test-utils` + happy-dom；`vitest.config.ts`（`include: src/**/*.spec.ts`，`@` 别名对齐）
- `npm run test` 已接入 CI 前端 job（与 lint/build 并列）
- 首批 21 例：`utils/date`（本地时间契约，防 UTC 跨日偏移回归）、`utils/errors`（错误提取三函数）、`utils/pinyin`（近似映射实际契约）、`stores/toast`（Pinia store + 定时器）

### 3.2 后端覆盖率基线（✅ 基线建立 2026-11-15）

- `pytest-cov` 加入 dev 依赖；分块 append 跑全量：**358 通过 / 1 跳过，覆盖率 65%**
- 模块级明细已出（`coverage report --sort=cover`）；低覆盖集中在 LLM/Agent 重资产模块（agent_eval_runner 12%、agent_memory 17%、agent_chat 18%、crud/agent 21%、parent_service router 22%、skill_exec 22%）——均依赖外部模型调用，靠 mock 逐步补
- 首批补测：`tests/test_knowledge_crud.py` 9 例（文档生命周期/可见性/收录幂等/家长白名单），`crud/knowledge.py` 31% → 72%；`tests/test_retrieval_config_crud.py` 6 例（Embedding 单例 upsert/密钥加密/指纹稳定性/local 模式守卫/家长与教师 rerank），`crud/retrieval_config.py` 46% → 89%
- 排障备注：`DATABASE_URL` 环境变量残留曾污染测试（指向已删库），已明确「跑测试前清除 env 覆盖」

### 3.3 覆盖率护栏（✅ 2026-11-15）

- CI 后端 pytest 已加 `--cov=app --cov-fail-under=63`（基线 65%，留 2pp 波动余量，只升不降）

## WS4 文档治理（✅ 2026-11-15）

### 4.1 ADR 索引重建（✅）

- 修正 `docs/adr/README.md`：原索引仅列 8/27 条；重建全量 27 条（0001–0029，除 0005/0006 空号），
  修正 0015–0018 因 BOM 导致标题缺失的问题，并注明空号来源

### 4.2 API 端点总览（✅）

- 新增 `scripts/gen_api_overview.py`：从 `app.openapi()` 生成 `docs/api-overview.md`（**403 个端点**，按前缀分组）
- 兼容新版 FastAPI `_IncludedRouter` 惰性路由（遍历 `app.routes` 拿不到子路由，改走 OpenAPI schema）
- 重新生成方式写入文档头；README「文档导航」已挂链接

### 4.3 文档入口对齐（✅）

- 根 `README.md` 文档导航补充：API 总览、架构加固计划入口

## WS5 性能体检（✅ 2026-11-15）

### 5.1 前端包体（✅）

- **FinanceView 路由 chunk 601 KB → 34 KB**：`import * as echarts from 'echarts'` 全量引入改为 `echarts/core` + 按需注册（Bar/Line + Grid/Legend/Tooltip + CanvasRenderer，echarts v6 无独立轴组件）；echarts 运行时与 usage 看板共享按需 chunk，仅这两个页面加载
- 首屏 `index` chunk 稳定 188 KB；Mermaid 全家族（elk 1.4MB / cytoscape / katex 等）均按需加载（仅渲染图表时拉取），不阻塞首屏
- 验证：`vue-tsc` 零错误、eslint 零告警、build 通过

### 5.2 后端查询索引盘点（✅ 结论：无需新增）

- 热点表索引核对：schedules（class/teacher/start_time）、feedbacks、assignments 全链 FK、orders（student/status）均已建索引
- `expire_stale_orders` 每分钟轮询走 status 索引，pending 子集小，当前规模无需 expires_at 复合索引
- 低风险结论：现阶段不加索引；数据量增长后按 pg_stat_statements 再评估

### 5.3 持续项（⬜）

- 接口 P95 基线（真实数据量下）待生产观测数据接入后再定阈值；前端 manualChunks 拆分（mermaid 家族内部）收益低，暂不做

## WS6 上线检查单（✅ 2026-11-15）

### 6.1 发布检查单（✅）

- 新增 `docs/release-checklist.md`：发版前三道闸（CI / 评测闸 / 备份闸）→ 发布窗口（stamp 流程/环境变量核对/启动日志观察）→ 发版后 15 分钟验证（健康检查 + 冒烟 A–F + 审计日志抽查）→ 回滚预案（触发条件/优先级/禁令）→ 发布记录模板

### 6.2 部署手册修正（✅）

- `DEPLOY.md` 三处过时内容更新：
  - §3 表结构同步：`create_all` 描述 → Alembic 入口迁移 + 存量库 stamp 一次性流程 + `SCHEMA_ENSURE_MODE` 三档说明
  - §5 运维：备份改为 `scripts/backup.sh` cron 标准化 + 季度恢复演练引用
  - §6/§7：checklist 增补（verify 模式/CI 全绿/冒烟/审计日志），回滚规则明确「优先应用层回滚、禁止 alembic downgrade、RAG 走配置版本回滚」

### 6.3 CI 后端闸修正（✅）

- 首推前的全量 `ruff check app tests` 暴露 202 个存量问题（CI 从未真正跑过）：
  - 自动修复 47 处（import 排序 I001/UP017/E702 等）；手工清理 F841 死变量 ×4、E741 歧义变量、E702 分号 ×10
  - **揪出 2 个潜在运行时 bug**：`finance.py` 缺 `status` import（教师无权限时 NameError 而非 403）、`crud/report.py` 字典键 `expected` 重复
  - `E501`（行宽）在 pyproject 显式豁免并注明原因（存量长中文注释全库重排风险大于收益）
- 新增 `.gitattributes`（`* text=auto eol=lf`，ps1/bat 保留 CRLF），统一行尾避免后续 diff 噪音
- 修复后回归：两批 169 例（含 agent/finance/report/knowledge 全链）全过

## 风险登记

| 风险 | 缓解 |
| ---- | ---- |
| 存量环境漏 stamp 直接升级 | entrypoint 过渡期容错 + DEPLOY 文档 + 发布窗口人工核对 `alembic current` |
| 基线 downgrade 清空全表 | 生产禁止 downgrade；回退依赖备份（1.4） |
| 多分支迁移分叉 | 新迁移统一从基线串联；冲突 rebase 生成新 revision |
| 审计日志增长 | 后续按月归档/分区（WS4 性能项一并处理） |

## 明确不做（本阶段）

- 不引入 Redis/Celery（任务状态外置留到 P4）
- 不做多 worker（同上）
- 不重写 git 历史（0.6 需用户确认后单独执行）
