# Child Code 后端服务

基于 FastAPI 的智能少儿编程教育管理系统后端。

## 环境要求

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)（依赖安装需科学上网）
- PostgreSQL（本地或远程实例）

## 安装步骤（在 backend/ 目录下执行）

```bash
# 1. 进入后端目录
cd backend

# 2. 创建虚拟环境并同步依赖（含 AI 可选依赖则追加 --extra ai）
uv sync --extra dev

# 3. 准备环境变量
#    Windows (PowerShell):
Copy-Item .env.example .env
#    Linux / macOS:
#    cp .env.example .env

# 4. 修改 .env 中的 DATABASE_URL、SECRET_KEY（生产环境必改）

# 5. 在 PostgreSQL 中创建数据库（如尚未创建）
#    psql -U postgres -c "CREATE DATABASE child_code;"

# 6. 应用数据库迁移
uv run alembic upgrade head
```

## 运行

```bash
# 开发模式（自动重载）
uv run uvicorn app.main:app --reload --port 8000
```

- Swagger 文档：http://127.0.0.1:8000/api/docs
- 健康检查：http://127.0.0.1:8000/api/health

## 可选：AI 能力

M3+ 里程碑启用 AI（报告/PPT/习题）。安装可选依赖：

```bash
uv sync --extra ai
# 或
uv pip install -r requirements-ai.txt
```

在 `.env` 中配置 `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`（默认 `deepseek-v4-pro`，可自定义）。

## 质检

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pytest                # 测试
```

## 目录说明

- `app/models/` - SQLAlchemy 模型
- `app/schemas/` - Pydantic 校验模型
- `app/crud/` - 数据访问层
- `app/api/` - 路由与依赖
- `app/core/` - 配置 / 安全 / 数据库会话
- `alembic/` - 数据库迁移脚本

## 常用命令（uv）

```bash
uv add <package>               # 添加依赖
uv remove <package>            # 移除依赖
uv sync                        # 同步环境
uv run <command>               # 在虚拟环境中执行命令
```