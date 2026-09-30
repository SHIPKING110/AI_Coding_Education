# 当前任务

> 用于跟踪项目当前任务状态。Claude 会读取和更新此文件。

## 进行中

- [x] **报告总结 AI 后台任务 + 年度季度缺 Q1 修复（2026-09-20，完成）**
  - [x] **Q1 丢失根因**：后端区间查询默认 UTC，Q1 起始 `01-01 00:00+08` 存为 `12-31 16:00Z` 早于下界被丢弃；前端又按浏览器本地时区二次过滤年份。修复：crud 统一按北京时间解释 naive 入参（`BEIJING`），季度查询两侧放宽 1 天；前端按北京时间边界+容差过滤并 Q1→Q4 正序；新增 `test_yearly_includes_q1_boundary` 回归用例
  - [x] **AI 生成进度**：后端新增 `POST /{id}/ai-draft-jobs`（202 返回 job_id，后台线程执行）+ `GET /{id}/ai-draft-jobs/{job_id}` 轮询；同步 `ai-draft` 保留给测试/旧客户端。前端 SummaryView 与 ReportsView 提交即关弹窗，顶部任务条显示已用时（约 20-60 秒），完成后自动回填，localStorage 持久化支持刷新回来继续等
  - [x] 验证：ruff 全过；`test_report.py + test_report_rollup.py` 21 例全绿；前端 vue-tsc + vite build 通过
- [x] **学员管理账号规则完善（2026-09-15，完成）：家长账号=家长手机号，学员账号=可自定义前缀+家长手机号**
  - [x] **家长账号**：新增/编辑学员弹窗「联系电话」改名为「家长手机号」（明确即家长登录账号）；新建家长账号登录名默认=家长手机号数字部分，注册时同步写入 users.phone；同手机号已注册返回友好提示「该手机号已注册过家长账号，请直接搜索绑定」（多孩共用一个家长账号）
  - [x] **学员账号**：登录名=前缀+家长手机号；弹窗新增「账号前缀」输入（默认=学员姓名拼音缩写如 露露→ll，取不到回退 st，可自定义以区分同家长多孩子），实时预览最终登录名；前缀/姓名/手机号变化自动联动（手动改过前缀则不覆盖）；学员账号不写 users.phone（该列唯一，同家长多孩子会 500）
  - [x] **缴费名单一键补建**：默认登录名规则同步改为 姓名缩写前缀+家长手机号（原 st+电话），冲突提示注明「同一家长多个孩子请改前缀」；文案与 tooltip 全部对齐
  - [x] **后端**：`POST /auth/register` 新增 phone 唯一冲突前置校验返回 409 "Phone already exists"（crud user.get_by_phone），避免 users.phone 唯一约束触发 500
  - [x] 验证：pytest 全绿（新增手机号冲突 409 回归用例）；ruff 零错误；前端 vue-tsc + vite build 通过
- [x] **AI 习题课堂作业按学员发布 422 修复（2026-09-15，完成）**
  - [x] **根因**：`confirmPublish` 课堂作业分支把 `publishClassIds`（课堂作业弹窗无班级复选，该数组恒为 []）直接传给 `class_ids`，触发后端 `AssignmentPublishIn.class_ids` min_length=1 的 422 校验
  - [x] **修复**：课堂作业发布时 `class_ids` 用所选学员所在班级去重兜底（服务端据此落主班级/计算通知范围），回退链=学员所在班级→已发布班级→作业主班级；可见性仍完全由 `target_student_ids` 定向学员决定（后端 `list_for_student` 定向优先口径不变）
  - [x] **学员候选收敛修复**：`openPublish` 教师默认 `teacherId=自己`，但教师本人可能未被设为班级带教教师（`teacher_id` 为空），导致学员候选被限定为「自己带教的学员」、看似只能发布给少数人；改为教师/管理员默认均不限教师（仅按校区收敛），教师可按需再选自己收敛
  - [x] **边界**：所选学员均未分班且作业无主班级时，前端给明确提示「请先在学员管理中为其分班，或改用课后作业按班级发布」，不再直接抛 422
  - [x] 验证：前端 vue-tsc + vite build 通过，无 linter 错误
- [x] **AI 习题三件套（2026-09-15，完成）：统计口径说明 + 批改模式可选 + 批改中心/作业管理**
  - [x] **问题1·统计口径**：后端口径本就正确（定向作业=定向学员数，常规=发布班级学员去重，见 `submission_stats`）；前端批改页标题下新增口径说明行（定向显示「定向发布的 N 名学员」，常规显示「发布班级（A、B）学员去重」）
  - [x] **问题2·批改模式可选**：后端 `review_mode` 列/迁移/schema/客户端门禁本就存在（缺前端入口）；编辑器新增「批改模式」切换（自动批改/教师确认后公布），发布弹窗新增同款设置（打开回填作业当前值，随发布生效）；`AssignmentCreateIn/update/publish` 与 `AssignmentOut` 类型打通 `review_mode`
  - [x] **问题3a·批改中心**：新路由 `GET /assignments/grading-center`（crud `list_published_for_grading`：跨作业聚合应作答/已提交/待批改/已批改/最新提交时间，默认仅有待批改，待批改多+最新提交优先排序；注意定义在 `/{assignment_id}` 之前防路由吞没）；新页面 `GradingCenterView`（进度条+待批改徽标+一键进批改）+ 左侧导航「批改中心」入口；AI 习题页顶部「批改中心 · N 份待批改」快捷入口
  - [x] **问题3b·作业管理**：作业列表新增标题搜索（300ms 防抖）+ 班级下拉 +「只看有待批改」复选；后端列表新增 `keyword` 标题搜索 + `pending_review` 待批改筛选 + 每项聚合 `submitted/graded/pending_review`（crud 一次查全无 N+1）；列表行直显「已提交 x/y」+ 可点「N 待批改」角标 + `teacher_confirm` 胶囊；总数口径取 `submission-stats`（仅对有提交的作业请求）
  - [x] 验证：pytest 全量 62 例通过（`test_assignment_scoring_makeup_flow` 内扩展：统计口径断言 + 批改模式创建/发布覆盖 + teacher_confirm 门禁前后对照 + 列表聚合/待批改筛选/批改中心断言）；ruff 零错误；前端 vue-tsc + vite build 通过

- [x] **班级家长会 PPT 重提炼去重（2026-09-12，完成）：无变化提示 + 强制二次确认**
  - [x] **素材指纹**：`ClassPpt` 新增 `material_hash`（迁移 c0ffee000012 已应用开发库）；`_material_fingerprint()` 对 全班评估正文（summary/progress/to_improve/subjects 去空白）+ 班级统计 + 课堂反馈 + 能力均分 取 sha256——updated_at/标题/排版字段不参与，AI 无实质变化重跑不误判
  - [x] **提交拦截（后端）**：`POST /evaluations/class-ppt`——①同班同周期在途任务 → 409「已有生成任务在进行中」防连点重复排队（dedup_key 全局查 pending/running）；②已有落库记录且指纹一致且未 force → 409「素材无变化，无需重新提炼；如需强制重提炼请二次确认」；`force=true` 放行并落库新指纹
  - [x] **预检接口**：新增 `GET /evaluations/class-ppt/fingerprint` 返回 `{has_record, record_id, unchanged, running, running_stage, evaluated_count}`，权限复用班级可见性；`ai_tasks.create_task` 支持 `dedup_key` + `find_running_by_dedup(owner_id=None 全局)`，向后兼容出题/优化任务
  - [x] **前端预检 + 二次确认**（EvaluationsView.vue）：有落库记录时点「AI 重新提炼并生成」先调 fingerprint 预检——running 直接红字拦截；unchanged 弹 ConfirmDialog「素材无变化，仍要重新提炼？」（danger，明确提示会覆盖手工编辑内容），确认后 `force=true` 重新提交；后端 409 兜底同样转二次确认；切换班级/周期自动重置确认态；预检失败（404/400）不阻塞首次生成
  - [x] 测试：pytest 72 例全绿（扩展 test_class_parent_ppt：预检 unchanged=true → 无 force 重提 409 含「无变化」→ force=true 202 → 改评估内容后 unchanged=false 直接 202）；ruff 零错误；前端 vue-tsc + vite build 通过

