import httpx
import pytest

from atlas_rag.application.query_faithfulness import DeterministicSupportChecker
from atlas_rag.application.query_orchestration import DeterministicAnswerGenerator
from atlas_rag.config import Settings
from atlas_rag.infrastructure.answer_generator_factory import (
    create_answer_generator,
    create_support_checker,
)
from atlas_rag.infrastructure.ollama import OllamaAnswerGenerator


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


def test_support_checker_factory_rejects_unimplemented_ollama_judge() -> None:
    settings = Settings(query_support_provider="ollama")

    with pytest.raises(RuntimeError, match="Ollama support checker is not implemented"):
        create_support_checker(settings)
