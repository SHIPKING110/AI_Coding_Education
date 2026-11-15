# API 概览（自动生成）

> 由 `scripts/gen_api_overview.py` 从 OpenAPI schema 生成，勿手改。
> 重新生成：`cd backend && uv run python ../scripts/gen_api_overview.py`

共 **403** 个端点，按 `/api/<前缀>` 分组；权限细节见各路由源码依赖声明。

## /api/admin

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| DELETE | `/api/admin/agent-eval/cases/{case_id}` | Delete Case |
| PUT | `/api/admin/agent-eval/cases/{case_id}` | Update Case |
| POST | `/api/admin/agent-eval/results/{result_id}/human-score` | Set Human Score |
| GET | `/api/admin/agent-eval/runs` | List Runs |
| GET | `/api/admin/agent-eval/runs/{run_id}` | Run Detail |
| GET | `/api/admin/agent-eval/runs/{run_id}/compare` | Compare Runs |
| GET | `/api/admin/agent-eval/runs/{run_id}/results` | Run Results |
| POST | `/api/admin/agent-eval/seed-default` | Seed Default |
| GET | `/api/admin/agent-eval/sets` | List Sets |
| POST | `/api/admin/agent-eval/sets` | Create Set |
| DELETE | `/api/admin/agent-eval/sets/{set_id}` | Delete Set |
| GET | `/api/admin/agent-eval/sets/{set_id}/cases` | List Cases |
| POST | `/api/admin/agent-eval/sets/{set_id}/cases` | Add Case |
| POST | `/api/admin/agent-eval/sets/{set_id}/cases/bulk` | Add Cases Bulk |
| POST | `/api/admin/agent-eval/sets/{set_id}/runs` | Create Run |
| GET | `/api/admin/agent-ops/runs` | List Runs |
| GET | `/api/admin/agent-ops/runs/{run_id}` | Get Run |
| GET | `/api/admin/agent-ops/sessions` | List Sessions |
| GET | `/api/admin/agent-ops/sessions/{conversation_id}` | Get Session |
| GET | `/api/admin/agent-ops/stats` | Get Stats |
| GET | `/api/admin/rag/audit` | Audit Log |
| GET | `/api/admin/rag/collections` | Collections |
| POST | `/api/admin/rag/collections/sweep` | Sweep Collections |
| GET | `/api/admin/rag/config` | Get Config |
| PUT | `/api/admin/rag/config` | Update Config |
| POST | `/api/admin/rag/config/rollback/{version}` | Rollback Config |
| GET | `/api/admin/rag/config/versions` | Config Versions |
| GET | `/api/admin/rag/documents` | List Documents |
| DELETE | `/api/admin/rag/documents/{doc_id}` | Delete Document |
| GET | `/api/admin/rag/documents/{doc_id}` | Document Detail |
| GET | `/api/admin/rag/documents/{doc_id}/chunks` | Document Chunks |
| POST | `/api/admin/rag/documents/{doc_id}/parent-visible` | Toggle Parent Visible |
| POST | `/api/admin/rag/documents/{doc_id}/reindex` | Reindex Document |
| POST | `/api/admin/rag/documents/{doc_id}/toggle` | Toggle Document |
| DELETE | `/api/admin/rag/eval/cases/{case_id}` | Delete Eval Case |
| PUT | `/api/admin/rag/eval/cases/{case_id}` | Update Eval Case |
| GET | `/api/admin/rag/eval/models` | List Eval Models |
| POST | `/api/admin/rag/eval/results/{result_id}/human-score` | Set Eval Result Human Score |
| GET | `/api/admin/rag/eval/runs` | List Eval Runs |
| GET | `/api/admin/rag/eval/runs/{run_id}` | Eval Run Detail |
| GET | `/api/admin/rag/eval/sets` | List Eval Sets |
| POST | `/api/admin/rag/eval/sets` | Create Eval Set |
| DELETE | `/api/admin/rag/eval/sets/{set_id}` | Delete Eval Set |
| GET | `/api/admin/rag/eval/sets/{set_id}/cases` | List Eval Cases |
| POST | `/api/admin/rag/eval/sets/{set_id}/cases` | Add Eval Case |
| POST | `/api/admin/rag/eval/sets/{set_id}/cases/bulk` | Add Eval Cases |
| POST | `/api/admin/rag/eval/sets/{set_id}/cases/from-trace` | Add Eval Case From Trace |
| POST | `/api/admin/rag/eval/sets/{set_id}/generate` | Generate Eval Cases |
| POST | `/api/admin/rag/eval/sets/{set_id}/runs` | Create Eval Run |
| GET | `/api/admin/rag/knowledge-bases` | Knowledge Bases |
| POST | `/api/admin/rag/maintenance/cleanup-traces` | Cleanup Traces |
| POST | `/api/admin/rag/maintenance/sync` | Trigger Sync |
| GET | `/api/admin/rag/overview` | Overview |
| GET | `/api/admin/rag/parent-sessions` | List Parent Sessions |
| GET | `/api/admin/rag/parent-sessions/{thread_id}` | Parent Session Detail |
| GET | `/api/admin/rag/routes` | Routes |
| POST | `/api/admin/rag/routes/test` | Route Test |
| PUT | `/api/admin/rag/routes/{route_key}` | Update Route Override |
| GET | `/api/admin/rag/traces` | List Traces |
| GET | `/api/admin/rag/traces/{trace_id}` | Trace Detail |
| POST | `/api/admin/rag/traces/{trace_id}/feedback` | Trace Feedback |
| GET | `/api/admin/usage/events` | List Events |
| POST | `/api/admin/usage/events/purge-unpriced` | Purge Unpriced Events |
| GET | `/api/admin/usage/export` | Export Events |
| GET | `/api/admin/usage/monthly` | List Monthly |
| GET | `/api/admin/usage/prices` | List Prices |
| POST | `/api/admin/usage/prices` | Create Price |
| DELETE | `/api/admin/usage/prices/{price_id}` | Delete Price |
| PUT | `/api/admin/usage/prices/{price_id}` | Update Price |
| GET | `/api/admin/usage/reconciliations` | List Reconciliations |
| POST | `/api/admin/usage/reconciliations` | Upsert Reconciliation |
| DELETE | `/api/admin/usage/reconciliations/{recon_id}` | Delete Reconciliation |
| POST | `/api/admin/usage/reprice-unpriced` | Reprice Unpriced |
| GET | `/api/admin/usage/settings` | Get Usage Settings |
| PUT | `/api/admin/usage/settings` | Update Usage Settings |
| GET | `/api/admin/usage/stats` | Get Stats |

