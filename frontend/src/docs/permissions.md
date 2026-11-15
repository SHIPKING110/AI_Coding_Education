# 权限体系

## 角色模型

| 角色 | 代码 | 入口 | 说明 |
| --- | --- | --- | --- |
| 管理员 | `admin` | 管理端 | 系统所有者/负责人，权限全开 |
| 教务 | `staff` | 管理端 | 权限全开，负责学员、排课、班级等运营 |
| 教师 | `teacher` | 管理端 | 按权限键逐项开关，默认值见 `KEY_DEFAULTS` |
| 家长 | `parent` | 客户端 H5 | 查看课时、反馈、作业，发起订阅 |
| 学员 | `student` | 客户端 H5 | 查看与作答作业 |

> 后端 `effective()` 的语义：非 `teacher` 角色（管理员/教务）返回全开；教师读取 `TeacherPermission`，无记录时使用默认值。

## 权限键模型

权限以「键 + 布尔值」授予教师，键的中文说明集中在 `PERMISSION_KEYS`，默认值集中在 `KEY_DEFAULTS`。按域分组：

| 分组 | 代表键 | 作用 |
| --- | --- | --- |
| 学员管理 | `student_create`、`student_edit`、`student_adjust`、`student_refund`、`student_stop`、`student_delete`、`student_records`、`class_unenroll` | 学员与调班操作 |
| 班级管理 | `class_view`、`class_create`、`class_edit`、`class_delete` | 班级增改查删 |
| 教师管理 | `teacher_add`、`teacher_view`、`teacher_edit`、`teacher_delete` | 教师档案 |
| 排课考勤 | `schedule_create`、`schedule_cancel` | 排课与取消 |
| 课时包 | `package_create`、`package_edit`、`package_off` | 课时包维护 |
| 招生邀约 | `invitation_create` | 新建邀约 |
| AI 习题 | `assignment_ai`、`assignment_create` | 出题与发布作业 |
| Agent | `agent_skill_import`、`agent_doc_upload` | 技能包导入、知识文档上传 |
| 设置 | `settings_manage`、`settings_tab_personalize`、`settings_tab_model`、`settings_tab_business` | 设置页与 Tab |
| 财务 | `finance_view`、`finance_revenue`、`finance_records`、`finance_salary`、`finance_salary_all` | 财务查看与薪资范围 |
| 教学服务 | `service_reply` | 回复家长会话 |
| 后台管理（RAG） | `rag_overview_view`、`rag_assets_view`、`rag_assets_reindex`、`rag_assets_delete`、`rag_assets_sweep`、`rag_routes_view/save/test`、`rag_eval_view`、`rag_eval_set_create`、`rag_eval_case_add`、`rag_traces_view`、`rag_runs_view`、`rag_sessions_view`、`rag_parent_sessions_view`、`rag_settings_view/save` | RAG 各子页与操作 |
| 用量与成本 | `usage_view`、`usage_price_create`、`usage_budget_save`、`usage_recon_upsert` | 看板、价格、预算、对账 |
| 导航可见 | `nav_students`、`nav_classes`、`nav_teachers`、`nav_schedules`、`nav_packages`、`nav_feedbacks`、`nav_reports`、`nav_evaluations`、`nav_agents`、`nav_assignments`、`nav_invitations`、`nav_finance`、`nav_service`、`nav_settings` | 侧边栏模块显隐 |

> 完整键集合与中文名以 `PERMISSION_KEYS` 为准；新增模块时同时更新键、默认值、分组与前端卡片。

## 默认值与最小权限

- 默认值等于「升级前的既有行为」，避免升级后权限被放大
- 敏感能力默认关闭：`student_delete`、`teacher_add/edit/delete`、`package_*`、`settings_*`、全部 `rag_*`、全部 `usage_*`、`nav_settings`
- 高影响能力开启前应评估影响面，并在变更后抽检

## 职务预设

管理员可在权限管理中维护「职务」，每个职务保存一组权限键；新建或调整教师职务时一键套用。

- **套用即覆盖**：换职务会用职务预设覆盖该教师的个人开关（职务绑定语义）
- **同步**：修改职务后可一键同步到该职务下所有教师
- 职务同时可带薪资基数（供薪资核算），与权限是同一实体的两个维度

## 鉴权链路

```text
请求 → 解析 JWT(get_current_user) → 角色判定 → 权限键校验(require_teacher_permission)
     → 业务处理；管理员/教务放行、教师按开关、家长/学员拒绝
```

硬性规则（即使权限全开也不突破）：

- 教师只能增删改「本人所带」的班级
- 只有空班级（无在册学员）才能删除

后端逐接口鉴权示例：

| 接口域 | 权限键 |
| --- | --- |
| 权限管理 `/api/permissions/*` | 仅 `admin` |
| 学员/班级/教师 | 对应 `student_*` / `class_*` / `teacher_*` |
| 排课 | `schedule_create` / `schedule_cancel` |
| 财务 | `finance_view` 等 |
| 教学服务 | `service_reply` |
| RAG 后台 | `rag_*` 对应键 |
| 用量与成本 | `usage_*` 对应键 |

> 前端守卫只负责跳转与隐藏，敏感操作必须由后端再次校验，二者不可互相替代。

## 前端集成

- `auth.fetchPerms()` 拉取当前教师权限，路由 `meta.perm` 与侧边栏 `navKey/perm/permAny` 共同决定可见性
- 模块排序：个性化设置保存 `nav_order`，侧边栏据此渲染，未收录模块保持原相对顺序沉底
- 权限卡片按「导航可见 / 业务 / 后台管理 / 用量」分组，顺序与侧边栏模块对齐，便于对照配置
- 高影响操作（删除、发布、清空、重索引、预算变更等）统一二次确认弹窗，说明影响范围

## 实施建议

1. 先定义职务预设，再用预设批量授权，最后按需微调个别键
2. 敏感模块先关闭（财务、设置、后台管理、用量），再按岗位逐个开启
3. 每季度复核权限，离职或转岗及时回收
4. 变更权限键后，检查前端导航、权限卡片分组与后端接口三处一致性
