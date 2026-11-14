# ADR-0017：同名 Skill 遮蔽 + 会话粘性出片

- 状态：已采纳
- 日期：2026-10-24
- 关联：ADR-0013/0015/0016、agent_ext.resolve_skill_for_user、agents.py skill_mode

## 背景（Context）

修复后复发三症状（管理员/教师）：
1. svg 与 pptx 风格/标题不一致；或一致但下载到的是**别的会话 PPT**、调不回来。
2. 「说了出片不出片」：回复空口「好/稍等」，无文件可下载，拖。
3. 疑问：广场适配版 ppt-master 是否内置？管理员与教师效果不同（教师更差）。

## 根因（Root Causes）

### 问题3（教师效果更差）——同名 Skill 遮蔽
- `resolve_skill_for_user` 按**名字** "ppt-master" 解析时，**优先返回本人名下**的 skill。
- 教师 zhang 名下自留一份**旧版 `e7d71aa7`（无 ppt_oneshot wrapper、无快速通道）**，同时收录了适配版 `69a4af9c`。
  → 模型用名字调工具时命中**旧版** → 缺 wrapper/快速通道 → 生成链路不稳（风格漂移、页序乱、出不了片）。
- 更糟：带 Agent 白名单时，先命中旧版却被白名单拒绝 → 直接 None（执行失败），根本用不上适配版。

### 问题1（风格不一致/下载旧会话）——旧版无隔离 + 无归一化
- 旧版 `e7d71aa7` 没有 `_normalize_svg_order`（页序兜底）、也无会话级 projects 隔离；
  走它的链路就会：风格/标题漂移、下载到共享 projects 里别的会话产物。
- 一旦问题3让它解析到旧版，问题1 必然复发。

### 问题2（说了不出片）——短确认句不进 Skill 路径
- 「可以给我了吗/确认/好的/开始吧」等短句不命中 `looks_like_skill_task/ppt_edit/ppt_continue` → 不进 Skill 路径 → 模型只回「好」不执行。

## 决策（Decision）

1. **resolve_skill_for_user 改为「可用性 + 白名单」优先**：
   - 名字匹配时，优先命中「**既可用、又在当前 Agent 白名单内**」的 skill；
   - 不再盲选本人名下（避免旧同名遮蔽适配版）；读 `_ALLOWED_SKILLS` 让解析与授权口径一致。
   → 教师即使自留旧版，也会解析到「已收录、已授权的适配版」。
2. **会话粘性出片**：本会话近几轮已 `write_skill_file/run_skill_script`（在做 PPT）时，
   把 ≤16 字的短确认句也纳入 Skill 路径，逼模型真正执行出片，而非空口应「好」。
3. **广场适配版已内置为权威版**：admin 发布 `69a4af9c` 到广场；教师收录即用同一份（含 wrapper + 归一化 + 快速通道）。
   不强制「系统内置」——但通过「解析优先可用+白名单」保证所有人用到的是这份完整版。

## 后果（Consequences）
- 正向：教师与管理员效果一致（都用适配版）；短确认句也能真出片；旧版不再遮蔽。
- 边界：若用户名下确有**多个都能用的同名 skill**，按「有效绑定 > 广场」优先；仍未彻底删除旧版，
  建议运维清理教师名下冗余旧 ppt-master（脚本可后续提供）。

## 附录（2026-10-24 复测加深）：出片真正失败的三层根因 + 修复

复测发现「说了出片不出片」在生产里不止"门控"，还有出片脚本层的硬失败，逐层修：

1. **同名遮蔽（已修，见上）**：教师 zhang 自留旧版 `e7d71aa7` 遮蔽适配版 → 用残缺旧版。
   修：`resolve_skill_for_user` 按名字解析优先「可用 + 白名单内」，读 `_ALLOWED_SKILLS` 口径一致。
2. **路径前缀 `./` 未归一（已修）**：模型常传 `./projects/x`，旧 `_scope_path/_scope_arg` 只认 `projects/`
   开头 → 没改写到会话隔离目录 → build 跑到不存在的根目录而失败。
   修：`_scope_path/_scope_arg` 归一化 `.//`、前导斜杠、反斜杠；`ppt_oneshot.cmd_build` 增加
   `_resolve_project` 回退（`projects/X` 不存在就找 `conversations/*/projects/X`）。
3. **质量门禁过严 + 非法颜色（已修，最致命）**：
   - 模型生成的 SVG 常含非法颜色（如 `stroke='#33island'`）→ 质量检查 error → build 直接失败不出片；
   - 即便只有 warning（passed:0, errors:0）也被拦。
   修：`ppt_oneshot.cmd_build` 导出前 `_sanitize_svg_colors` 规范化非法颜色；质量门禁改为
   **仅 error 才阻断，warning 放行**（`_qc_errors_only`）；导出不再叠 `--enable-dangerous-nonconforming`
   （与 `--quick-generate` 冲突）。

**真实验证**：教师 zhang 经工作台 `run_skill_script` 执行 `ppt_oneshot.py build` → `成功=True`、
产出 `.pptx`（此前 exit 1、无文件）。管理员与教师现走同一适配版、同一稳定链路。

> 注：日志里「百炼沙箱不可用，回退本地执行」是沙箱配置提示，不影响最终本地出片成功。