## /api/agents

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/agents` | List Agents |
| GET | `/api/agents/conversations` | List Conversations |
| POST | `/api/agents/conversations` | Create Conversation |
| DELETE | `/api/agents/conversations/{conv_id}` | Remove Conversation |
| PATCH | `/api/agents/conversations/{conv_id}` | Patch Conversation |
| POST | `/api/agents/conversations/{conv_id}/attachments` | Upload Conversation Attachment |
| POST | `/api/agents/conversations/{conv_id}/build-ppt` | Conversation Build Ppt |
| POST | `/api/agents/conversations/{conv_id}/chat` | Conversation Chat |
| GET | `/api/agents/conversations/{conv_id}/material` | Conversation Material |
| GET | `/api/agents/conversations/{conv_id}/messages` | Conversation Messages |
| POST | `/api/agents/conversations/{conv_id}/share` | Share Conversation |
| GET | `/api/agents/ext/agents` | List Custom Agents |
| POST | `/api/agents/ext/agents` | Create Custom Agent |
| DELETE | `/api/agents/ext/agents/{agent_id}` | Delete Custom Agent |
| GET | `/api/agents/ext/agents/{agent_id}` | Get Custom Agent |
| PATCH | `/api/agents/ext/agents/{agent_id}` | Patch Custom Agent |
| GET | `/api/agents/ext/global` | Get Global |
| PUT | `/api/agents/ext/global` | Put Global |
| GET | `/api/agents/ext/mcps` | List Mcps |
| POST | `/api/agents/ext/mcps` | Create Mcp |
| GET | `/api/agents/ext/mcps/plaza` | List Plaza Mcps |
| DELETE | `/api/agents/ext/mcps/plaza/{mcp_id}/collect` | Uncollect Plaza Mcp |
| POST | `/api/agents/ext/mcps/plaza/{mcp_id}/collect` | Collect Plaza Mcp |
| DELETE | `/api/agents/ext/mcps/{mcp_id}` | Delete Mcp |
| PATCH | `/api/agents/ext/mcps/{mcp_id}` | Patch Mcp |
| POST | `/api/agents/ext/mcps/{mcp_id}/publish` | Publish Mcp |
| POST | `/api/agents/ext/mcps/{mcp_id}/test` | Test Mcp |
| POST | `/api/agents/ext/mcps/{mcp_id}/unpublish` | Unpublish Mcp |
| GET | `/api/agents/ext/sandbox` | Get Sandbox |
| PUT | `/api/agents/ext/sandbox` | Put Sandbox |
| POST | `/api/agents/ext/sandbox/test` | Test Sandbox |
| GET | `/api/agents/ext/skills` | List Skills |
| POST | `/api/agents/ext/skills` | Create Skill |
| POST | `/api/agents/ext/skills/import` | Import Skill Bundle |
| GET | `/api/agents/ext/skills/plaza` | List Plaza Skills |
| DELETE | `/api/agents/ext/skills/plaza/{skill_id}/collect` | Uncollect Plaza Skill |
| POST | `/api/agents/ext/skills/plaza/{skill_id}/collect` | Collect Plaza Skill |
| DELETE | `/api/agents/ext/skills/{skill_id}` | Delete Skill |
| PATCH | `/api/agents/ext/skills/{skill_id}` | Patch Skill |
| GET | `/api/agents/ext/skills/{skill_id}/files` | List Skill Files |
| GET | `/api/agents/ext/skills/{skill_id}/files/preview` | Preview Skill File |
| POST | `/api/agents/ext/skills/{skill_id}/publish` | Publish Skill |
| POST | `/api/agents/ext/skills/{skill_id}/run` | Run Skill Script |
| POST | `/api/agents/ext/skills/{skill_id}/unpublish` | Unpublish Skill |
| POST | `/api/agents/ext/skills/{skill_id}/upload` | Upload Skill Bundle |
| GET | `/api/agents/memories` | List Memories |
| DELETE | `/api/agents/memories/{memory_id}` | Remove Memory |
| GET | `/api/agents/share/{token}` | Read Shared Conversation |

## /api/assignments

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/assignments` | List Assignments |
| POST | `/api/assignments` | Create Assignment |
| POST | `/api/assignments/ai-generate` | Ai Generate |
| POST | `/api/assignments/ai-refine` | Ai Refine |
| GET | `/api/assignments/ai-tasks` | List Ai Tasks |
| GET | `/api/assignments/ai-tasks/{task_id}` | Get Ai Task |
| POST | `/api/assignments/ai-tasks/{task_id}/cancel` | Cancel Ai Task |
| GET | `/api/assignments/folders` | List Assignment Folders |
| POST | `/api/assignments/folders` | Create Assignment Folder |
| POST | `/api/assignments/folders/ungrouped/assignments` | Remove Assignments From Assignment Folder |
| DELETE | `/api/assignments/folders/{folder_id}` | Delete Assignment Folder |
| PATCH | `/api/assignments/folders/{folder_id}` | Update Assignment Folder |
| POST | `/api/assignments/folders/{folder_id}/assignments` | Move Assignments To Assignment Folder |
| GET | `/api/assignments/grading-center` | Grading Center |
| GET | `/api/assignments/questions/pool` | List Questions Pool |
| DELETE | `/api/assignments/{assignment_id}` | Delete Assignment |
| GET | `/api/assignments/{assignment_id}` | Get Assignment |
| PATCH | `/api/assignments/{assignment_id}` | Update Assignment |
| POST | `/api/assignments/{assignment_id}/makeup` | Create Makeup Draft |
| POST | `/api/assignments/{assignment_id}/publish` | Publish Assignment |
| POST | `/api/assignments/{assignment_id}/questions` | Add Questions |
| PUT | `/api/assignments/{assignment_id}/questions/reorder` | Reorder Questions |
| DELETE | `/api/assignments/{assignment_id}/questions/{question_id}` | Delete Question |
| PATCH | `/api/assignments/{assignment_id}/questions/{question_id}` | Update Question |
| GET | `/api/assignments/{assignment_id}/submission-stats` | Submission Stats |
| GET | `/api/assignments/{assignment_id}/submissions` | List Submissions |
| GET | `/api/assignments/{assignment_id}/submissions/{submission_id}` | Get Submission |
| POST | `/api/assignments/{assignment_id}/submissions/{submission_id}/grade` | Grade Submission |
| POST | `/api/assignments/{assignment_id}/unpublish` | Unpublish Assignment |