- [x] **班级家长会 PPT 反馈修复轮四（2026-09-08，完成）：面板联动 + 排版重写 + 预览编辑**
  - [x] **面板筛选联动修复（问题 1）**：`EvaluationsView.vue` 新增两组 watch——①校区/教师变化 → `loadPptClasses()` 即时重载班级下拉（校区切换时清空不属于该校区的教师），不再需要重开面板；②班级/周期起止变化 → `loadRoster()` + `loadClassPptRecord()` 即时加载学员评估状态名册与最近 PPT 记录，窗口内选完即显示（此前名册只在打开面板瞬间加载一次）
  - [x] **排版引擎重写（问题 2·格式乱/内容重叠）**：`pptx_builder.py` 新增 `_fit_size/_truncated_lines`（按 CJK 字宽估算行数，超框自动缩小字号至 12pt 下限、仍超按行截断加「…」），`_bullets` 全量接入；能力条行高动态压缩（最多 6 行不再溢出页底，单学员 PPT 学科能力条同步修复）；进步之星荣誉墙重写为姓名+点评同卡（3 列×2 行，点评自动缩字截断，不再互相叠压）；「班级亮点」与「进步之星」拆成两页；新增「班级整体情况」页渲染此前被丢弃的 class_summary
  - [x] **班级 PPT 文案落库 + 预览编辑（问题 2·无法二次修改）**：新表 `class_ppts`（迁移 c0ffee000011，class_id+周期唯一，content 7 字段 + stats/averages/honor_roll 素材快照）；生成任务 runner 落库（后台线程自开 SessionLocal）；`GET /class-ppt/latest` 优先查库（source:'db' 可编辑，历史内存任务回退 source:'task' 仅下载）；新增 `PATCH /class-ppt/{record_id}`（字段级合并 → 用存量快照直接重排版，不调 LLM 秒级完成；权限复用班级可见性）
  - [x] **面板预览编辑 UI**：名册下方新增「PPT 文案预览与编辑」卡片——班级统计 chips + 能力均分 + 封面标题/整体情况/能力点评/亮点/改进/安排/建议 7 个字段（与幻灯片页码一一对应），「保存并重新生成 PPT」秒级重建并刷新下载链接，「撤销修改」回填最近保存；原生成按钮在有落库记录时改为「AI 重新提炼并生成」（title 提示会覆盖手工编辑）
  - [x] 测试：pytest 72 例全绿（新增 落库 latest 断言/PATCH 重建与 403/超长文案 smoke）；ruff 零错误；前端 vue-tsc + vite build 通过；迁移已应用开发库；后端已重启、真实 LLM 链路冒烟通过（生成→落库→编辑→重排版→下载 44KB PPTX）

- [x] **班级家长会 PPT 进度可视化修复（2026-09-06，完成）**：
  - [x] **面板"一直排队"根因修复**：此前清理重复代码时误删了面板任务的轮询 watch，面板状态永不更新（右侧 AI 任务卡走 store 轮询所以显示已完成）。重构为：面板与 AI 任务卡共用 aiTasks store 单一状态源（classPptTask 由 store 任务派生），彻底消除两套轮询不同步
  - [x] **分阶段进度**：后端 ai_tasks 支持 runner 上报阶段（report 回调，签名探测向后兼容出题/优化任务）；班级 PPT 任务上报 排队→AI 提炼汇报内容→排版生成→完成 四阶段，完成文案按任务类型区分（"已完成，可下载班级家长会 PPT"）
  - [x] **面板进度 UI**：步骤条（排队等待 / AI 提炼汇报内容 / 排版生成 PPT / 完成，当前步高亮、已完成打勾）+ 当前阶段说明 + 已进行时长（每秒跳动）；打开面板自动接管进行中/已完成任务（按 task id 记忆 + 任务列表按班级名/class_id 恢复，刷新页面也能接上）
  - [x] **AI 任务卡**：班级 PPT 任务完成后卡片出现「查看 / 下载 PPT」入口（点击重新打开面板定位下载）
  - [x] 验证：pytest 71 例全绿、ruff 零错误；前端 vue-tsc + vite build 通过；前后端已重启（8000/5173）

- [x] **班级家长会 PPT 名册口径修正（2026-09-06，完成）**：
  - [x] **草稿也算已生成**：名册周期匹配从「完全一致」改为「重叠」（评估覆盖期与所选周期有交集即算已生成，多份重叠时优先展示已发布、其次最近更新）；解决"草稿评估显示未生成"的问题
  - [x] **标识与按钮**：徽标改为 已生成·已发布 / 已生成·草稿 / 未生成；已生成学员同时提供「查看」（直接打开评估详情）与「重新生成」（按该评估自身周期载入编辑器回填内容）两个操作；未生成仍为「去生成」
  - [x] **草稿可生成班级 PPT**：生成门槛从「至少 1 份已发布」放宽为「至少 1 份评估（草稿/已发布均可）」；后端 collect_class_material 纳入草稿评估（published_evaluations → evaluations），班级 PPT 面板在有草稿时提示"建议发布后再生成"
  - [x] 验证：pytest 70 例全绿（class-roster 断言 generated=2/published=1、仅草稿可生成班级 PPT）、ruff 零错误；前端 vue-tsc + vite build 通过

- [x] **反馈修复轮三（2026-09-05，完成）：评估打印 + 班级管理 2 项**
  - [x] **评估打印/导出 PDF 优化**（EvaluationDetailDialog.vue）：①打印时把浏览器页眉中央标题改为「学习评估 · 报告名」（打印后 afterprint 恢复），不再显示系统名；②打印时隐藏底部「评估教师：X · 发布于 YYYY-MM-DD」签名行（应用内容随打印 CSS 隐藏）；③弹窗内新增屏幕提示「打印时可在系统弹窗取消勾选「页眉和页脚」，去除日期/网址」——日期时间/URL 属浏览器自带页眉，代码无法移除，需用户勾选一次后浏览器会记住
  - [x] **班级管理筛选升级**（ClassesView.vue + 后端）：①筛选栏新增 校区下拉（按带教教师所属校区归口）、教师改为可搜索下拉（SearchableSelect，教师多时输入姓名/登录名快速定位）、开班日期范围（起~止）；②后端 /classes 新增 `start_date_from/start_date_to` 区间筛选；③每张班级卡新增「查看」→ 详情弹窗（GET /classes/{id} 返回学员名单：姓名/电话/校区/课时/在读状态，含 在册/在读/课时不足 统计卡），原教师下拉保留兼容
  - [x] 验证：后端 pytest 68 例全绿、ruff 零错误（import 整理）；前端 vue-tsc + vite build 通过；班级详情接口实测返回学员名单、日期区间筛选 total 正确；后端已热重载
- [x] **家长成长页渲染崩溃修复（2026-09-05 补）**：`ClientEvaluationsView` 的 `growth` 计算属性在「仅 1 份已发布评估」时 `subjectsOf(previous.value)` 传入 null → `null.content` 抛 TypeError，render 函数异常导致整页停在骨架屏（报错 `Cannot read properties of null (reading 'content')`）。修复：`contentOf/subjectsOf/summaryOf/statNum/publishedKey` 全部改为 null 安全（`ev?.` + 空对象兜底），只有一份评估时成长轨迹正常展示「本期新增」；构建通过
- [x] **M6 班级家长会 PPT 重构（2026-09-06，完成）**：
  - [x] **班级维度生成**：新增 `POST /evaluations/class-ppt`，按班级 + 周期聚合该班所有学员的已发布评估、课堂反馈与阶段统计，生成面向全班家长的汇报 PPT；并新增 `GET /evaluations/class-ppt/latest` 回查最近一次结果
  - [x] **名单查漏补缺**：新增 `GET /evaluations/class-roster`，班级内逐个学员标注本周期评估是否已生成（草稿/已发布/未生成）；班级 PPT 面板可直接查看已生成评估，未生成则一键跳转到评估编辑器并自动带出学员与周期
  - [x] **筛选升级**：班级 PPT 面板增加「校区→教师→班级」筛选链，教师账号默认筛到自己校区/自己带教班级；评估编辑器的学员下拉也补了「校区→教师→班级→学员」快速筛选，选人更快
  - [x] **内容不再照搬个人评估**：后端新增班级素材收集 `collect_class_material`、班级汇报文案生成 `generate_class_meeting`（LLM + 兜底模板）、班级版 `build_class_meeting_ppt`；PPT 结构改为“封面 / 班级学习数据 / 能力培养 / 班级亮点与进步之星 / 共性问题与改进 / 下阶段教学安排 / 给家长的建议 / 结尾”
  - [x] **前端入口升级**：评估工作台新增「班级家长会 PPT」浮层，选择班级与周期后提交异步任务，完成后可直接下载；班级筛选与评估编辑器增加校区/教师/班级/学员联动筛选，未生成评估的学员可一键「去生成」并自动带入学员+周期
  - [x] 验证：后端 pytest 70 例全绿、ruff 零错误；前端 vue-tsc + vite build 通过；班级 PPT 构建器本地 smoke test 通过

