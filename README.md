# Child Code · 智能少儿编程教育管理系统

> 面向少儿编程培训机构的一体化教务与 AI 助手平台：把课后反馈、周期报告、学员评估、家长会 PPT、AI 习题、知识库检索与用量成本，收进同一套系统。

![系统首页](docs/screenshots/overview.png)

> 截图占位：请将实际界面截图按下方「截图清单」命名后放入 `docs/screenshots/`，README 会自动引用。

## 核心能力

- **教师提效**：AI 生成课后反馈、日报/周报/季度/年度总结、学员评估与家长会 PPT 草稿，人工审核后发布
- **教务数字化**：学员、班级、教师、排课、考勤、课时包、催缴名单全流程在线
- **家长/学员自助**：客户端查看课时余量、反馈、作业并完成订阅
- **AI 工作台**：Agent 对话、工具调用、技能包与知识库
- **知识库与评测（RAG）**：知识资产、检索路由、追踪、任务、会话观测与评测
- **用量与成本**：全链路 Token 计价、预算告警、月度对账与模块成本归因
- **细粒度权限**：角色 + 权限键 + 职务预设，逐接口鉴权

## 功能模块

| 模块 | 说明 |
| --- | --- |
| 学员 / 班级 / 教师 | 档案、分班、带教绑定、课时状态与催缴 |
| 排课与考勤 | 排课、到课、划课时，驱动课时消耗 |
| 课后反馈 | 逐生反馈、AI 草稿、家长可见 |
| 报告与总结 | 日报/周报/季度/年度总结、PPT 生成 |
| 学员评估 | 三个月综合评估、家长会 PPT |
| AI 习题 | 出题、发布作业、作答与批改 |
| Agent 工作台 | 对话、工具、技能包、分享 |
| 教学服务 | 家长会话回复 |
| 财务 | 订单、收款、退费、薪资 |
| 后台管理（RAG） | 资产、路由、评测、追踪、任务、会话、设置 |
| 用量与成本 | 计价、预算、对账、成本归因 |

## 系统截图

### 学员管理
![学员管理](docs/screenshots/students.png)

### 排课与考勤
![排课与考勤](docs/screenshots/schedules.png)

### 课后反馈
![课后反馈](docs/screenshots/feedbacks.png)

### 学员评估
![学员评估](docs/screenshots/evaluations.png)

### 后台管理 · 评测
![RAG 评测](docs/screenshots/rag-eval.png)

### 用量与成本
![用量与成本](docs/screenshots/usage.png)

### 开发文档界面
![开发文档](docs/screenshots/docs.png)

## 截图清单

| 文件名 | 页面 | 建议尺寸 |
| --- | --- | --- |
| `overview.png` | 系统首页/工作台 | 1600×900 |
| `students.png` | 学员管理 | 1600×900 |
| `schedules.png` | 排课与考勤 | 1600×900 |
| `feedbacks.png` | 课后反馈 | 1600×900 |
| `evaluations.png` | 学员评估 | 1600×900 |
| `rag-eval.png` | 后台管理 · 评测 | 1600×900 |
| `usage.png` | 用量与成本 | 1600×900 |
| `docs.png` | 开发文档 | 1600×900 |

> 放入 `docs/screenshots/` 后无需改 README；未放图片时 GitHub 显示占位说明。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Vue Router |
| 后端 | FastAPI + Pydantic + SQLAlchemy + Alembic + PostgreSQL |
| 模型接入 | **LangChain**（langchain-core / langchain-openai）：ChatOpenAI、OpenAIEmbeddings、原生 function calling |
| Agent 编排 | 自研 **Plan-and-Run** 多轮工具调用（意图路由 + 规划器 + 记忆 + 兜底） |
| 向量检索 | **ChromaDB**（按 embedding 指纹分片）+ 两阶段检索 + Rerank 熔断 |
| 工具协议 | **MCP**（Streamable HTTP / JSON-RPC） |
| 沙箱执行 | **E2B 2.31 / 百炼 Sandbox** 运行 Skill 脚本 |
| 文档产物 | python-pptx / pypdf / python-docx / reportlab |
| 部署 | Docker Compose + Nginx |

