# 质检线（Backend + Frontend + Docs）
# 后端依赖需 uv + 科学上网安装；前端依赖需 npm install。

.PHONY: help install install-ai setup lint format test run frontend dev check release

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
	@echo "  make release     生产发版：构建 → 评测闸门（GATE_SET_NAME）→ 上线"

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

# 生产发版：先构建新镜像，用新镜像跑评测闸门（读线上库），通过后才上线。
# 用法：GATE_SET_NAME="行舟-家长客服回归集" make release
# 发布证据要求（硬性）：answer_eval=on、人工复核 ≥10 对且 Kappa≥0.6、存在基线运行。
# 未设置 GATE_SET_NAME 时跳过闸门（不推荐，仅应急）。
release:
	@if [ -z "$$GATE_SET_NAME" ]; then \
		echo "警告：未设置 GATE_SET_NAME，跳过评测闸门（不推荐）"; \
	fi
	docker compose build backend
	@if [ -n "$$GATE_SET_NAME" ]; then \
		docker compose run --rm -T backend /srv/app/.venv/bin/python -m scripts.deploy_gate \
			--set-name "$$GATE_SET_NAME" --require-answer --require-calibration --require-baseline \
			|| { echo "评测闸门未通过，已中止发版"; exit 1; }; \
	fi
	docker compose up -d
	@echo "发版完成：docker compose ps 查看状态"