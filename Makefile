# 质检线（Backend + Frontend + Docs）
# 后端依赖需 uv + 科学上网安装；前端依赖需 npm install。

.PHONY: help install install-ai setup lint format test run frontend dev check

help:
	@echo "Child Code 质检线"
	@echo "  make install     安装后端依赖（uv sync --extra dev）"
	@echo "  make install-ai  额外安装 AI 可选依赖"
	@echo "  make setup       安装后端+前端依赖"
	@echo "  make lint        后端 ruff 检查"
	@echo "  make format      后端 ruff 格式化"
	@echo "  make test        后端 pytest 测试"
	@echo "  make run         启动后端开发服务（8000）"
	@echo "  make frontend    启动前端开发服务（5173）"
	@echo "  make check       依次执行 lint + test"

install:
	cd backend && uv sync --extra dev

install-ai:
	cd backend && uv sync --extra ai

setup: install
	cd frontend && npm install

lint:
	cd backend && uv run ruff check .

format:
	cd backend && uv run ruff format .

test:
	cd backend && uv run pytest

run:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

check: lint test
	@echo "All checks passed."