> 说明：系统**深度使用 LangChain**；**LangGraph** 仅在 `ai` 可选依赖中声明预留，当前代码未使用，Agent 编排为自研 Plan-and-Run。详见 [AI 与 Agent 架构](frontend/src/docs/ai-agent.md)。

## AI 与 Agent 技术亮点

- **意图路由**：规则 + LLM 分类，自动决定检索、业务工具、PPT、MCP 等链路
- **Plan-and-Run**：原生 function calling 多轮规划，带轮次/次数/耗时预算、去重与启发式兜底
- **记忆体系**：短期窗口 + 摘要 + 长期记忆（Top-K）+ 工作记忆，异步蒸馏
- **工具生态**：业务查询、只读 SQL（白名单/脱敏/限流）、联网搜索、知识检索、Skill、MCP
- **沙箱执行**：E2B / 百炼隔离运行脚本，产物自动回传
- **RAG 工程**：Embedding 指纹分片、两阶段检索、Rerank 熔断、家长独立检索域
- **可观测与成本**：span 全链路追踪 + 异步用量记账 + 版本化计价与月度对账

## 快速开始

### 后端

```bash
cd backend
uv sync --extra dev
cp .env.example .env          # 修改 DATABASE_URL、SECRET_KEY
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173，/api 代理到 8000
```

### 容器部署

```bash
cp .env.prod.example .env.prod   # 填写 POSTGRES_PASSWORD 等
docker compose up -d --build
```

## 文档导航

**应用内开发文档**：登录后访问 `/docs`（管理员/教务可见），按模块组织、支持搜索与目录定位。

| 文档 | 文件 |
| --- | --- |
| 文档首页 | [frontend/src/docs/index.md](frontend/src/docs/index.md) |
| 系统架构 | [frontend/src/docs/architecture.md](frontend/src/docs/architecture.md) |
| AI 与 Agent 架构 | [frontend/src/docs/ai-agent.md](frontend/src/docs/ai-agent.md) |
| 权限体系 | [frontend/src/docs/permissions.md](frontend/src/docs/permissions.md) |
| 业务模块 | [frontend/src/docs/modules.md](frontend/src/docs/modules.md) |
| 后台管理（RAG） | [frontend/src/docs/rag-admin.md](frontend/src/docs/rag-admin.md) |
| 评测数据规格 | [frontend/src/docs/rag-eval-spec.md](frontend/src/docs/rag-eval-spec.md) |
| 用量与成本 | [frontend/src/docs/usage-cost.md](frontend/src/docs/usage-cost.md) |
| 接口约定 | [frontend/src/docs/api.md](frontend/src/docs/api.md) |
| 部署与运维 | [frontend/src/docs/ops.md](frontend/src/docs/ops.md) |

其他资料：

- 产品需求：[docs/prd/PRD.md](docs/prd/PRD.md)
- 架构决策：[docs/adr/README.md](docs/adr/README.md)
- 术语表：[docs/glossary.md](docs/glossary.md)
- 评测导入规格：[docs/rag-eval-import-format.md](docs/rag-eval-import-format.md)

## 目录结构

```text
backend/   FastAPI 应用、模型、迁移、测试
frontend/  Vue 3 应用（管理端 + 客户端 H5）
docs/      PRD、ADR、术语表、规格说明、截图
deploy/    部署相关
```

## 权限与安全

- 角色：管理员 / 教务 / 教师 / 家长 / 学员
- 教师按权限键逐项开关，敏感模块默认关闭
- 敏感配置（数据库口令、密钥、模型 Key）不入库、不写日志

## 质量保障

```bash
cd backend && uv run pytest
cd backend && uv run ruff check .
cd frontend && npm run build
```

## 许可证

内部项目，未经授权请勿外传。