- [x] **反馈修复轮二（2026-09-05，完成）：订单/学员筛选/催缴跳转/家长成长页 4 项**
  - [x] **订单管理「全部」Tab 首屏空白修复**：`onMounted` 中 `Promise.all([listClientPackages(), ...])` 调用了家长端专用接口 `/client/packages`（管理端 403）导致首个 `load()` 从未执行 → 改为先独立加载订单列表，课时包/校区选项用管理端接口（`/lesson-packages`、`/auth/campuses`）`Promise.allSettled` 异步填充，任一接口失败不再阻塞列表
  - [x] **学员管理筛选**：新增筛选栏（校区 / 状态 / 课时剩余范围 min~max / 班级名称·科目搜索 / 班级校区 / 班级教师 / 班级下拉联动）；后端 `/students` 新增 `campus`、`status`、`lesson_balance_min/max` 参数（CRUD `_apply_filters` 扩展，count 用 distinct 防 join 翻倍）
  - [x] **催缴名单跳转修复**：侧边栏链接 `/collection` 在路由表中缺失，落入 catch-all 重定向到 `/`（学员管理）→ 补回 `collection` 路由指向 CollectionView
  - [x] **家长端成长模块加载修复**：`client` store 的 `loadMe` 在途请求并发去重（原来 `if (this.loading) return` 会让布局/页面并发调用时提前返回、`me` 未就绪即结束加载，成长页一直转圈）→ 共用同一 Promise；成长页 `load()` 兜底错误态 + 「重新加载」按钮
  - [x] 验证：后端 pytest 68 例全绿、ruff 零错误；前端 vue-tsc + vite build 通过；新筛选参数接口实测生效（campus/status/lesson 范围均返回正确 total）；后端已热重载加载新代码
- [x] **反馈修复轮（2026-09-05，完成）：家长端提交弹窗 + 评估模块 2 项**
  - [x] **家长端提交作业弹窗美化**（ClientAssignmentDetailView.vue）：window.alert/confirm 全部替换——①提交前确认弹窗（发送图标 + 已完成 X/Y 题摘要 + 客观题立即出分/编程题老师批改说明 + 「提交后无法修改」警示）；②提交结果弹窗（对勾/警示徽标动画 + 达标标题 + 自动判分/待批改/当前得分统计卡）；③空题与失败提示复用 ConfirmDialog（新增 objectiveCount/manualCount computed）
  - [x] **评估模块免先保存草稿**（EvaluationsView.vue）：新增 validateRequired(base/content)——AI 生成仅需学员+周期，AI 优化/发布/生成 PPT 额外要求综合总结非空，缺失给具体红字提示；操作前自动 save() 落盘（新评估自动建草稿，发布的是编辑器当前内容）；对应按钮不再因无 current 而禁用，AI 面板提示同步更新
  - [x] **AI 列表输出格式修复（根因在后端）**：llm.py 的 _clean() 对 LLM 返回的数组 str() 出 "['a','b']"——新增 clean_listish_text()：list/tuple → 「；」拼接；历史脏数据（Python repr 字符串）→ json.loads / 正则引号项解析后同样拼接；progress/to_improve/suggestions/summary 走此清洗。pptx_builder.py PPT 三字段同样清洗（旧数据兼容）。前端新增 utils/text.ts cleanListishText()，编辑器回填/AI 回填/EvaluationDetailDialog 三处兜底
  - [x] 验证：pytest 68 例全绿；ruff 全库零错误；vue-tsc + vite build 通过；后端已重启加载新代码（Windows --reload 未自动生效，手动 taskkill 后重启）

- [x] **M6 反馈修复轮（2026-09-04，完成）**：家长/教师反馈的 3 个问题定位修复
  - [x] **发布弹窗题型分值只显示本次作业包含的题型**：分值配置网格由「固定 5 题型」改为 computed 去重取当前题目类型（`publishTypeKeys`/`publishTypeScoreEntries`），总分仍按实际题目逐题累计；AI 生成 3 种题型时仅显示这 3 行
  - [x] **「请至少选择一个发布班级」提示不消失修复**：确认发布前先清空错误（不再残留上次校验失败的红字）；勾选班级 watch 到长度 >0 时自动清除该提示；外层班级容器由 `<label>` 嵌套内层 `<label>`（非法 HTML，点击会触发外层隐式关联的搜索框）改为 `<div>`，杜绝勾选异常
  - [x] **家长端只收到通知收不到作业修复**（多孩场景定位）：通知文案与 data 增加学员名/学员 id/作业 id（`publish_assignment_notification`/`publish_graded_notification` 签名扩展，调用方传入 assignment_id）；家长端通知点击按 data.student_id 自动切换孩子并携带 `?student_id=` 跳转；作业列表/作业详情/反馈/评估页支持路由学员上下文自动同步 + 切换学员自动刷新
  - [x] **评估「加载失败」根因**：开发库 `child_code` 停在 alembic c0ffee000009，`evaluations` 表从未建（M6 只跑了测试库）→ GET /evaluations 500。执行 `alembic upgrade head`（c0ffee000010）后评估列表/素材预览/创建/发布/家长端可见全部 200
  - [x] 验证：vue-tsc + vite build 通过；后端 pytest 68 例全绿（先前多文件并行时 4 例 AI 任务轮询超时为单 worker 执行器排队偶发，串行全量两轮均过）；E2E 脚本验证通知 data 携带 student_id/assignment_id、家长端作业与评估可见、数据已清理
  - [x] 备注：uvicorn --reload 在 Windows 下检测到变更却未真正重启 worker（日志只见 Reloading 无 Shutting down），改代码后需留意服务进程；已重启干净实例
