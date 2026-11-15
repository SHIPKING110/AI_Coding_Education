# Product-Spec.md — 家长端 AI 客服 P0

> 状态：P0（无 Redis，先跑通问答）。Redis 留 P1（限流/会话窗/配额计数）。
> 约定：家长身份 = 微信小程序 openid；家长语料 = 仅"已发布家长版"子集（后台勾选）；
> 配额默认匿名 3 轮/日、家长 50 轮/日，落库可配；高风险（退费/收费/安全）强制转人工；
> 教师端"教学服务"为一级导航；配额与词表配置落库（沿用 `SystemSetting` 单例模式）。

## 1. 功能列表（优先级）

| # | 功能 | 优先级 | 说明 |
|---|------|--------|------|
| F1 | 小程序登录绑定（openid） | 高 | `wx.login` code → 后端 `code2Session` 换 openid → 建/取家长账号 → 发本系统 JWT（parent 角色） |
| F2 | 家长 AI 问答（含引用） | 高 | 配额检查 → 家长域 RAG 检索 → 生成回答 → 落账本；回答附引用来源 |
| F3 | 高风险强制转人工 | 高 | 命中退费/收费/安全词表 → 直接建 `escalated` 会话，不生成答案 |
| F4 | 教师端"教学服务"接待 | 高 | 一级导航；escalated 置顶；查看/回复/关闭；未读徽标 |
| F5 | 后台家长版勾选 + 设置项 | 高 | 知识库列表"家长可见"开关；设置页配额两数字 + 高风险词表编辑 |
| F6 | 家长端客服页（小程序/H5 共用 `/client/service`） | 中 | 会话消息流 + 转人工按钮 |
| F7 | 评估种子与回归 | 中 | `parent_seed.jsonl` + 单测 + CI 门禁 |
| F8 | 快捷回复预置 | 低 | 退费/请假/课程查询话术，可编辑 |

## 2. 功能详述

### F1 小程序登录绑定
- 输入：`{ code }`（`wx.login` 获得）。
- 流程：后端用 AppID/Secret 调微信 `code2Session` → 得 openid → 查 `users.wechat_openid`：
  有则直接发 token；无则新建 `role=parent` 用户（username=`wx_{openid前12}`，随机密码）并发 token。
- 输出：`{ access_token, user }`（沿用现有 JWT 体制，`security.create_access_token`）。
- 业务规则：AppID/Secret 只放 `.env.prod` 环境变量，不入库；`code2Session` 出网失败返回 502 友好提示。
- 学员绑定：家长首次需绑定学员（绑定码/手机号核验），写 `Student.parent_user_id`（沿用 client 现有归属链，不另起表）。

### F2 家长 AI 问答
- 输入：`{ thread_id?, content }`，鉴权 parent JWT；匿名允许（无 token，按 anon_key 限 3 轮/日）。
- 流程：
  1. 配额检查：当日 `parent_service_messages` count（按 parent_id/anon_key）超限 → 429 + 友好文案（匿名引导绑定，家长引导转人工）。
  2. 高风险分类：命中词表 → 转 F3（不调 LLM，不花 token）。
  3. 检索：`retrieve(query, 家长域)` — 仅 `visible_to_parents=true` 且 `usable_doc_ids` 放行的文档；`min_similarity` 沿用全局门控（默认 0.35）；`diag` 回填。
  4. 生成：`_chat_model()` + 家长客服 system 人设（亲切、简洁、有依据；不编造；未知说不知道并给转人工入口）。
  5. 落账本：`threads`（首问建）+ `messages(user/assistant)`（assistant 行含 `tokens` 与 `retrieval_diag` JSONB）。
- 输出：`{ answer, refs:[{title,chunk}], thread_id, escalated:false }`；refs 由 `retrieval_summary(diag)` 展开。
- 业务规则：匿名不建 `parent_accounts` 行（只记 anon_key 计数）；家长域检索零命中 → 回答"暂未找到相关政策说明" + 转人工按钮，不编造。

