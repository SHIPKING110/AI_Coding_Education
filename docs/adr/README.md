# 架构决策记录（ADR）

本目录记录 Child Code 项目里**难以逆转、影响面较大**的技术/产品决策。
每条 ADR 记录：背景（Context）、决策（Decision）、理由（Rationale）、后果（Consequences）。

约定：
- 文件名 `adr-NNNN-简短标题.md`，编号只增不改。
- 一旦某条决策被推翻，不改原文，而是新增一条 ADR 并在旧条目顶部标注 `已被 ADR-XXXX 取代`。

## 索引

| 编号 | 标题 | 状态 |
| --- | --- | --- |
| [ADR-0001](adr-0001-assistant-business-tools.md) | 智能助手接入业务数据：本地工具（Skill）层 | 已采纳 |
| [ADR-0002](adr-0002-assistant-tool-planning.md) | 智能助手工具「规划层」：多轮 规划→执行→观察 | 已采纳 |
| [ADR-0003](adr-0003-assistant-sql-tool.md) | 智能助手数据库查询工具：只读 SQL + 多步取数 | 已采纳 |
| [ADR-0004](adr-0004-tool-list-integrity.md) | 名单类工具的完整性与截断语义 | 已采纳 |
