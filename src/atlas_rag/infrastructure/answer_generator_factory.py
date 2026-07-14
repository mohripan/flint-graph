from __future__ import annotations

import httpx

from atlas_rag.application.query_faithfulness import DeterministicSupportChecker
from atlas_rag.application.query_orchestration import (
    AnswerGenerator,
    DeterministicAnswerGenerator,
    SupportChecker,
)
from atlas_rag.config import Settings
from atlas_rag.infrastructure.ollama import OllamaAnswerGenerator


def create_answer_generator(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
) -> AnswerGenerator:
    if settings.query_answer_provider == "deterministic":
        return DeterministicAnswerGenerator()
    return OllamaAnswerGenerator(
        model=settings.query_answer_model,
        timeout_seconds=settings.query_answer_timeout_seconds,
        temperature=settings.query_answer_temperature,
        max_tokens=settings.query_answer_max_tokens,
        http_client=http_client,
        base_url=settings.ollama_base_url,
    )


def create_support_checker(settings: Settings) -> SupportChecker:
    if settings.query_support_provider == "deterministic":
        return DeterministicSupportChecker()
    raise RuntimeError("Ollama support checker is not implemented yet.")


def answer_generator_base_url(settings: Settings) -> str:
    if settings.query_answer_provider == "ollama":
        return settings.ollama_base_url
    return settings.ollama_base_url