## /api/audit

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/audit/logs` | List Audit Logs |

## /api/auth

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/auth/admin/example` | Admin Example |
| GET | `/api/auth/campuses` | List Campuses |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Read Me |
| PATCH | `/api/auth/me` | Update My Profile |
| POST | `/api/auth/me/password` | Change My Password |
| POST | `/api/auth/refresh` | Refresh |
| POST | `/api/auth/register` | Register |
| GET | `/api/auth/teachers` | List Teachers |
| POST | `/api/auth/teachers` | Create Teacher |
| DELETE | `/api/auth/teachers/{teacher_id}` | Delete Teacher |
| GET | `/api/auth/teachers/{teacher_id}` | Get Teacher |
| PATCH | `/api/auth/teachers/{teacher_id}` | Update Teacher |
| GET | `/api/auth/users` | List Users |
| PATCH | `/api/auth/users/{user_id}/password` | Reset User Password |

## /api/business

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/business/campuses` | List Campuses |
| POST | `/api/business/campuses` | Create Campus |
| POST | `/api/business/campuses/reorder` | Reorder Campuses |
| PATCH | `/api/business/campuses/{campus_id}` | Update Campus |
| GET | `/api/business/commission-rules` | List Commission Rules |
| PUT | `/api/business/commission-rules` | Update Commission Rules |
| GET | `/api/business/finance-setting` | Get Finance Setting |
| PUT | `/api/business/finance-setting` | Update Finance Setting |
| GET | `/api/business/payroll` | List Payroll |
| POST | `/api/business/payroll/auto-compute` | Auto Compute Payroll |
| POST | `/api/business/payroll/compute` | Compute Payroll Entry |
| GET | `/api/business/posts` | List Posts |
| POST | `/api/business/posts` | Create Post |
| PATCH | `/api/business/posts/{post_id}` | Update Post |
| GET | `/api/business/subjects` | List Subjects |
| POST | `/api/business/subjects` | Create Subject |
| PATCH | `/api/business/subjects/{subject_id}` | Update Subject |
| GET | `/api/business/teacher-levels` | List Teacher Levels |
| POST | `/api/business/teacher-levels` | Create Teacher Level |
| DELETE | `/api/business/teacher-levels/{level_id}` | Delete Teacher Level |
| PATCH | `/api/business/teacher-levels/{level_id}` | Update Teacher Level |
| GET | `/api/business/workbench` | Workbench Overview |

## /api/classes

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/classes` | List Classes |
| POST | `/api/classes` | Create Class |
| DELETE | `/api/classes/{class_id}` | Archive Class |
| GET | `/api/classes/{class_id}` | Get Class |
| PATCH | `/api/classes/{class_id}` | Update Class |

