# 架构决策记录（ADR）

本目录记录 Child Code 项目里**难以逆转、影响面较大**的技术/产品决策。
每条 ADR 记录：背景（Context）、决策（Decision）、理由（Rationale）、后果（Consequences）。

约定：
- 文件名 `adr-NNNN-简短标题.md`，编号只增不改。
- 一旦某条决策被推翻，不改原文，而是新增一条 ADR 并在旧条目顶部标注 `已被 ADR-XXXX 取代`。

## 索引

| 编号 | 标题 | 状态 |
| --- | --- | --- |
| [ADR-0001](adr-0001-assistant-business-tools.md) | 智能助手接入业务数据 —— 本地工具（Skill）层 | 已采纳 |
| [ADR-0002](adr-0002-assistant-tool-planning.md) | 智能助手工具「规划层」——多轮 规划 → 执行 → 观察 | 已采纳 |
| [ADR-0003](adr-0003-assistant-sql-tool.md) | 智能助手数据库查询工具 —— 只读 SQL + 多步取数 | 已采纳 |
| [ADR-0004](adr-0004-tool-list-integrity.md) | 名单类工具的完整性与截断语义 | 已采纳 |
| [ADR-0007](ADR-0007-report-rollup-seed.md) | 报告链路数据源与轻量年度种子 | 已接受 |
| [ADR-0008](ADR-0008-unified-agent-protocol.md) | 统一 Agent 运行协议 | 已接受 |
| [ADR-0009](ADR-0009-agent-conversation-persistence.md) | Agent 会话与记忆持久化到 Postgres | 已接受 |
| [ADR-0010](ADR-0010-local-embedding-chroma.md) | 本地 Qwen3-Embedding-0.6B + Chroma 持久化作为 RAG 底座 | 已接受 |
| [ADR-0011](ADR-0011-knowledge-base-model.md) | 知识库模型——Document / KnowledgeBase / Plaza / Collection | 已接受 |
| [ADR-0012](adr-0012-agent-web-search.md) | Agent 联网搜索（Tavily）的边界与驱动方式 | 已采纳 |
| [ADR-0013](adr-0013-agent-workbench-fixes.md) | Agent 工作台修复——Skill 广场一致执行 / 乱码净化 / 大纲对齐 / 附件呈现 | 已采纳 |
| [ADR-0014](adr-0014-ppt-master-adapter.md) | ppt-master 兼容适配版（工作台 one-shot 包装） | 已采纳 |
| [ADR-0015](adr-0015-ppt-stability-workbench.md) | PPT 生成稳定性与工作区融合（续作意图/自动出片/产物隔离/预览融合） | 已采纳 |
| [ADR-0016](adr-0016-skill-permission-session-scope.md) | Agent Skill 权限界定 + 工作区按会话一致刷新 | 已采纳 |
| [ADR-0017](adr-0017-skill-shadowing-and-nudge.md) | 同名 Skill 遮蔽 + 会话粘性出片 | 已采纳 |
| [ADR-0018](adr-0018-default-agent-cleanup-local-exec.md) | 默认 PPT Agent + 会话删除清理 + 大 Skill 本地执行 + 防跑偏 | 已采纳 |
| [ADR-0019](adr-0019-ppt-quality-regression-fix.md) | PPT 输出质量回归修复（SVG↔大纲对齐 / 空回复兜底 / 防跑偏） | 已采纳 |
| [ADR-0020](adr-0020-admin-observability-rag-metrics.md) | 后台管理 / RAG 运营观测与指标口径 | 已采纳 |
| [ADR-0021](adr-0021-parent-embedding-and-ppt-metrics.md) | 家长客服专属 Embedding 与 PPT 页数对齐口径修复 | 已采纳 |
| [ADR-0022](adr-0022-parent-eval-acceptance-protocol.md) | 家长客服评测验收协议（检索口径 / 冻结集 / Kappa / 发布证据） | 已采纳 |
| [ADR-0023](adr-0023-parent-retrieval-keep-hybrid.md) | 家长客服检索维持 Hybrid（Dense vs Hybrid A/B 结论） | 已采纳 |
| [ADR-0024](adr-0024-eval-review-dialog.md) | 评测逐条复核改为弹窗连评（含检索视角） | 已采纳 |
| [ADR-0025](adr-0025-mermaid-render-local.md) | Mermaid 图表渲染本地化（npm 打包 + 懒加载） | 已采纳 |
| [ADR-0026](adr-0026-eval-calibration-rubric-and-keyword-metrics.md) | 人工复核只打 correctness + 关键词命中度量增强与生成口径收敛 | 已采纳 |
| [ADR-0027](adr-0027-calibration-sla-and-retrieval-observability.md) | 人工校准四指标 SLA + 检索观测/低置信门控/关键词腿与入库策略 | 已采纳 |
| [ADR-0028](adr-0028-agent-eval-rollback-gate.md) | Agent 行为评测闸门（工具编排回归） | 已采纳 |
| [ADR-0029](adr-0029-alembic-rebaseline.md) | Alembic re-baseline —— 以 ORM 模型为唯一事实源重建迁移基线 | 已采纳 |

> 注：0005 / 0006 为早期合并前预留号，未单独成文（内容并入 0007/0008）。
