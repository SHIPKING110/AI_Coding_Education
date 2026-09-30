# CLAUDE.md —— 会话启动导航

> 每次会话开始时，请按本文件指引建立上下文。核心协作规范见 `agent.md`，规则库见 `.claude/rules/`。

## 第一步：建立上下文（必读顺序）

1. 读取 **`.claude-summary.md`** —— 快速了解项目是什么
2. 读取 **`.tasks/current.md`** —— 当前进行中 / 待办 / 已完成任务
3. 读取 **`agent.md`** —— 项目说明、约束、文档定位速查、自检与自修复
4. 读取 **`.claude/rules/`**（00-governance / 10-engineering / 11-project-arch / 99-self-check）
5. 需要功能细节时读 **`docs/prd/PRD.md`**，需要设计/数据结构/API 时读 **`spec/design.md`**

## 任务进行中

- 严格遵循 `.claude/rules/*.mdc` 与 `agent.md` 的约束、自检、自修复规则
- 功能实现做依 PRD 编号对齐；表结构改动走 Alembic 迁移
- 完成后回填 `.tasks/current.md` 与相关设计文档

## 文档体系速览

| 文件 | 角色 |
| --- | --- |
| `CLAUDE.md` | 启动导航（本文件） |
| `agent.md` | 核心说明 + 约束 + 自检 + 自修复 + 文档路径 |
| `.claude-summary.md` | 项目概览 |
| `.tasks/current.md` | 任务状态 |
| `.claude/rules/*.mdc` | 治理 / 工程 / 架构 / 自检规则 |
| `docs/prd/PRD.md` | 产品需求 |
| `spec/design.md` | 系统设计 |
| `.claude/plan` | 里程碑与关键决策 |
| `.claude/skill/` | skill 工具库 |

## 环境提示

- 无 `make`；PowerShell 5.1 无 `&&`；依赖安装（uv/npm）需科学上网由用户执行
- 后端 8000、前端 5173；认证冒烟闭环作为回归基线（见 `spec/design.md`）