## /api/client

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/client/assignments` | Client Assignments |
| GET | `/api/client/assignments/{assignment_id}` | Client Assignment Detail |
| POST | `/api/client/assignments/{assignment_id}/answers` | Client Save Answers |
| POST | `/api/client/assignments/{assignment_id}/submit` | Client Submit |
| GET | `/api/client/me` | Client Me |
| GET | `/api/client/orders` | Client List Orders |
| POST | `/api/client/orders` | Client Create Order |
| POST | `/api/client/orders/{order_id}/cancel` | Client Cancel Order |
| POST | `/api/client/orders/{order_id}/pay` | Client Pay Order |
| POST | `/api/client/orders/{order_id}/refund` | Client Self Refund |
| GET | `/api/client/orders/{order_id}/refund-check` | Client Refund Check |
| GET | `/api/client/packages` | Client Packages |
| GET | `/api/client/students/{student_id}` | Client Student Detail |
| GET | `/api/client/students/{student_id}/evaluations` | Client Evaluations |
| GET | `/api/client/students/{student_id}/feedbacks` | Client Feedbacks |
| GET | `/api/client/students/{student_id}/lesson-records` | Client Lesson Records |
| GET | `/api/client/students/{student_id}/schedules` | Client Schedules |

## /api/evaluations

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/evaluations` | List Evaluations |
| POST | `/api/evaluations` | Create Evaluation |
| GET | `/api/evaluations/ai-tasks` | List Evaluation Ai Tasks |
| GET | `/api/evaluations/ai-tasks/{task_id}` | Get Evaluation Ai Task |
| POST | `/api/evaluations/ai-tasks/{task_id}/cancel` | Cancel Evaluation Ai Task |
| POST | `/api/evaluations/class-ppt` | Create Class Ppt |
| POST | `/api/evaluations/class-ppt/agent/build` | Agent Build |
| POST | `/api/evaluations/class-ppt/agent/init` | Agent Init |
| POST | `/api/evaluations/class-ppt/agent/outline` | Agent Outline |
| POST | `/api/evaluations/class-ppt/agent/refine` | Agent Refine |
| POST | `/api/evaluations/class-ppt/agent/titles` | Agent Titles |
| GET | `/api/evaluations/class-ppt/fingerprint` | Class Ppt Fingerprint |
| GET | `/api/evaluations/class-ppt/latest` | Latest Class Ppt |
| PATCH | `/api/evaluations/class-ppt/{record_id}` | Update Class Ppt |
| GET | `/api/evaluations/class-roster` | Class Evaluation Roster |
| GET | `/api/evaluations/material/preview` | Material Preview |
| DELETE | `/api/evaluations/{evaluation_id}` | Delete Evaluation |
| GET | `/api/evaluations/{evaluation_id}` | Get Evaluation |
| PATCH | `/api/evaluations/{evaluation_id}` | Update Evaluation |
| POST | `/api/evaluations/{evaluation_id}/ai-draft` | Ai Draft Evaluation |
| POST | `/api/evaluations/{evaluation_id}/ai-refine` | Ai Refine Evaluation |
| POST | `/api/evaluations/{evaluation_id}/ppt` | Generate Evaluation Ppt |
| POST | `/api/evaluations/{evaluation_id}/publish` | Publish Evaluation |
| POST | `/api/evaluations/{evaluation_id}/unpublish` | Unpublish Evaluation |

