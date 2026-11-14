# ADR-0018：默认 PPT Agent + 会话删除清理 + 大 Skill 本地执行 + 防跑偏

- 状态：已采纳
- 日期：2026-10-24
- 关联：ADR-0016/0017、agent_provision.py、skill_bundle.cleanup_conversation、skill_exec.dispatch、llm.TOOL_PLANNER_SYS、AgentsView.svgPages

## 背景（Context）
1. 希望**每个教师账号默认拥有「PPT生成助手」**，开箱即用。
2. **删除会话组**时，其产出的文件（会话隔离 projects / _outputs 产物）需要一并清理，不留垃圾。
3. 教师账号生成 PPT「效果更差/跑不动脚本」；怀疑广场 skill 对教师执行受限。
4. **PPT 跑偏**：多轮后正文规划正常但产出文件不一致；工作区大纲的 SVG 不实时同步最新。

## 根因（Root Causes）
- **A1**：默认 Agent 只在个别账号手工建过；新教师无 PPT 助手。
- **A2**：`delete_conversation` 只删 DB 行，会话隔离的 `conversations/conv_xxx/` 与 `_outputs/` 产物残留。
- **B3（教师更差的关键系统级原因）**：教师 zhang 账户开启了**百炼远程沙箱**（`provider=bailian`），
  而 ppt-master 近千文件超出远程文件配额，入口脚本被挤掉 → 每次「远程失败→回退本地」，
  慢且不稳；管理员是纯本地则稳定。**并非广场 skill 权限限制**——权限层早已对齐（按名解析到适配版）。
- **B1/B2（跑偏/不出片）**：规划器 prompt 对「读文档上限、必须出片、与正文对齐」约束不够强；
  模型容易读几个文件就停或中途换主题。SVG 预览只取「最近一条」消息，二次编辑只回传变更页时整套缺页/不更新。

## 决策（Decision）
1. **默认 PPT Agent 供给**（`agent_provision.ensure_default_ppt_agent`）：
   - 教师/管理员首次进入工作台（list_agents）自动补建「PPT生成助手」，绑定广场适配版并自动收录；
   - 幂等：已存在同名则跳过；无广场适配版则不建（避免空助手）。已对现有账号批量补建。
2. **会话删除连带清理**（`skill_bundle.cleanup_conversation`）：
   - 删会话时清理各 skill 下 `conversations/conv_<cid12>/` 整目录；
   - 从该会话消息的工具轨迹里提取产物 `_outputs/<run>/` 目录并删除（只删本会话自己的运行产物）。
3. **大 Skill 强制本地执行**（`skill_exec.dispatch`）：
   - 技能包文件数 > 远程配额（REMOTE_MAX_FILES=300）时，跳过远程沙箱、直接本地执行；
   - 于是 ppt-master 无论管理员还是教师都走本地、会话隔离、快速稳定——**效果彻底对齐**。
4. **防跑偏 + 实时同步**：
   - `TOOL_PLANNER_SYS` 增加：文件内容必须来自本轮正文、禁止中途换主题；信息足够就直接出片；
     读文档≤4 次、写了页必须 build、没有下载链接=没交付；
   - 前端 `svgPages` 改为「按页名跨消息合并去重，以最新一轮 url 为准」：二次编辑只回传变更页也能拼出完整套并实时更新。

## 后果（Consequences）
- 正向：所有教师开箱即用 PPT 助手、生成效果与管理员一致（同一适配版+同类本地执行）；
  删除会话不留垃圾；复杂课件能一步到位出片且与正文对齐；大纲 SVG 实时反映最新改动。
- 边界：大 skill 一律本地执行（放弃远程沙箱复用）；如需远程，需调大配额或拆分 skill 包。
- 真实验证：zhang 教师账号发「C++课件（4-6年级，含4大知识块+习题+情景）」→ 27 步工具、
  写 17 页 SVG、出片 16 页 PPT，标题逐项覆盖需求；build 走本地 `provider=local` 成功。
