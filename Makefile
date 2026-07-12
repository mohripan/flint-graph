.PHONY: install dev relay up down migrate revision test lint format typecheck check

install:
	uv sync --all-groups

dev:
	uv run uvicorn atlas_rag.main:app --reload --host 0.0.0.0 --port 8000

relay:
	uv run python -m atlas_rag.processes.outbox_relay

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

check: lint typecheck test
