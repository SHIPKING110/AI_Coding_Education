# Agent · 知识库 · 记忆（Context）

本上下文描述系统的「AI Agent 工作台」：把生成 PPT 的智能体统一到一个可管理的工作台中，
并为其提供跨轮记忆与 RAG 知识库引用能力。术语在此锁定，其他文档/代码/对话一律以此为准。

## Language

**Agent**：
一个在 Agent 工作台注册、有固定职责与可执行动作集的 AI 智能体（当前：工作报告 PPT Agent、家长会 PPT Agent）。
_Avoid_：机器人、Bot、助手、AI（泛指）

**Agent 工作台（Agent Workbench）**：
统一承载所有 Agent 的页面：选 Agent → 新建对话 → 对话历史 / 上下文 / 记忆 / RAG 引用管理。
_Avoid_：助手页、AI 页、聊天页

**Agent 注册表（Agent Registry）**：
后端维护的 Agent 清单（id、名称、所需上下文类型、系统提示词、可用动作集、是否支持 RAG）。
_Avoid_：Agent 列表、Agent 配置

**context_ref（业务上下文引用）**：
一次会话绑定的业务对象，如 `{kind:'report', id}`、`{kind:'class_ppt', class_id, period}`。
_Avoid_：参数、上下文（泛指）

**Conversation（会话）**：
一个 Agent 与一个 context_ref 绑定的一段持久化对话线程。_Avoid_：聊天、对话（口语）

**Message（消息）**：
会话中的单轮记录（role = user / assistant），持久化存储。_Avoid_：气泡、发言

**短期记忆（Short-term Memory）**：
当前会话的滑动窗口 + 滚动摘要，仅在本会话内生效。_Avoid_：上下文、临时记忆

**长期记忆（Long-term Memory）**：
跨会话保留的用户/Agent 持久事实（结构化键值 + 每次会话结束生成的要点摘要），检索后注入提示词。
_Avoid_：记忆（不区分时）、永久记忆

**Document（文档）**：
用户上传的一份可被切块入库的源文件（标题 + 描述 + 文件），是上传与入库的单位。
_Avoid_：资料、文件、知识

**Chunk（切块）**：
Document 按 token 切分出的检索单元：窗口 512 token、重叠 100 token。_Avoid_：分段、片段

**KnowledgeBase（知识库，KB）**：
Document 的逻辑集合。两种范围：私有库（Private，仅所有者可引用）与广场（Plaza，公开可发现）。
_Avoid_：库、语料、资料集

**Plaza（广场）**：
教师把 Document 公开放入的公共区域，供其他教师发现。_Avoid_：公开库、共享区

**Collection（收录）**：
某用户对一份广场 Document 的**引用**（不复制向量），收录后才可在对话中被引用；作者下架即失效。
_Avoid_：收藏、订阅、收藏夹

**Citation（引用）**：
回答中基于检索命中的 Chunk 给出的来源标注（文档标题 + 片段 + 相似度）。_Avoid_：参考、出处（口语）

**RAG 开关**：
会话级「引用知识库」开关（默认关），可对单条消息临时切换；关闭时不检索、不注入。
_Avoid_：知识库模式、检索开关