## /api/feedbacks

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/feedbacks` | List Feedbacks |
| POST | `/api/feedbacks` | Create Feedback |
| GET | `/api/feedbacks/completed-schedules` | Completed Feedback Schedules |
| GET | `/api/feedbacks/schedule/{schedule_id}` | List Feedback By Schedule |
| GET | `/api/feedbacks/schedule/{schedule_id}/editor` | Feedback Editor Rows |
| GET | `/api/feedbacks/stats` | Feedback Stats |
| POST | `/api/feedbacks/upload` | Upload Media |
| PATCH | `/api/feedbacks/{feedback_id}` | Update Feedback |
| POST | `/api/feedbacks/{feedback_id}/ai-enhance` | Ai Enhance Feedback |
| POST | `/api/feedbacks/{feedback_id}/publish` | Publish Feedback |
| POST | `/api/feedbacks/{feedback_id}/unpublish` | Unpublish Feedback |

## /api/finance

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/finance/by-subject` | Finance By Subject |
| GET | `/api/finance/by-teacher` | Finance By Teacher |
| GET | `/api/finance/lesson-stats` | Finance Lesson Stats |
| GET | `/api/finance/order-stats` | Finance Order Stats |
| GET | `/api/finance/overview` | Finance Overview |
| GET | `/api/finance/records` | Finance Records |

