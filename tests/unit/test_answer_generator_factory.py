import httpx

from flint_graph.application.query_faithfulness import DeterministicSupportChecker
from flint_graph.application.query_orchestration import DeterministicAnswerGenerator
from flint_graph.config import Settings
from flint_graph.infrastructure import ollama
from flint_graph.infrastructure.answer_generator_factory import (
    create_answer_generator,
    create_support_checker,
)
from flint_graph.infrastructure.anthropic import (
    AnthropicAnswerGenerator,
    AnthropicSupportChecker,
)
from flint_graph.infrastructure.ollama import OllamaAnswerGenerator


def test_answer_generator_factory_defaults_to_deterministic() -> None:
    settings = Settings(query_answer_provider="deterministic")

    generator = create_answer_generator(settings, http_client=httpx.AsyncClient())

    assert isinstance(generator, DeterministicAnswerGenerator)


def test_answer_generator_factory_creates_ollama_generator() -> None:
    settings = Settings(
        query_answer_provider="ollama",
        query_answer_model="llama3.2",
        query_answer_timeout_seconds=12,
        query_answer_temperature=0.2,
        query_answer_max_tokens=256,
    )

    generator = create_answer_generator(settings, http_client=httpx.AsyncClient())

    assert isinstance(generator, OllamaAnswerGenerator)


def test_support_checker_factory_defaults_to_deterministic() -> None:
    settings = Settings(query_support_provider="deterministic")

    checker = create_support_checker(settings)

    assert isinstance(checker, DeterministicSupportChecker)


def test_support_checker_factory_creates_ollama_checker() -> None:
    settings = Settings(query_support_provider="ollama")

    checker = create_support_checker(settings, http_client=httpx.AsyncClient())

    assert isinstance(checker, ollama.OllamaSupportChecker)


def test_answer_generator_factory_creates_anthropic_generator() -> None:
    settings = Settings(
        query_answer_provider="anthropic",
        anthropic_api_key="sk-test",
        anthropic_answer_model="claude-opus-4-8",
    )

    generator = create_answer_generator(settings, http_client=httpx.AsyncClient())

    assert isinstance(generator, AnthropicAnswerGenerator)


def test_support_checker_factory_creates_anthropic_checker() -> None:
    settings = Settings(
        query_support_provider="anthropic",
        anthropic_api_key="sk-test",
        anthropic_support_model="claude-opus-4-8",
    )

    checker = create_support_checker(settings)

    assert isinstance(checker, AnthropicSupportChecker)