- [x] **M6 评估打磨二轮（2026-09-04，完成）**：详情弹窗雷达图/打印 + 家长端成长页完整化 + 管理端工作台体验
  - [x] **评估详情弹窗（EvaluationDetailDialog.vue）增强**：
    - **SVG 能力雷达图**（纯手写无依赖，3~8 个能力项时展示）：5 层同心环 + 轴线 + indigo→cyan 渐变数据多边形 + 顶点圆点 + 外圈能力名标签（按位置自适应 anchor/y 偏移）+ 1~5 星图例
    - **打印/导出 PDF**：底部「打印 / 导出 PDF」按钮 window.print()；全局 print 样式（body.eval-detail-open 时隐藏应用其余 DOM、弹窗铺满整页、隐藏关闭/下载/打印按钮、print-color-adjust: exact 保留品牌渐变）
    - 封面右上「已发布」金色斜置印章（仅 published）；底部署名「评估教师：XX · 发布于 日期」，草稿态提示「内容以最终发布为准」
    - 弹窗打开时锁定背景滚动（body.overflow=hidden）+ body.eval-detail-open 类，关闭/卸载恢复
  - [x] **家长端评估页（ClientEvaluationsView.vue 完整化）**：
    - **成长概览 4 卡**：出勤率（到课/请假次数）、课时消耗（节+周期）、作业得分率（有数据才显示）、累计评估份数（含周期内反馈篇数）
    - **能力成长轨迹面板**：最近两次评估同名能力项对比——当前星级 + ↑上升/↓下滑/持平徽标 + 「本期新增」识别 + 等级文案徽标 + 一句话点评
    - **年份筛选 chips**（≥2 个年份时出现）+ 按发布时间倒序 + 分页改为本地切片（一次拉 50 条）
    - 卡片增强：能力项彩色 chips（按星级着色，最多 4 个+N）、「含家长会 PPT」标记、发布日期行
    - **骨架屏**（概览卡+列表卡 shimmer 动画）替代原「加载中」文案
  - [x] **管理端评估页（EvaluationsView.vue）体验**：
    - **素材预览不再依赖已保存草稿**：选学员+周期即拉 material/preview（原逻辑必须有已保存评估才显示素材，教师无从核对 AI 依据）
    - 快捷周期预设组：近 1 / 3 / 6 个月（原仅「近 3 个月」单按钮）
    - 学员信息条：校区 / 班级数 / 剩余课时（≤10 爆黄 warn）
    - **Ctrl+S / Cmd+S 保存草稿**（全局 keydown，卸载时移除）
    - 历史评估：状态筛选 chips（全部/草稿/已发布）+ PPT 徽标（已生成家长会 PPT 的评估）
    - AI 按钮进行中态：本页任务未完成时「AI 生成草稿/对话优化」禁用并显示「生成中…/优化中…」+ 进行中提示文案
  - [x] 验证：vue-tsc + vite build 通过（EvaluationDetailDialog 10.85KB gzip 4.24KB、ClientEvaluationsView 8.61KB、EvaluationsView 19.92KB gzip 7.77KB）；后端无改动

- [x] **M6 评估打磨轮（2026-09-04，完成）**：评估页视觉样式 + 评估详情弹窗 + 家长端评估页完整化
  - [x] **评估详情弹窗（共享组件 `EvaluationDetailDialog.vue`）**：管理端/家长端复用——评估「报告单」式渲染：品牌渐变封面（学员/周期/教师）+ 周期统计 chips（出勤率/到课/请假/课时消耗/反馈/作业得分率）+ 综合表现 + 学科能力（1-5 星 + 等级徽标 + 点评）+ 进步亮点/待提升项/家长建议（条目圆点列表）+ 底部「下载家长会 PPT」（uploads 公开静态可下）+ Esc/遮罩关闭
  - [x] **评估页视觉样式（EvaluationsView.vue 全量重写）**：原页面无任何 `<style>` 且 AI 结果不回填。新增：页头状态胶囊（草稿/已发布）+ 发布/撤回/预览详情/生成 PPT/查看 PPT/删除（ConfirmDialog，仅草稿）操作区；双栏工作台（左评估编辑器 / 右素材+历史）；学员改 **SearchableSelect 可搜索**（路由 `/students/:id/evaluations` 带参进入自动选中）；「近 3 个月」一键周期；学科能力行内 **1-5 星级点击打分**（等级文案：待观察~非常优秀）替代裸数字；AI 面板（indigo→cyan 渐变）：补充说明+生成草稿 / 优化指令+对话优化，未保存草稿时禁用并提示；素材预览统计卡格 + 反馈折叠摘要；历史评估卡（状态徽标 + 摘要 + 载入编辑/详情）；**AI 任务完成自动回填并保存**（watcher 追踪本页提交任务 id，done→回填→save，failed→报错提示）；空态与移动端适配
  - [x] **家长端评估页完整化**：新增 `ClientEvaluationsView.vue`（渐变 hero + 评估卡片列表：徽标/标题/周期·教师/摘要/查看详情箭头 + 分页 + 详情弹窗），路由 `/client/evaluations` + 底部导航「成长」第 5 项 + 首页快捷入口「学习评估」+ 首页「最新学习评估」横条面板（最新一篇摘要，点击进列表）；后端客户端接口改返回 **`ClientEvaluationOut` 精简视图**（剔除 teacher_id/student_id/ai_draft 内部字段，家长不可见 AI 原始稿）
  - [x] **通知页打磨**：补齐缺失的全部样式（通知列表/类型徽标/未读高亮/分页）；补 `evaluation_published` 类型文案与金色徽标 + 点击跳评估页；「学习评估」区条目可点开详情弹窗 + 分页 + 「查看全部」入口
  - [x] 验证：pytest **68 例全绿**（修复 M5 增强回归 3 例：`set_student_targets` 覆盖设置前先 flush 删除避免同唯一键 UniqueViolation；lesson-records 断言 201；订单校区/状态/时间筛选断言改唯一标签规避共享测试库串扰）；ruff 全库零错误；vue-tsc + build 通过（EvaluationsView 18.5KB gzip 7.2KB、ClientEvaluationsView 3.5KB、EvaluationDetailDialog 8KB）

