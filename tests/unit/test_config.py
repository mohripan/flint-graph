import pytest
from pydantic import ValidationError

from atlas_rag.config import Settings


def test_settings_accept_default_retrieval_indexing_configuration() -> None:
    settings = Settings()

    assert settings.indexing_mode == "optional"
    assert settings.embedding_provider == "deterministic"
    assert settings.embedding_model == "deterministic-test"
    assert settings.embedding_dimensions == 384
    assert settings.embedding_batch_size == 32
    assert settings.index_backfill_batch_size == 25
    assert settings.opensearch_url == "http://localhost:9200"
    assert settings.active_retrieval_index_version_id is None


def test_settings_accept_default_query_orchestration_configuration() -> None:
    settings = Settings()

    assert settings.query_enabled is True
    assert settings.query_classifier_provider == "deterministic"
    assert settings.query_reranker_provider == "deterministic"
    assert settings.query_answer_provider == "deterministic"
    assert settings.query_default_candidate_limit == 10
    assert settings.query_max_candidate_limit == 50
    assert settings.query_context_token_budget == 4000
    assert settings.query_stream_heartbeat_seconds == 15
    assert settings.query_answer_model == "llama3.2"
    assert settings.query_answer_timeout_seconds == 180
    assert settings.query_answer_temperature == 0.0
    assert settings.query_answer_max_tokens == 1024
    assert settings.query_support_provider == "deterministic"
    assert settings.query_support_model == "llama3.2"
    assert settings.query_min_supported_claim_ratio == 0.5
    assert settings.query_min_context_relevance == 0.0
    assert settings.query_answer_stream_tokens is True


def test_settings_reject_query_default_candidate_limit_above_maximum() -> None:
    with pytest.raises(ValidationError, match="query_default_candidate_limit"):
        Settings(
            query_default_candidate_limit=51,
            query_max_candidate_limit=50,
        )


def test_settings_reject_invalid_query_faithfulness_thresholds() -> None:
    with pytest.raises(ValidationError):
        Settings(query_min_supported_claim_ratio=1.1)

    with pytest.raises(ValidationError):
        Settings(query_min_context_relevance=-0.1)


def test_settings_reject_openai_compatible_provider_without_base_url() -> None:
    with pytest.raises(ValidationError, match="embedding_openai_base_url"):
        Settings(
            embedding_provider="openai_compatible",
            embedding_openai_base_url=None,
        )


def test_settings_reject_openai_compatible_provider_without_api_key() -> None:
    with pytest.raises(ValidationError, match="embedding_openai_api_key"):
        Settings(
            embedding_provider="openai_compatible",
            embedding_openai_api_key=None,
        )


def test_model_providers_resolve_to_deterministic_in_test_env() -> None:
    settings = Settings(env="test")

    assert settings.query_answer_provider == "deterministic"
    assert settings.query_support_provider == "deterministic"


def test_model_providers_resolve_to_anthropic_outside_test_env() -> None:
    settings = Settings(env="local", anthropic_api_key="sk-test")

    assert settings.query_answer_provider == "anthropic"
    assert settings.query_support_provider == "anthropic"


def test_explicit_model_provider_overrides_env_default() -> None:
    settings = Settings(
        env="local",
        query_answer_provider="deterministic",
        query_support_provider="deterministic",
    )

    assert settings.query_answer_provider == "deterministic"
    assert settings.query_support_provider == "deterministic"


def test_anthropic_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="anthropic_api_key"):
        Settings(env="local")


def test_anthropic_provider_accepts_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")

    settings = Settings(env="production")

    assert settings.query_answer_provider == "anthropic"
    assert settings.anthropic_api_key is None
