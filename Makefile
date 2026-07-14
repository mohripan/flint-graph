.PHONY: install dev relay worker up down migrate revision test lint format typecheck eval-gate check

install:
	uv sync --all-groups

dev:
	uv run uvicorn atlas_rag.main:app --reload --host 0.0.0.0 --port 8000

relay:
	uv run python -m atlas_rag.processes.outbox_relay

worker:
	uv run python -m atlas_rag.processes.ingestion_worker

up:
	docker compose up -d --build

down:
	docker compose down -v

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy

eval-gate:
	uv run atlas-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic

check: lint typecheck test eval-gate