## /api/health

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | Health |

## /api/knowledge

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/knowledge/documents` | My Documents |
| POST | `/api/knowledge/documents` | Upload Document |
| POST | `/api/knowledge/documents/bulk` | Upload Documents Bulk |
| POST | `/api/knowledge/documents/describe` | Describe Document |
| DELETE | `/api/knowledge/documents/{doc_id}` | Remove Document |
| POST | `/api/knowledge/documents/{doc_id}/publish` | Publish To Plaza |
| POST | `/api/knowledge/documents/{doc_id}/retry` | Retry Index |
| POST | `/api/knowledge/documents/{doc_id}/toggle-parent` | Toggle Parent Visible |
| POST | `/api/knowledge/documents/{doc_id}/toggle-search` | Toggle Searchable |
| POST | `/api/knowledge/documents/{doc_id}/unpublish` | Unpublish From Plaza |
| GET | `/api/knowledge/maintenance/collections` | Knowledge Collections |
| GET | `/api/knowledge/maintenance/metrics` | Knowledge Metrics |
| POST | `/api/knowledge/maintenance/sweep-orphans` | Sweep Orphans |
| POST | `/api/knowledge/maintenance/sync` | Trigger Sync |
| GET | `/api/knowledge/plaza` | Plaza |
| DELETE | `/api/knowledge/plaza/{doc_id}/collect` | Uncollect |
| POST | `/api/knowledge/plaza/{doc_id}/collect` | Collect |

## /api/lesson-packages

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/lesson-packages` | List Packages |
| POST | `/api/lesson-packages` | Create Package |
| DELETE | `/api/lesson-packages/{package_id}` | Deactivate Package |
| PATCH | `/api/lesson-packages/{package_id}` | Update Package |

## /api/llm-configs

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/llm-configs` | List My Configs |
| POST | `/api/llm-configs` | Create Config |
| GET | `/api/llm-configs/modules/mapping` | Get Module Mapping |
| PUT | `/api/llm-configs/modules/mapping` | Set Module Mapping |
| DELETE | `/api/llm-configs/{config_id}` | Delete Config |
| PATCH | `/api/llm-configs/{config_id}` | Update Config |
| POST | `/api/llm-configs/{config_id}/test` | Test Config |

## /api/media

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/media/sign` | Sign Media |

## /api/notifications

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/notifications` | List Notifications |
| POST | `/api/notifications/read-all` | Mark All Read |
| GET | `/api/notifications/unread-count` | Get Unread Count |
| POST | `/api/notifications/{notification_id}/read` | Mark Notification Read |

## /api/orders

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/orders` | List Orders |
| GET | `/api/orders/{order_id}` | Get Order |
| POST | `/api/orders/{order_id}/cancel` | Cancel Order |
| POST | `/api/orders/{order_id}/confirm` | Confirm Order |

## /api/parent-service

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/parent-service/auth/wechat` | Wechat Login |
| POST | `/api/parent-service/chat` | Parent Chat |
| POST | `/api/parent-service/threads/{thread_id}/escalate` | Parent Escalate |
| GET | `/api/parent-service/threads/{thread_id}/messages` | Parent Messages |

## /api/permissions

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/permissions/job-titles` | List Job Titles |
| POST | `/api/permissions/job-titles` | Create Job Title |
| DELETE | `/api/permissions/job-titles/{title_id}` | Delete Job Title |
| PUT | `/api/permissions/job-titles/{title_id}` | Update Job Title |
| POST | `/api/permissions/job-titles/{title_id}/sync` | Sync Title To Teachers |
| GET | `/api/permissions/keys` | Permission Keys |
| GET | `/api/permissions/mine` | My Permissions |
| GET | `/api/permissions/teachers` | List Teacher Permissions |
| PUT | `/api/permissions/teachers/{teacher_id}` | Update Teacher Permissions |
| POST | `/api/permissions/teachers/{teacher_id}/apply-title` | Apply Title To Teacher |

