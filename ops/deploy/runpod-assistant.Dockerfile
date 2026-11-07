# Ollama and a small server. Models are on the Network Volume, in OLLAMA_MODELS.
FROM ollama/ollama:0.40.15@sha256:0e59999e0e8f9fd4e704bd788a89b7e4cad399367fb1365f8c102ac662288761

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/runpod/assistant.py /app/assistant.py

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/app/assistant.py"]
