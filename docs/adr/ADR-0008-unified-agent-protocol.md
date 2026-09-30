# ADR-0008：统一 Agent 运行协议

日期：2026-09-21
状态：已接受

## 背景

系统现有两个 AI PPT 能力，架构互不相通：工作报告总结是**自由流式对话**
（`services/ppt_chat.py` + `PptBuilderDrawer.vue`，SSE + 可执行 options 协议 + phase 阶段）；
家长会 PPT 是**固定 A–D 点选步骤**（`services/ppt_agent.py` + `PptAgentDialog.vue`，
内存 session + `ai_tasks` 异步构建，无流式对话）。要在同一工作台里管理，并便于后续新增 Agent，
必须先统一运行模型。

## 决策

所有 Agent 统一到同一套协议：**对话 + 可执行动作（options）+ 阶段（phase）+ SSE 流式**。

- 后端提供统一的 Agent 注册表（id、名称、所需上下文类型、系统提示词、可用动作集、是否支持 RAG）。
- 一次对话请求 = `agent_id` + `context_ref` + 会话消息 + 当前状态（大纲/文案/主题/开关）；
  后端按 Agent 的提示词与动作目录生成回复，以 SSE 流式返回 `delta / phase / done / error`。
- 家长会 Agent 用同一协议**重新平台化**：把原 A–D 点选步骤改写为「对话 + 可执行 actions」。

## 否决的备选

- 只做外壳统一（保留家长会固定步骤，仅嵌进统一页面）：两套运行模型并存，新增 Agent 成本高，否决。
- 各 Agent 各写一套接口：重复实现流式/阶段/动作，维护成本高，否决。

## 后果

- 现有 `PptBuilderDrawer.vue` 的对话协议升格为通用 Agent 协议；`ppt_agent.py` 的点选逻辑改为动作集。
- 前端「AI 定制 PPT」抽屉、评估「Agent 定制」弹窗下线，改为跳转 Agent 工作台并传 `agent_id + context_ref`。
- 后续新增 Agent 只需注册提示词 + 动作集，无需新接口。