## /api/prompt-templates

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/prompt-templates` | List Prompt Templates |
| POST | `/api/prompt-templates` | Create Prompt Template |
| DELETE | `/api/prompt-templates/{template_id}` | Delete Prompt Template |
| PATCH | `/api/prompt-templates/{template_id}` | Update Prompt Template |
| POST | `/api/prompt-templates/{template_id}/publish` | Publish Prompt Template |
| POST | `/api/prompt-templates/{template_id}/unpublish` | Unpublish Prompt Template |

## /api/reports

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/reports` | List Reports |
| POST | `/api/reports` | Create Report |
| GET | `/api/reports/board` | Board List |
| GET | `/api/reports/board/stats` | Board Stats |
| GET | `/api/reports/daily-stats/preview` | Daily Stats Preview |
| GET | `/api/reports/monthly-stats/preview` | Monthly Stats Preview |
| GET | `/api/reports/period-stats/comparison` | Period Stats Comparison |
| GET | `/api/reports/period-stats/monthly` | Period Stats Monthly |
| GET | `/api/reports/period-stats/preview` | Period Stats Preview |
| GET | `/api/reports/weekly-stats/preview` | Weekly Stats Preview |
| DELETE | `/api/reports/{report_id}` | Delete Report |
| GET | `/api/reports/{report_id}` | Get Report |
| PATCH | `/api/reports/{report_id}` | Update Report |
| POST | `/api/reports/{report_id}/ai-draft` | Report Ai Draft |
| POST | `/api/reports/{report_id}/ai-draft-jobs` | Create Ai Draft Job |
| GET | `/api/reports/{report_id}/ai-draft-jobs/{job_id}` | Get Ai Draft Job |
| POST | `/api/reports/{report_id}/ppt` | Generate Report Ppt |
| POST | `/api/reports/{report_id}/ppt-build` | Ppt Build |
| POST | `/api/reports/{report_id}/ppt-chat` | Ppt Chat Stream |
| POST | `/api/reports/{report_id}/publish` | Publish Report |
| POST | `/api/reports/{report_id}/unpublish` | Unpublish Report |

## /api/retrieval-configs

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| DELETE | `/api/retrieval-configs/embedding` | Remove Embedding Config |
| GET | `/api/retrieval-configs/embedding` | Get Embedding Config |
| PUT | `/api/retrieval-configs/embedding` | Set Embedding Config |
| POST | `/api/retrieval-configs/embedding/test` | Test Embedding Config |
| DELETE | `/api/retrieval-configs/rerank` | Remove Rerank Config |
| GET | `/api/retrieval-configs/rerank` | Get Rerank Config |
| PUT | `/api/retrieval-configs/rerank` | Set Rerank Config |
| POST | `/api/retrieval-configs/rerank/test` | Test Rerank Config |

