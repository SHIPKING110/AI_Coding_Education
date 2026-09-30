# ADR-0009：Agent 会话与记忆持久化到 Postgres

日期：2026-09-21
状态：已接受

## 背景

现有 AI 运行态全部在内存：`services/ai_tasks.py` 的任务、`services/ppt_agent.py` 的
`SESSIONS`，重启即丢。而 Agent 工作台要求「对话历史记录」「上下文管理」「长短期记忆」，
这些必须是持久、可跨会话检索的。

## 决策

会话与记忆落 **Postgres 新表**（走 Alembic 迁移），内存只保留运行态：

- `agent_conversation`：id、owner_id、agent_id、context_ref、title、rag_enabled、时间戳。
- `agent_message`：conversation_id、role、content、citations(JSON)、created_at。
- `agent_memory`：owner_id + agent_id 维度的长期事实（结构化键值 + 会话要点摘要）。
- `agent_conversation_summary`（可选）：会话滚动摘要，用于短期记忆压缩。

短期记忆 = 当前会话滑动窗口 + 滚动摘要；长期记忆 = `agent_memory`，跨会话检索后注入提示词。

## 否决的备选

- 继续用内存存储：重启丢历史，无法支撑长期记忆，否决。
- 用文件/Redis 存：引入额外组件，且与现有 SQLAlchemy 体系割裂，否决。

## 后果

- 新增 Alembic 迁移与对应 CRUD / 模型。
- 跨轮记忆、会话历史、上下文管理均基于这两张主表实现；RAG（ADR-0010）复用同一向量库存会话检索。
