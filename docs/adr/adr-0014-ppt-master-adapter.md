# ADR-0014：ppt-master 兼容适配版（工作台 one-shot 包装）

- 状态：已采纳
- 日期：2026-10-23
- 关联：ADR-0013、`backend/seed_skills/ppt-master-adapter/`、`backend/scripts/seed_ppt_master_adapter.py`

## 背景（Context）

工作台用第三方 ppt-master 生成/二次编辑 PPT，但官方流程是**多阶段交互式**的
（project_manager → 确认UI → 模板候选 → 图片获取 → 质量门禁 → 导出）。工作台模型的工具调用预算有限，
自己摸这套多步路由极易漏步走偏，表现为「生成不稳、二次编辑易崩」。

## 决策（Decision）

不重写 ppt-master（保其生成效果），而是加一层**兼容适配**：

1. **封装 one-shot 脚本** `scripts/ppt_oneshot.py`（注入到 ppt-master 包内）：
   - `build  <project>`：质量门禁(svg_quality_checker) + 导出(svg_to_pptx `--quick-generate`)，一步出片；
   - `edit   <src.pptx> <workspace>`：`pptx_to_svg --roundtrip` 导入为可编辑工作区；
   - `export <workspace>`：`svg_to_pptx --roundtrip` 导出（保留未改页、只重建改动页）；
   - `init   <name>`：建项目。
   脚本向上自动定位 ppt-master 根（含 `scripts/svg_to_pptx.py`），不写死路径。
2. **SKILL.md 顶部写入「工作台快速通道」**：引导模型「写 SVG 到 svg_output/ → 跑 build」，
   而非逐条走交互流程；高级场景（模板候选/图片生成/动画讲解）才回退官方完整流程。
3. **安装脚本** `seed_ppt_master_adapter.py`：从**已上传的 ppt-master 源包**就地构造适配版
   （复制源包 → 注入 wrapper + 快速通道 → save_bundle 落盘 → 建/更新 AgentSkill → 可选发布广场），
   等价于手动导入 ZIP，但无需 22MB 文件走浏览器上传，也**不入库大 zip**（`.gitignore`）。

## 理由（Rationale）

- **质量不变**：只是编排 ppt-master 自带脚本，生成效果与官方一致。
- **稳定性提升**：把多步路由压成单命令，模型只需「写页 → 跑一条命令」，大幅减少漏步走偏。
- **可维护**：适配逻辑是独立薄封装，ppt-master 升级时只需重跑 seed（从源包重新注入）。

## 后果（Consequences）

- 正向：工作台里 ppt-master 生成/二次编辑走稳定单入口；教师收录即可用；产物自动回链。
- 代价：
  - 适配版依赖「已上传的源包」存在（seed 从源包构造）；且封装的是 quick-generate 路径，
    **不含**确认UI/模板候选/图片生成等高级能力（这些仍可走官方完整流程，但工作台里不易用）。
  - `build` 仅导出当前 `svg_output/` 里已有的页；换主题/加页需由模型改 SVG 后再 build（这正是二次编辑路径）。
- 已验证：容器内通过工作台 `run_skill_script` 工具跑 `ppt_oneshot.py build`，成功导出 .pptx。

## 补充修正（2026-11-02：跨会话串任务与反复修复不出片）

线上反馈「问 Python 列表却导出旧会话的运算符课件」「多轮调整后反复继续修复仍拿不到成品」。根因与修正：

1. **二次编辑源文件跨会话泄漏**：`_existing_pptx_block` 与 `run_skill_script` 的「已有PPT源文件」
   原先扫描整个用户 Skill 目录，历史对话的旧 `.pptx` 进入上下文后，模型会把旧主题当成当前任务继续改。
   现在只扫描**当前会话** `conversations/conv_xxx/projects/`，且优先绑定当前 PPT 契约项目；
   无契约时只取本会话最近修改项目。
2. **构建路径回退跨会话**：`ppt_oneshot._resolve_project` 原先在项目缺失时遍历所有
   `conversations/*/projects` 并挑最新，可能抓到别的对话。现在只允许**同一会话作用域内**回退。
3. **门禁 error 阻断出片**：`build` 在自动修复 5 轮后若仍有 error，原先直接失败；现在会继续尝试
   `svg_to_pptx --quick-generate` 宽松导出，成功即交付并提示剩余非阻断问题，避免用户无限「继续修复」。
   导出后校验 PPTX 文件确实被本次构建更新，防止把旧成品误报成功。
4. **自动出片时间窗收紧过度**：`auto_build_ppt` 原先只认「60 分钟内改过」的项目，用户隔一会儿回来
   点「继续修复」就会找不到项目。会话作用域已能隔离，现改为优先使用当前 PPT 契约项目，否则用本会话
   最近项目；并在多轮规划/修复仍无成品时由路由层再强制兜底 build 一次。

回归：`tests/test_ppt_fallback.py`、`tests/test_agent_workbench.py`。