## /api/schedules

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/schedules` | List Schedules |
| POST | `/api/schedules` | Create Schedule |
| POST | `/api/schedules/recurring` | Create Recurring Schedules |
| DELETE | `/api/schedules/{schedule_id}` | Cancel Schedule |
| GET | `/api/schedules/{schedule_id}` | Get Schedule |
| PATCH | `/api/schedules/{schedule_id}` | Update Schedule |
| GET | `/api/schedules/{schedule_id}/attendance` | Get Attendance |
| POST | `/api/schedules/{schedule_id}/attendance` | Submit Attendance |

## /api/search-configs

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| DELETE | `/api/search-configs` | Remove Search Config |
| GET | `/api/search-configs` | Get Search Config |
| PUT | `/api/search-configs` | Set Search Config |
| POST | `/api/search-configs/test` | Test Search Config |

## /api/students

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/students` | List Students |
| POST | `/api/students` | Create Student |
| DELETE | `/api/students/{student_id}` | Archive Student |
| GET | `/api/students/{student_id}` | Get Student |
| PATCH | `/api/students/{student_id}` | Update Student |
| DELETE | `/api/students/{student_id}/bindings/{kind}` | Unbind Student Account |
| PATCH | `/api/students/{student_id}/classes` | Update Student Classes |
| PATCH | `/api/students/{student_id}/follow-up` | Update Student Follow Up |
| GET | `/api/students/{student_id}/last-price` | Get Last Package Price |
| GET | `/api/students/{student_id}/lesson-records` | List Lesson Records |
| POST | `/api/students/{student_id}/lesson-records` | Adjust Lesson Balance |
| POST | `/api/students/{student_id}/refund` | Refund Student |
| GET | `/api/students/{student_id}/refund-preview` | Refund Preview Student |
| POST | `/api/students/{student_id}/renew` | Renew Student |
| PATCH | `/api/students/{student_id}/status` | Update Student Status |

## /api/system-settings

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/system-settings` | Read Settings |
| PUT | `/api/system-settings` | Update Settings |
| POST | `/api/system-settings/upload` | Upload Setting Image |

## /api/teacher

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/teacher/service/config-status` | Config Status |
| DELETE | `/api/teacher/service/parent-embedding-config` | Delete Parent Embedding Config |
| GET | `/api/teacher/service/parent-embedding-config` | Get Parent Embedding Config |
| POST | `/api/teacher/service/parent-embedding-config` | Save Parent Embedding Config |
| POST | `/api/teacher/service/parent-embedding-config/test` | Test Parent Embedding Config |
| GET | `/api/teacher/service/parent-embedding-index` | Parent Embedding Index |
| POST | `/api/teacher/service/parent-embedding-index/rebuild` | Rebuild Parent Embedding Index |
| DELETE | `/api/teacher/service/parent-llm-config` | Delete Parent Llm Config |
| GET | `/api/teacher/service/parent-llm-config` | Get Parent Llm Config |
| POST | `/api/teacher/service/parent-llm-config` | Set Parent Llm Config |
| DELETE | `/api/teacher/service/parent-rerank-config` | Delete Parent Rerank Config |
| GET | `/api/teacher/service/parent-rerank-config` | Get Parent Rerank Config |
| POST | `/api/teacher/service/parent-rerank-config` | Save Parent Rerank Config |
| POST | `/api/teacher/service/parent-rerank-config/test` | Test Parent Rerank Config |
| GET | `/api/teacher/service/quick-replies` | List Quick Replies |
| POST | `/api/teacher/service/quick-replies` | Create Quick Reply |
| DELETE | `/api/teacher/service/quick-replies/{reply_id}` | Delete Quick Reply |
| PATCH | `/api/teacher/service/quick-replies/{reply_id}` | Update Quick Reply |
| POST | `/api/teacher/service/quick-replies/{reply_id}/use` | Use Quick Reply |
| GET | `/api/teacher/service/threads` | Staff Threads |
| POST | `/api/teacher/service/threads/{thread_id}/close` | Staff Close |
| GET | `/api/teacher/service/threads/{thread_id}/messages` | Staff Messages |
| POST | `/api/teacher/service/threads/{thread_id}/reply` | Staff Reply |

## /api/trials

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/trials/invitations` | List Invitations |
| POST | `/api/trials/invitations` | Create Invitation |
| DELETE | `/api/trials/invitations/{inv_id}` | Delete Invitation |
| PATCH | `/api/trials/invitations/{inv_id}` | Update Invitation |
| POST | `/api/trials/invitations/{inv_id}/trial-student` | Create Trial Student |
| GET | `/api/trials/payroll-evidence` | Payroll Evidence |
| GET | `/api/trials/payroll-stats` | Payroll Stats |
| PATCH | `/api/trials/students/{student_id}/trial-status` | Update Trial Status |
| POST | `/api/trials/upload` | Upload Chat Image |

