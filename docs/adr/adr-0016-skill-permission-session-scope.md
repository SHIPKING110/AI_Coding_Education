# ADR-0016：Agent Skill 权限界定 + 工作区按会话一致刷新

- 状态：已采纳
- 日期：2026-10-24
- 关联：ADR-0013/0014/0015、agent_registry.py、agent_tools.py、agent_planner.py、AgentsView.vue

## 背景（Context）

1. **权限越界**：某 Agent（如「画家」「编辑Agent」）在「编辑 Agent」窗口**没有勾选 ppt-master**，
   对话里却仍能引用/规划/执行 PPT 相关 Skill 脚本。
2. **工作区串台**：切换会话组后，新建的空会话或另一个 Agent 的会话，工作区「大纲」仍显示上个任务的大纲；
   「大纲/素材/成果」三块未与「当前会话」严格对齐。

## 根因（Root Causes）

### 问题1 权限越界
- `agent_planner._skill_inventory`、`agent_tools.auto_build_ppt`、`agent_tools._resolve_skill_for_exec`
  取的是**用户名下全部 Skill**（∪ 已收录广场 Skill），**完全忽略 Agent 的绑定**。
- `effective_capabilities` 的 `want_skill = per_agent_skill_ids ∪ global.default_skill_ids`：
  只要存在**全局默认 skill**，就会作用到该账户**所有** Agent（含没勾选的）。
- （叠加）测试期间给 admin 设了全局默认 skill，导致「画家」等未勾选 Agent 被动继承。

### 问题2 工作区串台
- `openConversation` 未清空 `outlineDraft/pptTheme/expandedPage/svgCodeCache` 等。
- `syncOutlineDraft` 仅在「有数据」时**赋值**，**从不清理**——切换到无大纲的会话时旧大纲残留。

## 决策（Decision）

### 1. Skill 权限按「Agent 生效绑定」严格界定
- 新增 contextvar 白名单 `_ALLOWED_SKILLS` + `use_allowed_skills()` + `_skill_allowed()`。
- `plan_and_run` 开跑前按「per-agent skill_ids ∪ global.default_skill_ids」求出 `allowed` 并设置。
- 三个 Skill 入口（`_skill_inventory` / `_resolve_skill_for_exec` / `auto_build_ppt` / `heuristic_skill_calls`）
  全部加 `_skill_allowed()` 过滤：**没勾选 = 不进清单 + 不能执行 + 不自动出片**。
- 清理误设的全局默认 skill（测试污染），避免「全局默认」把未勾选 Agent 被动授予。

> 说明：全局默认仍是产品特性（作用于所有 Agent），但**必须有 Skill 才生效**；
> 真正的越界修复是「无绑定即不可用」，不再回落到「用户名下全部 Skill」。

### 2. 工作区三块 Tab 与「当前会话」严格一致
- `openConversation` 切换即**全量重置**工作区状态（outline/section/theme/material/result/expand/cache）。
- `syncOutlineDraft` 改为**以本会话内容为准**：无 spec、无派生 → **清空** outline（不再保留上个会话残留）。

## 后果（Consequences）

- 正向：Agent 只有勾选/全局默认的 Skill 才可用——权限边界清晰；切换会话工作区即时对齐，不再串台上个任务。
- 代价：全局默认一旦设置会作用于所有 Agent（产品语义），需管理员谨慎；未勾选又无全局默认则 Skill 完全不可用（符合预期）。