- [x] **M4 AI 习题（2026-09-01，完成）**：举一反三、作业模式、题目模板编辑、作业发布（OQ-03=仅录入用例，判题引擎 M5）
  - [x] **表结构（迁移 c0ffee000005 已应用）**：`assignments`（作业：teacher_id/class_id/title/description/deadline/status draft↔published/published_at）+ `questions`（题目：order_no/type/stem/options/answer/analysis/difficulty/test_cases/language）+ `submissions`（提交：answers/judge_results/score/total/status，M5 作答使用，M4 建表预留）
  - [x] **AI 出题（FR-AI-01/04/05）**：`POST /assignments/ai-generate` 双模式——`similar` 举一反三（原题题干+可选答案+题数+难度 → 相似题）与 `homework` 作业模式（知识点提示语+题数+难度+题型选择 → 整套题）；`llm.generate_questions` 结构化 JSON 输出 + 字段规整（字符串答案转 int、判断转 bool、编程题默认 python）；`POST /assignments/ai-refine` 对话优化单题（原题+修改要求 → 重写）；解析失败兜底生成可编辑占位题
  - [x] **AI 异步任务化（用户反馈修复，2026-09-02）**：原「AI 出题失败」根因=真实 LLM 生成 20-60s 超过前端 axios 15s 超时 → 改为 **提交即返回任务**（`app/services/ai_tasks.py` 后台线程池串行执行，内存保留 30 个任务，单 worker 排队）+ `GET /assignments/ai-tasks` / `{id}` 轮询（阶段 stage：排队中/生成中/已完成/失败 + 错误信息）；教师仅见自己任务，admin/staff 全量；前端 `stores/aiTasks.ts` 全局轮询（1.5s，切页不中断，刷新后 bootstrap 恢复）+ AssignmentsView 任务卡（状态点+进度条+阶段文案+「可关闭弹窗去其他页面」提示）+ AdminLayout 右下角生成中浮窗 + 侧边栏徽标 + 完成 toast（点击跳回 AI 习题）；对话优化同异步化
  - [x] **保存/发布修复（用户反馈，2026-09-02）**：①「加入作业」后**自动保存为草稿**（applyTaskResult → saveAssignment），刷新不再丢；②新草稿无标题自动填「AI 生成作业草稿」（可改）；③openPublish 对未落盘新草稿先自动保存再打开发布弹窗（原逻辑 editing=null 直接 return 导致打不开发布窗）；④saveAssignment 返回 boolean 供调用方感知校验失败
  - [x] **发布班级三级筛选**：发布弹窗 校区 → 教师 → 班级 级联（SearchableSelect + watch 联动，同课后反馈模式），班级随 校区/教师 收敛，已选失效自动清空
  - [x] **UX 打磨（用户反馈，2026-09-02）**：①新增 `components/ConfirmDialog.vue`（图标+标题+文案+危险按钮，替换原生 window.confirm），作业删除/撤回弹窗化；②编辑器题操作按钮 ↑上移/↓下移（实为数组交换，题序变但当前题不变，易误解）改为 **◀ 上一题 / ▶ 下一题**（prevQuestion/nextQuestion 仅切换 activeIdx）；③**AI 出题弹窗新增「作业标题 *」输入框**（aiTitle，默认取当前标题/占位名，openAi 时初始化），「加入作业」时写入 form.title 再自动保存 → 用户输入标题立即生效，发布即所见（原默认名盖掉输入）
  - [x] **交互细节（用户反馈二轮，2026-09-02）**：①ConfirmDialog 按钮改到提示语**下方水平居中**（原右侧竖排）；②SearchableSelect 新增 **group 互斥展开**（同一组下拉一次只开一个，发布弹窗校区/教师 group="publish"）；③发布弹窗**默认预选当前账号的校区与教师**（教师=自己，管理员/教务=全部）；④AI 弹窗「生成题目」**按钮常驻**（任务完成后也能继续生成新一组）；⑤题数语义改为**每种题型各生成 N 题**（选 N 种题型×每类 count = 总数，弹窗有说明文案 + llm prompt 已调整）；⑥难度由 1-5 改为 **1-10 少儿编程考级等级**（后端 QuestionIn/Update/AiGenerate le=10、llm prompt 1-10 级、编辑器星级+下拉 10 级、AI 弹窗 1-10 级）
  - [x] **多班级发布（用户反馈二轮，2026-09-02）**：新增 `assignment_class_links` 表（迁移 c0ffee000006 已应用，回填存量已发布作业）+ 模型 AssignmentClassLink；`POST /publish` 改为 `class_ids[]`（可一次多选、可对已发布作业**追加新班级**、已发布班级 400 排重、班级不存在 404）；撤回时清空发布记录（可重新选班）；列表按班级过滤改为命中主班级或任一发布班级；`AssignmentOut` 增加 `published_class_ids / published_class_names`；前端发布弹窗改为**班级复选列表**（搜索过滤 + 已发布班级禁用灰显 + 本次发布标签 + 已发布提示），确认按钮显示选中班级数
  - [x] **历史题目池 + 发布弹窗修复（用户反馈，2026-09-02）**：①发布弹窗班级复选框与文字**垂直/水平对齐修复**（根因 `.modal label` 的 `display:block` 特异性高于 `.class-item` 的 flex，改为 `.publish-classes .class-item` 提权 + 复选/名称/标签间距与垂直对齐）；②**历史题目复用**：`GET /assignments/questions/pool`（仅**已发布**作业的题目，跨教师可见，条目含所属作业标题 assignment_title；keywords=作业标题模糊 / types=逗号分隔多题型 / difficulty_min~max 难度区间 筛选 + 分页 limit/offset）；前端编辑器工具栏新增「**历史题目**」按钮 → 弹窗（作业标题搜索栏 + 题型多选 chips + 难度区间双下拉 + 结果列表勾选 + 分页 10/页，勾选跨页保留），「加入作业」以 QuestionIn 追加并**自动保存草稿**；③后端 uvicorn 改 **--reload** 运行（本次「历史题目 404」根因=旧进程未重载新路由）
  - [x] **作业 CRUD**：创建（含题目）/列表（分页，教师只看自己，admin/staff 可全量+按教师/班级/状态筛选）/详情/更新/删除（仅草稿，已发布先撤回）/发布（**必选班级+可选截止时间，至少 1 题**）/撤回
  - [x] **题目管理**：追加（order_no 续排）/编辑单题（题干/选项/答案/解析/难度/编程题语言+用例）/删除（自动重排）/排序（PUT reorder）
  - [x] **前端 AssignmentsView.vue**（侧边栏「AI 习题」入口，`/assignments`）：作业列表（状态筛选+分页）+ 编辑器（标题/说明/AI 出题/保存/发布/撤回/删除/下载文档）+ **题号导航按钮**（每题一页）+ 题型切换（单选/多选/判断/代码填空/编程题）+ **答案与解析默认折叠**（FR-AI-03/07）+ 编程题用例编辑（M4 仅录入）+ AI 出题弹窗（举一反三/作业模式双 Tab，生成结果勾选加入）+ 对话优化弹窗 + 发布弹窗（SearchableSelect 选班级+截止时间）+ **文档下载**（txt，含答案/解析/用例，FR-AI-13 P1）
  - [x] 权限：出题/作业写操作 admin/staff/teacher；教师仅自己；家长/学员 403；前端教师可编辑、非教师隐藏操作按钮
  - [x] 验证：pytest 54 例全绿（M4 新增 7 例：CRUD/发布/权限/AI 生成/规范化/兜底/筛选）；ruff 全库零错误；vue-tsc + build 通过（AssignmentsView 26KB gzip 9.1KB）；live 真实 DeepSeek 出题 2 题成功 + CRUD/发布/撤回/删除/403 全流程通过
