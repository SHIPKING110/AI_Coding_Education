# ADR-0013：Agent 工作台修复——Skill 广场一致执行 / 乱码净化 / 大纲对齐 / 附件呈现

- 状态：已采纳
- 日期：2026-10-22
- 关联：ADR-0008/0009/0012、`app/services/skill_bundle.py`、`app/services/agent_tools.py`、`app/services/agent_planner.py`、`app/services/llm.py`、`app/api/routers/agents.py`、`frontend/src/views/agents/AgentsView.vue`

## 背景（Context）

Agent 工作台在 teacher 实际使用 ppt-master（zhang 发布到广场的 Skill）时暴露四类问题：

1. **收录后无法生成 PPT**：管理员/教师从广场「收录」ppt-master 后，能用、能出计划，但一执行就失败、产不出 PPT；发布者自用正常。
2. **二次编辑乱码**：首次生成 PPT 后，再说「加一页」这类修改，回复出现 `<｜｜DSML｜｜ calls>`、`<|tool▁calls▁begin|>` 之类的乱码，且越改越乱。
3. **大纲与成果不同步**：用 Skill 生成 PPT 时，工作区「大纲」不随对话更新，「大纲」页与「成果」对不上，对应页的 SVG 预览也没有。
4. **附件问题**：上传的图片/文档在对话里不显示；上传图片与 ppt-master 无法配合；「+」菜单鼠标移开就收起、难点中。

## 决策（Decision）

### 1. 收录后无法生成：收录即「物化」文件包到使用者目录

根因：Skill 文件包按 `uploads/skills/{作者owner}/{skill_id}/` 落盘在**作者目录**，
收录只是记录一条引用关系（`AgentSkillCollection`）。而执行工具用 `list_skills(owner_id=user.id)`
只找**本人名下**的 Skill，且 `skill_exec` 按 `(owner_id, skill_id)` 定位目录——
收录者既找不到 Skill 记录、也找不到文件，执行必然失败。

修复（`skill_bundle.materialize_bundle` + `agent_tools._resolve_skill_for_exec`）：

- 新增 `resolve_skill_for_user`：按「本人 → 已收录(作者仍在架) → 广场可见」解析真实 Skill 行；
- 工具层解析到「非本人」的 Skill 时，把作者目录的文件包**复制到使用者自己的目录**（物化，带 `.materialized.json` 标记、来源/文件指纹去重）；
- 之后执行/写文件/取产物全在使用者目录完成。效果：
  - **发布者与所有收录者跑同一份文件包、结果完全一致**（这是本 ADR 的核心诉求）；
  - 使用者手写的中间产物（如 SVG 源文件）不污染作者目录；
  - 产物下载链接按使用者维度隔离。
- 规划器 Skill 清单 `_skill_inventory` 与兜底 `heuristic_skill_calls` 同步纳入「本人 ∪ 已收录广场」，
  否则模型根本不知道有这个 Skill 可用。

### 2. 二次编辑乱码：原生工具调用标记净化

根因：最终回答走纯文本流式（`llm.stream_text`，不 bind_tools），但模型在「加一页」这类编辑意图下
会**原生吐出工具调用特殊 token**（DeepSeek 系 `<|tool▁calls▁begin|>…` / 部分模型的 `<｜｜DSML｜｜…>`、
以及 Anthropic XML 风格 `<function_calls>`），这些当普通文本落库 → 前端渲染成乱码 → 下一轮又被当历史喂回，
形成污染循环。

修复（`llm._StreamSanitizer` + `strip_toolcall_markup`）：

- 流式净化器识别「脏区」：看到开标记进入，丢弃脏区内所有内容，直到闭标记退出；
  跨 chunk 用「未完成标记前缀」缓冲，保证标记被拆成多段也不泄漏；
- 在四处统一净化：流式输出（`stream_text`）、持久化前（`agents.py`）、历史回灌（`agent_memory._clean_history`）、
  读取/分享接口（防止旧乱码复现）。
