# ADR-0021：家长客服专属 Embedding 与 PPT 页数对齐口径修复

- 状态：已采纳
- 日期：2026-11-03
- 关联：ADR-0010、ADR-0011、ADR-0014、ADR-0020、CONTEXT.md

## 背景（Context）

1. 家长客服只配置了对话模型与 Rerank，Embedding 强制复用系统级；管理员无法为家长域单独选择向量模型。
2. 后台「PPT 页数对齐」长期为 0：只有创建 AgentPptTask 契约的对话路径才写 ppt_* 指标；一键 build-ppt、历史会话或无契约 Skill 出片路径没有观测数据。任务监控卡片又用全部 ppt_runs 作分母，与只按明确页数计算的达成率不一致。
3. Skill 执行链路读取 01_cover.svg 报「该类型不支持预览」：文本白名单缺 SVG，且脚本新生成页面未回写 AgentSkill.files。

## 决策（Decision）

### 1. 家长客服专属 Embedding（可选，管理员）

- 新增单例表 system_parent_embedding_config（provider/base_url/api_key_enc/model/model_path/enabled）。
- 家长域使用独立集合 parent_knowledge__{fingerprint}：已配置且与系统指纹不同→独立集合；未配置/停用/指纹一致→复用系统集合。
- 父索引只含 visible_to_parents=true 的 ready+启用文档；保存配置后后台按文档哈希增量重建，未变化跳过。父集合为空时关键词兜底读系统集合纯文本，白名单仍二次过滤。
- 接口：GET/POST/DELETE /teacher/service/parent-embedding-config、POST .../test、GET .../parent-embedding-index、POST .../parent-embedding-index/rebuild。
- 前端「家长客服共享模型」并行展示 对话模型 / Embedding / Rerank，并显示可见文档数、已索引数、待同步数、独立集合名。

### 2. PPT 页数对齐口径

- 有契约：沿用契约目标/实际/对齐，current_page_count=0 时用成品 pptx 实际页数兜底。
- 无契约但已出片：用户显式页数=目标；未指定则以实际成品页数=目标（交付即对齐），并补写 AgentPptTask 契约。
- 一键 build-ppt 也写 run 观测与任务契约（目标=审核后大纲页数，实际=文件页数）。
- 任务监控分母改为「带目标页数的任务/运行」；有契约优先契约口径，并展示「已交付」与「未指定页数运行」提示。

### 3. Skill 文件读取

- read_text_file 文本白名单补齐 .svg/.xml/.html/.htm/.css/.csv；图片仍禁止文本预览并提示走下载。
- read_skill_file 与预览接口在 files 未包含、但磁盘文件真实存在且路径合法时允许读取，修复「包内无此文件」假失败。

## 后果（Consequences）

- 正向：家长域可独立调优向量模型且与教师知识库隔离；PPT 页数指标在各类出片路径都有真实数据；SVG 页面源可直接预览。
- 代价：配置家长专属 Embedding 后需一次父索引重建（后台异步、增量跳过）；切换 Embedding 会新增集合，旧集合需运维清理。
- 边界：家长域与教师域仍共享同一批文档源文件，父索引是二次向量化，不复制原始文件。