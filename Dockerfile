FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY runtimes ./runtimes
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 flintgraph
WORKDIR /app
COPY --from=builder --chown=flintgraph:flintgraph /app /app
# A number, so Kubernetes can verify that this is not root.
USER 10001

EXPOSE 8000
CMD ["uvicorn", "flint_graph.main:app", "--host", "0.0.0.0", "--port", "8000"]