- 普通文本（如 `a<b`）不受影响（只认已知标记前缀，且过半判定为正常文本时放行）。

### 3. 大纲/成果对齐：从工具轨迹提炼 spec

根因：`extract_spec` 只从模型输出的 ```json 块提炼 outline/sections。Skill 生成 PPT 时正文通常没有 json 大纲，
于是 spec 为空 → 前端「大纲」不更新、「成果」对不上、SVG 页预览丢失。

修复（`agents.py._derive_spec_from_tools`）：当 spec 无 outline 且本轮有工具执行时，
从 `write_skill_file` 写入的 `*.svg` 页（按写入顺序＝页序）还原 outline（标题取文件名去序号前缀，首页为 cover），
并附 slides 预览结构。这样「大纲」每一页都对应「成果」里真实生成的幻灯片，SVG 页也能在前端预览。
没有 SVG 轨迹时不臆造（保持原有 json 解析）。

### 4. 附件呈现 + 图片可配合 Skill

- 前端：消息气泡新增 `.msg-atts` 渲染 `m.attachments`（图片缩略图 / 文档图标 + 名称，可点击预览）——
  之前只渲染待发送区的附件，已发送的看不见。
- 「+」菜单：加一段透明「悬停桥」（`.plus-menu::after`）补上按钮与菜单间 8px 空隙，
  鼠标移向菜单项不再误触 `mouseleave` 收起；点击 + 直接开文件选择的行为不变。
- 图片配合 Skill：`_attachment_block` 把上传图片的 `/uploads/...` 映射为**磁盘绝对路径**写进上下文，
  并提示模型可让 Skill 脚本直接读取该路径插入 PPT/文档，或写入 Skill 包内资源后由脚本消费。

## 理由（Rationale）

- **一致性优先**：Skill 作为「全校可复用的能力」，发布者与使用者必须等效；物化文件包是达成一致且不污染作者的最稳方式。
- **乱码从源头堵**：既净化输出又净化历史，阻断「乱码→入历史→更乱」的正反馈。
- **对齐靠真实产物**：大纲从「实际写出的页」提炼，而非另造一份，保证大纲＝成果。

## 后果（Consequences）

- 正向：包含收录场景在内的所有使用方能生成 PPT；二次编辑不再乱码；大纲/成果/预览一致；附件可见且可配合 Skill。
- 代价：
  - 物化会在使用者目录占用一份文件包副本（带指纹去重，作者更新后首次调用自动刷新）；
  - 净化器基于已知标记清单，若未来模型引入全新标记格式需补充 `_DIRTY_OPENERS/_DIRTY_CLOSERS`；
  - 大纲标题取自 SVG 文件名，命名不规范时标题可能不够友好（可在 SKILL 内约定命名）。

## 附录（2026-10-22 修订）：上传附件/报告上下文未生效

反馈：「上传图片 + 配置报告总结上下文都没被正确传入 agent，对话里只显示一句话」。

排查结论：
- **后端注入链路本身正确**：`_attachment_block`（附件正文/图片路径）与 `_report_block`（绑定报告正文）
  都拼进 `mem_block` 并进入 `build_unified_prompt`（含自定义 Agent）；容器实测均有内容。
- **真正断点**：①前端「上传中」时点发送，`pendingAttachments` 此刻为空 → 附件被静默丢弃，只剩文字；
  ②当前模型为**纯文本模型**，看不到图片像素，只能看到文件名+磁盘路径，回复未明确确认附件。

修复：
- 前端：`uploadingAttachment` 时禁止发送并提示「还在上传」；附件渲染改为 `msgAtts()`（本地 attachments ∪
  citations.attachments 去重），本地刚发与历史重载都能显示。
- 后端：`_attachment_block` 增加强指令——回复开头须明确「已收到 N 张图片」并复述文件名；
  若模型无法识别图像内容须如实说明，不得假装看不见或编造；图片磁盘路径继续提供给 Skill 脚本内嵌（配合 ppt-master）。
