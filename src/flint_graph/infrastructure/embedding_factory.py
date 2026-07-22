from __future__ import annotations

import httpx

from flint_graph.application.embeddings import DeterministicEmbeddingModel, EmbeddingModel
from flint_graph.config import Settings
from flint_graph.infrastructure.embeddings import OpenAICompatibleEmbeddingModel
from flint_graph.infrastructure.ollama import OllamaEmbeddingModel


def create_embedding_model(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
) -> EmbeddingModel:
    if settings.embedding_provider == "deterministic":
        return DeterministicEmbeddingModel()
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddingModel(
            model=settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            http_client=http_client,
            base_url=settings.embedding_ollama_base_url,
        )
    if settings.embedding_openai_api_key is None:
        raise RuntimeError("embedding_openai_api_key is required")
    return OpenAICompatibleEmbeddingModel(
        model=settings.embedding_model,
        api_key=settings.embedding_openai_api_key,
        timeout_seconds=settings.embedding_timeout_seconds,
        http_client=http_client,
        base_url=settings.embedding_openai_base_url,
    )


def embedding_base_url(settings: Settings) -> str:
    if settings.embedding_provider == "ollama":
        return settings.embedding_ollama_base_url
    return settings.embedding_openai_base_url or "https://api.openai.com"