### F3 高风险强制转人工
- 词表初版：退费/收费/价格/安全/受伤/事故/投诉/报警/律师/骨折/过敏/接送陌生人（上线前与园方确认终版，可在设置页编辑）。
- 输入命中任一词 → 建 thread（`status=escalated, risk_flag=true`）+ 存 user 消息 → 返回 `{ escalated:true, tip:"已转人工…" }`，不调 LLM。
- 家长也可主动点"转人工"（`POST /threads/{id}/escalate`，open→escalated）。

### F4 教师端"教学服务"接待（一级导航，现代大气）
- 入口：`ADMIN_NAV` 新增 `{ to:'/service', label:'教学服务', navKey:'nav_service' }`；权限键 `nav_service`（默认 True）+ `service_reply`（默认 True），同步 `PERMISSION_KEYS/KEY_DEFAULTS` 与 `TeacherPermission` 列（需迁移）。
- 接口：`GET /teacher/service/threads`（escalated 置顶、未读数）、`GET /teacher/service/threads/{id}/messages`、`POST .../reply`（教师回复落库 role=staff）、`POST .../close`。
- 页面三栏：左会话列表（escalated 红条置顶、绑定学员名、未读点）/ 中消息流（三色：家长/助手/教师，助手消息附引用折叠卡，高风险警示条）/ 右家长画像（绑定学员、班级、历史会话、快捷回复、设为已解决）。
- 视觉：浅底 + 品牌主色点缀，大圆角卡片（12~16px），柔和阴影，hover 浮起；空态插画 + 引导文案；移动端右栏抽屉收起。

### F5 后台家长版勾选 + 设置项
- 知识库列表每行加"家长可见"开关 → 写 `knowledge_documents.visible_to_parents`（默认 false；新文档默认对家长隐藏）。
- 设置页（`SystemSettingUpdate` 扩展）：`parent_anon_daily_limit`（默认 3）、`parent_daily_limit`（默认 50）、`parent_risk_words`（JSON 数组字符串，默认 F3 初版词表）。沿用 `system_settings` 单例行（id=1）+ `_ensure_columns` 轻量自迁移兼容。
- 权限：设置写操作沿用 `settings_manage` 门禁。

### F6 家长端客服页
- 路由 `/client/service`（`ClientLayout` 底导航加"客服"项，parent/student 均可见；student 沿用本人归属）。
- 消息流 + 输入框 + "转人工"按钮；助手回答渲染引用折叠卡。

### F7 评估与质检
- `backend/evals/datasets/parent_seed.jsonl` 约 15 条：政策问答（命中家长版）、隔离反例（问教师考勤/结算 → 零召回）、高风险（退费/安全 → escalated）、闲聊（直接答）。
- `tests/test_parent_service.py`：隔离断言（家长搜不到内部文档）、超限 429、高风险必转人工。
- 验收线：隔离反例 100% 不泄漏；高风险 100% 转人工；`pytest` 全过 + CI 编译门禁通过。

### F8 快捷回复（低优）
- 预置 4 条（退费流程/请假流程/课程查询/安抚话术），存 `SystemSetting` 新增 `parent_quick_replies` JSON 列；教师端右栏一键插入。

## 3. 数据模型（迁移 041~045）

- `041`：`users.wechat_openid`（String 64，唯一可空）+ 索引。
- `042`：`knowledge_documents.visible_to_parents`（bool，默认 false）+ 索引。
- `043`：`parent_service_threads(id/parent_id→users可空/anon_key/status open|closed|escalated/risk_flag/created_at)`。
- `044`：`parent_service_messages(id/thread_id→threads级联删除/role user|assistant|staff/content/tokens/retrieval_diag JSONB/created_at)`。
- `045`：`system_settings` 加 `parent_anon_daily_limit`(int 3)、`parent_daily_limit`(int 50)、`parent_risk_words`(text JSON)、`parent_quick_replies`(text JSON 默认[])；`teacher_permissions` 加 `nav_service`、`service_reply` 列（默认 true）。

## 4. 风险前置
- 生产容器出网 `api.weixin.qq.com` 联调前验证。
- 上线首批运营勾选 10~20 篇家长版文档。
- 晚高峰先压测；顶不住则 workers 1→2、DB 池 size 5→10（配置级改动，无需 Redis）。
