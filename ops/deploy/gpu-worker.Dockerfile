# The API's code plus the isolated image and voice runtimes, whose PyTorch brings its own CUDA. Weights
# are not in the image: they stay on the GPU server's disk, mounted at /models.

# The runtimes come first, from their locks alone, and become their own layer of the image. Changing
# the application then neither rebuilds them nor makes the GPU server, billed by the hour, download
# them again.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtimes

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /app
COPY runtimes/imagegen/pyproject.toml runtimes/imagegen/uv.lock runtimes/imagegen/
COPY runtimes/voicegen/pyproject.toml runtimes/voicegen/uv.lock runtimes/voicegen/
RUN cd runtimes/imagegen && uv sync --frozen --no-dev
RUN cd runtimes/voicegen && uv sync --frozen --no-dev
COPY ops/deploy/share_identical_files.py /tmp/share_identical_files.py
RUN python /tmp/share_identical_files.py runtimes/imagegen/.venv runtimes/voicegen/.venv

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS application

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
COPY --from=runtimes --chown=flintgraph:flintgraph /app/runtimes /app/runtimes
COPY --from=application --chown=flintgraph:flintgraph /app /app
# A number, so Kubernetes can verify that this is not root.
USER 10001
