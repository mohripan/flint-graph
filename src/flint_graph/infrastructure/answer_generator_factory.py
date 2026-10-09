from __future__ import annotations

from typing import Any

import httpx

from flint_graph.application.query_faithfulness import DeterministicSupportChecker
from flint_graph.application.query_orchestration import (
    AnswerGenerator,
    DeterministicAnswerGenerator,
    SupportChecker,
)
from flint_graph.config import Settings
from flint_graph.infrastructure.anthropic import (
    AnthropicAnswerGenerator,
    AnthropicSupportChecker,
)
from flint_graph.infrastructure.ollama import OllamaAnswerGenerator, OllamaSupportChecker


def answer_generator_model(settings: Settings) -> str:
    if settings.query_answer_provider == "anthropic":
        return settings.anthropic_answer_model
    if settings.query_answer_provider == "ollama":
        return settings.query_answer_model
    return "deterministic"


def support_checker_model(settings: Settings) -> str:
    if settings.query_support_provider == "anthropic":
        return settings.anthropic_support_model
    if settings.query_support_provider == "ollama":
        return settings.query_support_model
    return "deterministic"


def create_answer_generator(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
    anthropic_client: Any | None = None,
) -> AnswerGenerator:
    provider = settings.query_answer_provider
    if provider == "ollama":
        if http_client is None:
            raise RuntimeError("the ollama answer generator requires an http client")
        return OllamaAnswerGenerator(
            model=answer_generator_model(settings),
            timeout_seconds=settings.query_answer_timeout_seconds,
            temperature=settings.query_answer_temperature,
            max_tokens=settings.query_answer_max_tokens,
            http_client=http_client,
            base_url=settings.ollama_base_url,
        )
    if provider == "anthropic":
        # The Anthropic SDK client manages its own transport; when no client is
        # injected the adapter constructs one from the configured API key.
        return AnthropicAnswerGenerator(
            model=answer_generator_model(settings),
            max_tokens=settings.query_answer_max_tokens,
            effort=settings.anthropic_effort,
            timeout_seconds=settings.query_answer_timeout_seconds,
            api_key=settings.anthropic_api_key,
            client=anthropic_client,
        )
    return DeterministicAnswerGenerator()


def create_support_checker(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
    anthropic_client: Any | None = None,
) -> SupportChecker:
    provider = settings.query_support_provider
    if provider == "anthropic":
        return AnthropicSupportChecker(
            model=support_checker_model(settings),
            max_tokens=settings.anthropic_support_max_tokens,
            effort=settings.anthropic_effort,
            timeout_seconds=settings.query_answer_timeout_seconds,
            api_key=settings.anthropic_api_key,
            client=anthropic_client,
        )
    if provider == "ollama":
        if http_client is None:
            raise RuntimeError("the ollama support checker requires an http client")
        return OllamaSupportChecker(
            model=support_checker_model(settings),
            timeout_seconds=settings.query_answer_timeout_seconds,
            temperature=settings.query_answer_temperature,
            max_tokens=settings.query_answer_max_tokens,
            http_client=http_client,
            base_url=settings.ollama_base_url,
        )
    return DeterministicSupportChecker()


def answer_generator_base_url(settings: Settings) -> str:
    return settings.ollama_base_url