- [x] **M5 客户端（2026-09-03，完成）**：课时/反馈查看、订阅（模拟支付）、提醒通知、在线作业作答（判题 OQ-03=客观题自动判+编程题教师人工批改；通知 OQ-01=应用内+微信预留）
  - [x] **表结构（迁移 c0ffee000007/000008 已应用）**：`notifications`（站内通知：type 上课提醒/低余量/订单到账/反馈发布/作业发布/批改完成 + title/content/data/read_at，data 存关联键+reminder_key 幂等去重）+ `students.student_user_id`（学员本人登录账号，唯一索引，家长绑定沿用 parent_user_id 支持多孩）
  - [x] **账号绑定**：`GET /auth/users`（admin/staff 按角色/关键字筛选用户，学员编辑弹窗绑定家长/学员账号）；家长账号 parent_user_id 可绑多个孩子；学员账号 student_user_id 绑定本人；`/client` 系列接口仅 parent/student 可访问（其他角色 403）
  - [x] **客户端 API（`/api/client`）**：`GET /me`（账号+名下学员：课时余额/low_balance/班级/下一节课/未读数，进入时惰性生成提醒）；学员详情/课时流水/已发布反馈（仅 published）/课表；`GET /packages` 在售课时包；`POST /orders` 下单 → `pay` 模拟支付（pending→paid 待确认）→ 取消；`GET /orders` 我的订单；作业列表（发布班级命中+我的状态）/详情（**题目不含答案/解析/用例防作弊**）/`answers` 保存进度（自动+手动，截止后 400）/`submit` 提交
  - [x] **判题引擎（OQ-03 决策=客观题自动判+编程题人工批改）**：`app/services/judge.py` 单选（索引比对）/多选（集合比对）/判断（bool）/代码填空（空白归一化比对）自动判；编程题标记「待教师批改」不沙箱执行（安全）；提交时空题校验返回未作答题号（前端跳最小题号）；提交后状态 submitted（待批改），教师批改后 graded
  - [x] **订阅模拟支付（FR-CL-04~08，OQ-06=管理员确认到账）**：`/api/orders` 管理端（admin/staff）订单列表（状态筛选+分页）+ `confirm` 确认到账（课时入账+流水 ref_id=订单+通知家长）+ `cancel`；前端 OrdersView（状态 Tab+确认/取消弹窗）
  - [x] **通知系统**：`/api/notifications` 列表（分页/只看未读）/单条已读/全部已读/未读数；业务联动通知——反馈发布（feedback_published）/作业发布（assignment_published）/订单到账（order_confirmed）/批改完成（submission_graded）自动推送家长+学员账号；提醒服务 `app/services/reminders.py` 上课前一天+低课时（≤10）惰性幂等生成
  - [x] **教师批改（FR-CL-18）**：`/assignments/{id}/submissions` 列表（学员名/状态/分数/待批改题数）+ 详情（学员答案+自动判题结果+题目）+ `grade` 批改（编程题 0/1 分+评语→graded+通知学员）；AssignmentsView 列表已发布作业「批改」按钮 → SubmissionGradingView（统计卡+逐题打分弹窗）
  - [x] **前端客户端（家长/学员 H5）**：`ClientLayout`（渐变头+学员切换 Tab+通知徽标+底部导航）+ `stores/client.ts`（学员选择本地记忆）；页面——首页（课时卡爆红续费+下一节课提醒+快捷入口+近期课表+最近反馈）/作业列表（状态 Tab 全部·未完成·待批改·已批改+进度条+截止/逾期标记）/**作业作答页**（题号导航色=已答绿/当前渐变/未答白、上一题/下一题、8s 节流自动保存+手动保存、空题跳最小题号、提交客观题即看判题结果）/反馈（折叠详情+课堂照片）/课时订阅（课时包卡+下单）/订单（模拟支付+取消+到账状态）/通知中心（类型徽标+未读点+全部已读+类型跳转）
  - [x] 验证：pytest 63 例全绿（M5 新增 7 例：绑定/家长首页/学员账号/反馈仅已发布/订阅全流程/判题+批改+通知/提醒+已读）；ruff 全库零错误；vue-tsc + build 通过；88 条 OpenAPI 路径注册正常
- [x] **M3 公栏与图表（2026-08-31，用户反馈 2 组，完成）**：
  - [x] **问题修复-教师管理**：`/auth/teachers`、`/auth/campuses`、`/auth/teachers/{id}` 读取对教师开放（只读）；TeachersView 教师角色隐藏/拦截新增·编辑·删除 → 点击弹「无操作权限」提示（后端写操作仍 admin/staff 403 兜底）
  - [x] **报告公栏**：`GET /reports/board`（仅已发布，按校区/教师/类型/日期范围筛选+分页，所有角色可读）+ `GET /reports/board/stats`（按在职教师×周期算 日报/周报 应提交与已提交）；前端 ReportsView 新增「公栏」Tab（筛选栏+统计卡+分页+详情弹窗，教师只可编辑自己的报告）
  - [x] **期间统计增强**：period-stats 新增 当前学员/应耗课时/消耗课时/达标率；缺课学员明细回日报/周报（不再入期间统计）；PPT 数据卡同步为新指标
  - [x] **图表**：`period-stats/monthly`（逐月应耗/消耗/新增/上课人次，折线图）+ `period-stats/comparison`（季度对上一季度、年度对上一年 逐月课时消耗对比，柱状图）；前端 SummaryView 用 echarts（tree-shake 裁剪）渲染
  - [x] **PPT 公栏**：SummaryView 底部展示全体教师已提交发布的季度/年度总结（含 PPT 下载），教师只可编辑自己的总结
  - [x] 验证：pytest 47 例全绿（报告新增 5 例）；ruff 零错误；前端 vue-tsc + build（echarts 裁剪后 SummaryView ~551KB（gzip 189KB））通过
- [x] **M3 反馈与报告（2026-08-31，完成）**：课后反馈、日报/周报、季度/年度总结（PPT）
  - [x] **季度/年度总结（PPT，2026-08-31，完成）**：
    - [x] `reports` 扩展 `quarterly/yearly` 类型 + `ppt_url` 列（迁移 c0ffee000004 已应用）
    - [x] 周期聚合统计 `GET /reports/period-stats/preview`（排课/人次/出勤率/缺课/新增/已发布周报）+ `collect_period_material` 期间周报摘要
    - [x] AI 季度/年度总结：`llm.generate_period_summary`；`/reports/{id}/ai-draft` 分支季度/年度（素材=统计+周报摘要，无周报提示补全）
    - [x] `app/services/pptx_builder.py`（python-pptx）生成 16:9 简报（封面/数据卡/总体/亮点/问题/计划/数据说明/结尾），落盘 `uploads/ppt/<uuid>.pptx`；`POST /reports/{id}/ppt` 生成+写 ppt_url；`/uploads/ppt/{file}` 下载
    - [x] 前端「总结·PPT」（SummaryView.vue，侧边栏新入口）：季度/年度 Tab + 期间导航 + 统计卡 + 编辑表单 + AI 总结 / 生成 PPT / 下载 / 提交 / 撤回
    - [x] 验证：pytest 42 例全绿（新增 2 例）；ruff 零错误；前端 vue-tsc + build 通过；live 生成 PPT 8 页 38KB 可下载
    - [ ] 待续：家长端接收反馈/报告（M5）；M4 AI 习题
  - [x] **报告：日报+周报（2026-08-31，完成）**：
    - [x] `reports` 表（迁移 c0ffee000003）：type(daily/weekly)+period(唯一约束，幂等创建=更新)+content(JSONB)+stats(JSONB)+status(draft/published，可撤回重编辑)
    - [x] 日报（FR-DR）：模板 `{work,courses,problems,plan}`，按日归档检索；周报（FR-WR）：模板 `{summary,highlights,problems,next_plan}`
    - [x] 周报自动统计（FR-WR-02）：`/reports/weekly-stats/preview` = 已完成排课/上课人次/缺课人次/出勤率/缺课学员/新增学员（口径同 M2）
    - [x] AI 草稿（FR-DR-02/FR-WR-03）：`/reports/{id}/ai-draft` 基于当日排课考勤 或 本周统计+已发布日报摘要生成 JSON；`llm.generate_report_summary`；未配 Key 降级
    - [x] 前端 ReportsView.vue：日报/周报双 Tab + 周导航 + 统计卡 + 编辑表单（保存/AI/提交/撤回）+ 历史列表；侧边栏「日报·周报」入口
    - [x] 验证：真实 DeepSeek 生成日报草稿成功；pytest 40 例全绿（报告新增 4 例）；ruff 零错误；前端 vue-tsc + build 通过；live `/api/reports`、`/api/reports/weekly-stats/preview` 正常
    - [x] 待续：季度/年度总结（PPT，FR-QS/FR-YS）；家长端接收（M5）
  - [x] **反馈回顾轮（2026-08-31，修复+口径）**：
    - [x] AI 课堂评价 500 修复：`generate_feedback_evaluation` 增加 `title` 参数（此前 `**current` 传 title 导致契约错位）
    - [x] 已反馈口径收窄为「仅已发送(published)」：`feedback_done/pending/all_done/saved_draft` 全部按 published 计数
    - [x] 新增「重新编辑/撤回」：`POST /feedbacks/{id}/unpublish`；前端已发送卡片显示「重新编辑」按钮，二次确认后撤回改动再重发
    - [x] 操作按钮图标统一 13px 大小（`.op-btn svg`），AI 星星不再撑大按钮
  - [x] **反馈增强2：课堂评价 + 提示词模板（2026-08-30，完成）**：
    - [x] `feedbacks` 新增 `evaluation`（课堂评价，AI 内容写入位置）；`prompt_templates` 表 + 3 套系统默认模板 seed（通用鼓励型/问题引导型/亮点详述型）；迁移 c0ffee000002 已应用
    - [x] 模板三档可见性：system（内置，所有人可用，仅 admin 可改删）/ personal（账号隔离，仅 owner）/ published（admin 发布，全校教师可用，仅 admin 可改删/撤回）；admin 管理视角可见全部 personal
    - [x] 占位符 `{student_name} {class_name} {subject} {topic} {content} {performance} {homework} {evaluation}`，`fill_template` 替换；`values_callable` 修复 Enum 大小写绑定（system 查询此前不匹配）
    - [x] `ai-enhance` 改为按模板生成/润色 evaluation 正文：模板下拉（默认系统模板）、已有 evaluation 时=润色（保留事实优化措辞）、未配 Key 降级、他人 personal 模板 403
    - [x] 前端：课堂评价字段（紫色「AI 生成内容将写入此处」徽标）+ AI 生成弹窗（模板下拉/内容预览/生成或润色）+ 提示词模板管理弹窗（系统/全校/我的分组 + 新建/编辑/删除/发布/撤回，管理员专属）+ 未保存自动保存引导提示
    - [x] 验证：pytest 35 例全绿（新增模板隔离/发布/自定义模板 ai-enhance 3 例）；ruff 零错误；前端 vue-tsc + build 通过；live 接口 `/api/prompt-templates` 正常返回 3 套系统模板
    - [x] 待办：日报/周报/季度/年度总结（下一步）；家长端接收（M5）
  - [x] **AI 草稿接入真实 LLM（2026-08-30，完成）**：
    - [x] 新增 `app/services/llm.py`：LangChain OpenAI 兼容客户端（ChatOpenAI），模型名/BaseURL/Key 由 `.env` 驱动不硬编码；延迟导入 langchain + 未配 Key 优雅降级（返回原内容+note 提示），不影响应用启动
    - [x] 改造 `POST /feedbacks/{id}/ai-enhance`：配 Key 时调 LLM 生成结构化草稿 `{title,topic,content,performance,homework}` 写 `ai_draft`（含 input/model/generated_at）并返回；前端回填输入框人工编辑；调用失败 502
    - [x] 前端：`api/feedback.ts` 封装 `aiEnhanceFeedback`；`FeedbackView` 已到学员卡片加「AI 草稿」按钮（紫色 ✨），生成后回填课题/内容/课堂表现/作业
    - [x] 依赖：已 `uv sync --extra ai`（langchain / langchain-openai / langgraph / python-pptx 等）
    - [x] 验证：真实调用 DeepSeek 生成草稿成功；pytest 33 例全绿；ruff 零错误；前端 vue-tsc + build 通过
    - [x] 待办：日报/周报/季度/年度总结（下一步）；家长端接收（M5）
  - [x] **课表打磨轮（2026-08-30，用户反馈 2 项）**：
    - [x] **课组可收起**：重构课组为「固定头部 + 展开内容」，头部始终可见且可点击切换收起/展开（原展开态子卡片 `.stop` 吞掉点击导致无法收起）；`expandedGroups` 双向切换逻辑保持
    - [x] **课组标题美观**：收起/展开副标题不再罗列班级名（如“1班 等”），改为展示统一时间区间 `groupTitleText()`；主标题统一「同时段 N 节课 · 点击展开/收起」
    - [x] 前端 vue-tsc/vite build 通过、无 lint 错误；dev server 已热更新
    - [x] 待办：AI 草稿接入 LLM（需配 LLM_API_KEY）；家长端接收（M5）；日报/周报/季度/年度总结（下一步）
  - [x] **排课课表完善轮（2026-08-30，用户反馈 2 项 + 在线验证）**：
    - [x] **课表同时段多节=课组收起/展开**：同一时间段重叠多节不再水平拥挤，改为合并为「课组」（`layoutTimeline` 连通分量聚类 + `expandedGroups` 状态）；收起时显示数量徽标（如 4）+「节课 · 点击展开」；点击展开后垂直堆叠显示全部排课，下方刻度随展开向下推移（`cursorY` 下推 + `maxDayBottom` 动态延长刻度至需要的小时），不再压到其他时间刻度
    - [x] **课组取消到剩 1 节自动还原单卡片**：聚类结果为单节即渲染普通卡片，天然恢复
    - [x] **新建排课表单增强**：单次/循环排课均新增「校区筛选」下拉（联动教师/班级）；教师改为 SearchableSelect 搜索选择（显示校区标签）；选定教师后班级下拉只显示该教师带教的班级（`/classes?teacher_id=` 联动，与班级管理分配的带教教师一致）；未选教师时班级按校区教师过滤
    - [x] **在线接口验证**：`/feedbacks/completed-schedules` 已含 8/30 两节（2/1 人到课）、`/feedbacks/stats` 全部口径 pending=3、`/schedules` 8/30 升序（09:00→14:30）、`/auth/teachers?campus=`、`/classes?campus=`、`/classes?teacher_id=` 均正常
    - [x] 后端 32 例全绿 + ruff 零错误；前端 vue-tsc/vite build 通过
    - [x] 待办：AI 草稿接入 LLM（需配 LLM_API_KEY）；家长端接收（M5）；日报/周报/季度/年度总结（下一步）
  - [x] **课后反馈边界与课表刻度修复轮（2026-08-30，用户反馈 4 项）**：
    - [x] **反馈班级不显示（未接通）**：根因=前端日期区间 end 传的是结束日当天 00:00，后端 `start_time<=end` 把结束日当天的已完成排课全部排除（如 8/30 排课在 end=8/30 时被过滤）。修复：`FeedbackView` 新增 `feedbackQuery()`，end 统一取「结束日次日 00:00」闭开区间；`listCompletedSchedules`/`getFeedbackStats`/`completed-schedules`/`stats` 全部走同一逻辑 → 上完课的班级正常进入待反馈
    - [x] **待反馈统计（全部=0，筛选才对）修复**：同一根因（结束日当天被 end 边界排除）；统计卡走同一 `feedbackQuery()` 后，全部校区/教师/班级口径 pending 正常（实测 8/30 完成班 3 人待反馈）
    - [x] **课表排序**：`schedules.list_all` 从 `start_time.desc()` 改为 `asc()`，同一天 9:00 在上、14:30 在下
    - [x] **课表时间刻度标尺**：周课表重写为 8:00-22:00 时间轴布局（`hourMarks` + `layoutTimeline()`），同天同时刻跨日水平对齐；同时段多节采用分栏排版（依次对齐）；`sched-card` 改绝对定位 + 按实际时长定高
    - [x] 新增后端测试 2 例（反馈 end 边界闭区间 / 排课升序），合计 **32 例全绿**；ruff 零错误；前端 build + vue-tsc 通过
    - [x] 待办：AI 草稿接入 LLM（需配 LLM_API_KEY）；家长端接收（M5）；日报/周报/季度/年度总结（下一步）
  - [x] **课后反馈（2026-08-30，首轮闭环）**：
    - [x] `feedbacks` 表（Alembic 迁移 c0ffee000001）：一次排课对一名学员唯一（uq_schedule_student），字段=标题/课题/课程内容/课堂表现/今日作业/media_urls(JSONB)/status(draft|published)/ai_draft
    - [x] API：按排课批量查询 / 创建（幂等更新）/ 编辑 / 发布（草稿→已发布，空内容拦截 400）/ AI 草稿预留（未接 LLM 返回原样）/ 素材上传（本地磁盘，OQ-04 决策=本地，image|video、≤20MB）
    - [x] 素材静态服务：`/uploads` 挂载本地目录；`python-multipart` 依赖
    - [x] 前端「课后反馈」页面：排课下拉（近 90 天~未来 30 天）→ 载入班级学员 → 逐学员填反馈 → 上传预览 → 保存/发送 → 历史弹窗
    - [x] 导航「课后反馈」+ 路由 `/feedbacks`
    - [x] 后端测试 28 例全绿；ruff 零错误；前端 build 通过
  - [x] **课后反馈增强（2026-08-30，用户反馈 5 项）**：
    - [x] **只显示已上完的课**：反馈模块排课仅来自 status=completed（`GET /feedbacks/completed-schedules`，剔除未来/未上/取消）；排课卡片显示 题目数/待反馈数 + 反馈进度条 + 「已全部反馈」徽标
    - [x] **请假学员免反馈 + 颜色标记**：编辑器行接口（`GET /feedbacks/schedule/{id}/editor`）返回每学员考勤状态；请假学员卡片置灰/虚线 + 「已请假·无需反馈」提示 + 顶部请假条汇总；签到学员正常反馈
    - [x] **多条件筛选 + 统计**：筛选栏=校区下拉 + **教师搜索下拉（SearchableSelect）** + **班级搜索下拉（可选）** + 日期区间（默认本周）；统计卡实时展示 待反馈/已反馈/应到/签到/请假/已完成排课（`GET /feedbacks/stats`）
    - [x] **课题内容输入框**：课题下方新增「课题内容」，反馈字段 title/topic/content/performance/homework 完整对齐输入
    - [x] **批量填入课程信息弹窗化**：原 prompt() 改为真弹窗（多字段可部分填），应用后真正写入各签到学员的输入框
    - [x] 新增组件 `SearchableSelect.vue`（搜索+下拉选中+清除）
    - [x] **待反馈口径**：待反馈=签到(attended)但未反馈的学员，**请假学员不计入待反馈**（`feedback.stats.pending`）
    - [x] **筛选联动**：选校区后教师只显示该校区的教师、班级只显示该校区教师的班级；选了教师后班级只显示该教师待反馈的班级（`/classes?campus=` + `/classes?teacher_id=`）
    - [x] 后端测试 30 例全绿（M3 新增共 5 例：编辑器行/统计/completed/班级校区过滤）；ruff 零错误；前端 build 通过
    - [x] **AI 草稿接 LLM（本轮已完成，见上方）**；家长端接收（M5）；日报/周报/季度/年度总结（下一步）
## 待办

- [ ] 微信推送接入（OQ-01 应用内先行，真实推送需企业微信/公众号商户资质）

## 已解决/已确认

- [x] OQ-02 边界口径：课时 **≤ 10** 即爆红并进入催缴名单
- [x] OQ-05 排课冲突**跨教师检测**（任意教师/班级同时间段重叠即冲突）
- [x] 前端设计系统升级：品牌渐变（indigo→cyan）+ 玻璃拟态侧边栏 + 卡片化 + 状态胶囊

## 待确认（PRD §10 其余 OQ）

- [x] OQ-01 微信通知实现方式 → 应用内通知先行（站内信），微信推送接口预留（需企业微信/公众号商户资质）
- [x] OQ-03 编程题判题 → 仅录入用例，判题引擎 M5（M4 决策）；实现方式→客观题自动判（单选/多选/判断/代码填空）+ 编程题教师人工批改（M5 决策安全考量，不沙箱执行）
- [x] OQ-04 视频/文件存储 → 本地磁盘（M3 决策）
- [x] OQ-06 模拟支付到账确认人 → 管理员后台确认（M5 决策）

## 已完成

- [x] M6 评估与家长会（2026-09-04，完成）：学员评估表、家长会 PPT、AI 优化对话
  - [x] 表结构迁移：`evaluations`（学员评估：student_id/teacher_id/period_start-end/title/content/stats/ai_draft/ppt_url/status draft↔published/published_at）
  - [x] 后端模型/CRUD：`app/models/evaluation.py`、`app/crud/evaluation.py`（同学员同周期幂等 upsert；素材收集=近 3 个月已发布反馈 + 出勤/课时/作业得分率）
  - [x] AI 生成/优化：`POST /evaluations/{id}/ai-draft`、`/ai-refine` 异步任务（复用 `ai_tasks`，前端轮询）；LLM 新增 `generate_evaluation` / `refine_evaluation`
  - [x] 家长会 PPT：`POST /evaluations/{id}/ppt` 基于评估内容生成 `uploads/ppt/*.pptx`，发布后通知家长/学员
  - [x] 客户端可见性：`GET /client/students/{id}/evaluations` 仅已发布评估；通知页/路由补入口
  - [x] 前端：`EvaluationsView` 评估工作台、`evaluation.ts` API、AI 任务中心支持 assignment/evaluation 双模块、管理员侧栏入口
  - [x] 验证：后端 `pytest tests/test_m6.py -q` 2 例全绿；`ruff` 零错误；前端 `npm run build` 通过

- [x] M0 基础设施与认证（后端骨架 + JWT/RBAC + 前端登录骨架 + Alembic + 冒烟测试）
- [x] M1 学员与班级（学员 CRUD/分班/课时包/流水/催缴名单，见 `.claude/plan`）
- [x] M2 排课与划课时：
  - [x] schedules/attendances 两表迁移
  - [x] 排课 CRUD + 同教师冲突检测（force 强制创建，前端冲突确认弹窗）
  - [x] 考勤批次接口：已到扣 2 / 请假不扣 / 防重 / 余额不足拒绝 / 全员标记后置 completed
  - [x] 前端：周课表视图 + 考勤划课时详情页
  - [x] 后端测试 13 例全绿（含 M2 新增 3 例）；ruff 零错误
  - [x] 端到端验证：排课→冲突→考勤扣课时→防重→流水 CONSUME 全部通过
- [x] **M2 修复轮（2026-08-30，用户反馈 6 项）**：
  - [x] 班级管理按钮图标重叠修复（操作按钮改底部行，不再与状态胶囊重叠）
  - [x] 新增教师管理模块（列表 + 新增账号），班级表单支持分配教师
  - [x] 排课卡片快捷取消 + 考勤详情页「取消排课」按钮
  - [x] 周视图导航修复（相对当前周前后翻页，不再限 2 周）
  - [x] **时区修复**：排课时间改传本地 naive 时间（utils/date.ts），日期/星期不再错位
  - [x] **冲突语义修正**：仅【同一教师】时间重叠算冲突（不同教师同段可排）
  - [x] **独立考勤修复**：学员逐个标记，全员完成后排课才 completed（原 bug 标记一人即全员锁定）
  - [x] **循环排课**：每周 N 节多时间段 × 连续周至排满 total_lessons（含批次内冲突检测）
  - [x] 新增 3 测试（双学员独立考勤/循环排课/教师列表），pytest 16 例全绿
  - [x] uv 配置 default-groups=dev，防止 pytest/ruff 被裁剪
- [x] **M2 补强轮（2026-08-29，功能点完善 4 项）**：
  - [x] **教师管理**：新增/删除（软停用）/编辑/查看详情 + 校区标签（一校/二校/三校可自定义，datalist 联想）+ 关键字/校区筛选搜索栏；删除后默认列表隐藏、include_inactive 可查
  - [x] **排课与考勤**：未到上课时间的排课禁止签到/请假（前端点击提示「未到上课时间」+ 顶部横幅，后端 400 拦截兜底），到点后方可标记
  - [x] **班级管理**：筛选搜索栏（按班级名称/科目/带教教师姓名，后端 keyword 过滤）
  - [x] **催缴名单**：课时 ≤ 10 自动进入（待跟进），点击「已续费」补录 40 课时并标记跟进状态=已续费，学员保留在名单中**直接显示「已续费」**；支持按状态筛选（全部/待跟进/已续费/已停课）
  - [x] 表结构迁移：`users.campus`、`students.follow_up_status/follow_up_at/follow_up_note`（Alembic 迁移 7f9a2c41b8d3 已应用）
  - [x] 修复遗留 bug：`FollowUpStatus.of` 不存在导致的催缴名单查询崩溃；补充 `set_follow_up` crud
  - [x] 后端测试 20 例全绿（新增 4 例：未到上课时间拦截/教师校区管理/班级搜索/跟进状态流转）；ruff 零错误；前端 build 通过
- [x] **M2 补强2（2026-08-30，用户反馈 6 项）**：
  - [x] **统一分页**：学员/班级/教师/课时包列表改返回 `{items,total,limit,offset}`（`PageOut[T]`）；前端新增通用 `PaginationBar.vue` 并接入五处列表
  - [x] **学员管理**：编辑弹窗班级**可搜索多选**；学员**停课（需填备注）/恢复在读**（`PATCH /students/{id}/status`，停课同步跟进为已停课、恢复后回到待跟进）
  - [x] **催缴名单**：「已续费」支持**选择课时包或自定义课时+金额**入账（`POST /students/{id}/renew`，记订单+流水+标记已续费）；**已停课学员「恢复为待跟进」**入口
  - [x] **排课按校区筛选**：`GET /schedules` 新增 `campus` 参数（按教师所属校区过滤）；排课页增加**校区下拉 + 教师下拉**联动筛选课表
  - [x] **布局修复**：左侧边栏高度固定（100vh）+ 独立滚动，不再被右侧内容拉伸；**可收起/展开**（仅图标模式 + tooltip）
  - [x] 表结构迁移：`students.stop_note`（Alembic 迁移 a1b2c3d4e5f6 已应用）
  - [x] 后端测试 24 例全绿（新增 4 例：学员停课恢复/课包自定义续费/排课校区过滤/分页）；ruff 零错误；前端 build 通过
  - [x] 修复 vue-tsc 解析坑：`.vue` 文件 `<script>` 末尾若 `})</script>` 同行（无换行）会导致 vue-tsc 虚拟文件产出 `})debugger` 报 TS1005，须 `})` 后换行

## 环境说明（用户机器）

- Windows PowerShell，无 make，无 `&&` 语法 —— 用 uv run / npm 等价命令逐条执行
- PostgreSQL：postgres:123456@localhost:5432/child_code（M2 表已迁移）
- 测试库：child_code_test（pytest 自动创建/销毁）
- 冒烟基线：认证闭环（register/login/me/refresh/RBAC 401/403）
- 服务状态：后端 8000（uvicorn --reload，改代码自动重载）、前端 5173 运行中