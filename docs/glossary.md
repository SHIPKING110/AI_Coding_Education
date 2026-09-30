# 领域术语表（Glossary）

Child Code 项目里反复出现的领域概念与统一叫法。新增术语请就近追加，保持"一个概念一个词"。

## 业务领域

- **机构（Campus）**：多校区/分支标签（一校/二校/三校），挂在教师账号上，用于区分课表与学员归属。
- **教师（Teacher）**：授课账号，`role=teacher`。课表、报告、评估都以教师为归属维度。
- **教务（Staff）/ 管理员（Admin）**：非授课角色，可见全局数据；智能助手的业务工具对二者放开全局范围。
- **学员（Student）**：在读孩子，`status ∈ {active, stopped, archived}`；有 `lesson_balance`（剩余课时）。
- **班级（Class）**：一组学员 + 一位授课教师 + 科目（subject）。
- **排课（Schedule）**：一次具体的上课安排，`status ∈ {scheduled, completed, cancelled}`，含起止时间。
- **考勤（Attendance）**：某学员在某节课的出勤，`status ∈ {unmarked, attended, leave}`；到课扣 2 课时。
- **课时（Lesson）**：课程的计量单位；`expected_lessons` 应耗、`consumed_lessons` 实耗。
- **课时余额（Lesson balance）**：学员剩余课时；`≤ 10` 进入催缴名单（低课时预警）。
- **反馈（Feedback）**：课后给家长的课堂评价记录。
- **评估（Evaluation）**：每约 3 个月一次的学员综合评估表（含能力项 `level 1-5`），家长会使用。
- **家长会 PPT（Class PPT）**：以班级为单位的家长会演示，`ClassPpt`。
- **报告（Report）**：教师日报/周报/季度总结/年度总结，`type ∈ {daily, weekly, quarterly, yearly}`；
  含 `stats` 统计快照。报告 PPT 基于它生成。
- **达标率（Achievement rate）**：`实耗课时 / 应耗课时`，反映课程是否按计划消耗。
- **出勤率（Attendance rate）**：`到课人次 / (到课 + 请假) 人次`。

## Agent 工作台

- **Agent / 智能体**：工作台里的可对话角色。当前有 `assistant`（智能助手）、`report_ppt`（工作报告 PPT）、
  `class_parent_ppt`（家长会 PPT）。
- **会话（Conversation）**：一次与某 Agent 的持续对话；`context_ref` 绑定其业务素材，`pinned` 置顶，`share_token` 分享。
- **阶段（Stage）**：Agent 的执行链路步骤（如 `outline / copy / theme / export`），多阶段 Agent 才有路线图。
- **路线图（Roadmap）**：多阶段 Agent 的阶段导航；单阶段 Agent（如智能助手）不显示。
- **工作区（Workspace）**：对话右侧的大纲 / 素材 / 成果面板。
- **素材（Material）**：Agent 绑定的业务数据（报告 / 班级评估），存于 `context_ref`。

## 智能助手工具层（ADR-0001 / ADR-0002）

- **工具 / Skill（工具）**：一层**只读**的业务数据查询能力，声明 `name / description / 参数 schema / 处理函数`。
  例：`my_schedule_overview`、`find_students`。注册于 `app/services/agent_tools.py`。
- **规划层（Planner）**：`app/services/agent_planner.py`。多轮 **规划 → 执行 → 观察** 循环，
  决定"调哪些工具、传什么参数"，并带预算护栏与降级。
- **规划（Plan）**：一次非流式 function-calling 产出"下一步要调用的工具集合"。
- **观察（Observation）**：工具执行结果回灌给规划器，供其决定是否继续调用更多工具。
- **轮（Round）**：一次"规划 + 执行其产出的全部工具调用"。受 `AGENT_TOOL_MAX_ROUNDS` 限制。
- **预算护栏（Budget guard）**：轮数 / 工具数 / 时间三重上限，防止多轮失控。
- **去重（Dedup）**：同一 `(工具, 参数)` 只执行一次，避免模型兜圈。
- **降级（Degrade）**：LLM 不可用或规划失败时，退回关键词启发式单轮路由或纯 RAG。
- **教师作用域（Teacher scope）**：工具按当前教师隔离数据（学员/班级/报告/评估等都只见本人）。
- **整条截断（Whole-record truncation）**：结果超长时按整条记录裁剪 + 提示未列出条数，
  绝不把一条记录切成两半，避免模型幻觉出"未返回"。
- **评估完成态（Evaluation completion）**：已完成=有已发布(published)评估；未完成=未写评估或
  仍为草稿(draft)。`class_evaluation_overview` 工具逐学员标注。
- **RAG**：知识库检索增强（制度/流程/文化文档），与"业务工具"是两类互补的知识来源。
- **数据库查询工具（只读 SQL）**：`app/services/agent_sql.py`。`sql_list_tables` / `sql_describe_table` /
  `sql_query` 三件套，只读事务 + 表白名单 + 列脱敏 + LIMIT/超时 + 教师作用域；用于固定工具覆盖不到的临时统计。
- **作用域过滤（Scope filter）**：教师查询含教师归属的表时必须显式带自己的 `teacher_id`，否则拒绝。
- **结果截断（Truncation）**：工具结果回灌模型与注入回答前的限长处理，控制 token。
