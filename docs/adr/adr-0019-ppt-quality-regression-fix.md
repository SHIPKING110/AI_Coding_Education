# ADR-0019：PPT 输出质量回归修复（SVG↔大纲对齐 / 空回复兜底 / 防跑偏）

- 状态：已采纳
- 日期：2026-10-24
- 关联：ADR-0018、skill_exec.LOCAL_FETCH、agents._derive_spec/_synthesize、agent_tools.tool_schema_for、ppt_chat.chat_prompt、AgentsView.svgPages

## 背景（Context）
同一分享会话出现质量回归：①空对话、SVG 没对应到「工作区 大纲」；②规划正文变短、不够细致；③半天不出文件、偶发空回复/内容不完整。

## 根因（Root Causes）
1. **SVG 预览被截断 → 大纲缺页**：`LOCAL_FETCH_MAX_FILES=8`，
   一次 build = pptx(1) + 每页 svg(N)。当 N≥7 时，超出 8 的 svg 不被回收，
   前端「大纲」有 8~10 页但「SVG 预览」只有 7 页 → 点后面几页显示「暂无 SVG」，即"svg 没对应到大纲"。
2. **前端按数组下标对齐 svg↔大纲**：outline 与 svgPages 两个数组靠 `svgPages[i]` 配对，
   任一侧数量不一致就错位。
3. **空/过短回复**：模型在多轮工具后，最终正文可能是「我先…然后生成」这类一句话（实测 43 字），
   且不保证带下载链接 → 用户看到"空回复/不完整"。
4. **跑偏 & 拖沓**：做内容 PPT 时规划器仍把班级/学员/排课/SQL 等业务工具暴露给模型，
   诱导它去 `my_teaching_stats/list_my_classes` 等无关查询，拖慢出片、污染内容。
5. **规划偏薄**：chat 阶段 prompt 对「新起 PPT 必须细致方案」约束不足。

## 决策（Decision）
1. 产物回收上限 `LOCAL_FETCH_MAX_FILES` 8 → 40（字节上限不变），保证 pptx + 全套单页 svg 都回收。
2. **SVG↔大纲按文件名精确对齐**：
   - 后端 `_derive_spec_from_tools` 把每次 build 产出的每页 svg 下载 url **按文件名**挂到 `slides/outline[].url`；
   - 前端 `svgPages` 优先取 `spec.outline[].url`（与大纲同序、逐页对应），无 spec 时才回退扫工具轨迹。
3. **空/过短回复兜底**：新增 `_synthesize_ppt_summary`，当 Skill 已产出文件但正文 <120 字或缺下载链接时，
   落库前用工具轨迹合成「页数 + 逐页标题 + PPTX 下载链接」补进正文，杜绝空回复/缺链接。
4. **按场景裁剪工具集**：`agent_tools.tool_schema_for(skill_task)`——明确的 Skill 生成任务下，
   剔除业务数据工具（my_teaching_stats/list_my_classes/find_students/student_progress/
   class_evaluation_overview/sql_*），保留 web_search + 文件/脚本工具，减少跑偏与拖沓。
5. **规划更细致**：重写 `ppt_chat.chat_prompt`——新起 PPT 必须先讲定位与结构、**逐页列出**标题+内容概要，
   禁止只回"我来做/稍等"；已生成则结尾给页数与下载链接。

## 后果（Consequences）
- 正向：大纲与每页 SVG 一一对应（不再缺页/错位）；回复恢复详尽（实测 3372 字、含下载）；不跑偏查业务数据；
  出片更快更稳。
- 真实验证：admin 发「魅力高管自我介绍 PPT」→ 18 步工具、**0 次业务查询**、10 页大纲**10 页全部挂 SVG url**、
  pptx **10 页**与大纲一致、正文 3086 字含逐页方案；落库后正文含 PPTX 下载链接。
- 边界：大 deck（>40 产物）仍受 40 上限；极少情况下文件名无法提取有意义标题（仍显示 slug，可在大纲里手改标题）。
