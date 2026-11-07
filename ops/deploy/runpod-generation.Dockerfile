# The isolated image and voice runtimes, whose PyTorch brings its own CUDA, and a small server. Weights
# are not in the image: they stay on the Network Volume, so nothing here redistributes them.
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

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=runtimes /app/runtimes /app/runtimes
COPY runtimes/imagegen/generate.py /app/runtimes/imagegen/generate.py
COPY runtimes/voicegen/generate.py /app/runtimes/voicegen/generate.py
COPY deploy/runpod/relay.py deploy/runpod/server.py deploy/runpod/fetch_weights.py /app/
COPY tools/narrative/fetch_model.py deploy/ansible/vars/models.yml /app/
# The paths the pinned requests name, on the volume Runpod mounts.
RUN ln -s /runpod-volume/models /models

CMD ["python", "/app/server.py"]
