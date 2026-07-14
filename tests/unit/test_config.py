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
