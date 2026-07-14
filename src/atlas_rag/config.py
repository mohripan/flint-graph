import os
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DETERMINISTIC_EMBEDDING_MODEL = "deterministic-test"
_DETERMINISTIC_EMBEDDING_DIMENSIONS = 384
# Default real embedding model + dimensions per provider. Dimensions are intrinsic to the
# model, so switching providers/models requires a new retrieval index version + backfill.
_REAL_EMBEDDING_MODELS: dict[str, str] = {
    "ollama": "nomic-embed-text",
    "openai_compatible": "text-embedding-3-small",
}
_REAL_EMBEDDING_DIMENSIONS: dict[str, int] = {
    "ollama": 768,
    "openai_compatible": 1536,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ATLAS_",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["local", "test", "staging", "production"] = "local"
    service_name: str = "atlas-rag-api"
    service_version: str = "0.1.0"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas"
    database_echo: bool = False

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "ingestion"
    temporal_workflow_name: str = "IngestDocumentWorkflow"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "atlaspassword"
    neo4j_database: str = "neo4j"
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1)
    neo4j_connection_timeout_seconds: float = Field(default=30.0, gt=0.0)

    object_store_provider: Literal["s3"] = "s3"
    object_store_bucket: str = "atlas-rag"
    object_store_endpoint_url: str | None = "http://localhost:9000"
    object_store_region: str = "us-east-1"
    object_store_access_key_id: str = "atlas"
    object_store_secret_access_key: str = "atlas-secret"
    object_store_force_path_style: bool = True
    object_store_connect_timeout_seconds: int = Field(default=5, ge=1)
    object_store_read_timeout_seconds: int = Field(default=30, ge=1)
    object_store_max_pool_connections: int = Field(default=20, ge=1)

    intake_max_source_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    intake_url_timeout_seconds: float = Field(default=10.0, gt=0.0)

    parser_timeout_seconds: float = Field(default=30.0, gt=0.0)
    parser_max_raw_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    parser_max_normalized_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    parser_max_elements: int = Field(default=10_000, ge=1)

    chunking_max_chunk_chars: int = Field(default=1200, ge=1)
    chunking_overlap_chars: int = Field(default=120, ge=0)

    extraction_enabled: bool = True
    extraction_mode: Literal["disabled", "optional", "required"] = "optional"
    llm_provider: Literal["ollama", "deterministic"] = "ollama"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "gemma3:1b"
    extraction_timeout_seconds: int = Field(default=180, ge=1)

    indexing_mode: Literal["disabled", "optional", "required"] = "optional"
    # Left unset (None) so the default resolves by env (see _resolve_env_provider_defaults):
    # test -> deterministic, local -> ollama, staging/production -> openai_compatible.
    # Explicit values always win. embedding_model/dimensions follow the resolved provider
    # unless the operator sets them explicitly.
    embedding_provider: Literal["deterministic", "ollama", "openai_compatible"] | None = None
    embedding_model: str = _DETERMINISTIC_EMBEDDING_MODEL
    embedding_dimensions: int = Field(default=_DETERMINISTIC_EMBEDDING_DIMENSIONS, ge=1)
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    embedding_timeout_seconds: int = Field(default=60, ge=1)
    embedding_ollama_base_url: str = "http://host.docker.internal:11434"
    embedding_openai_base_url: str | None = "https://api.openai.com"
    embedding_openai_api_key: str | None = None
    active_retrieval_index_version_id: str | None = None
    index_backfill_batch_size: int = Field(default=25, ge=1, le=500)

    query_enabled: bool = True
    query_classifier_provider: Literal["deterministic", "ollama"] = "deterministic"
    query_reranker_provider: Literal["deterministic", "ollama"] = "deterministic"
    # Left unset (None) so defaults resolve by env: test -> deterministic,
    # otherwise -> anthropic. Explicit values always win. See _resolve_env_provider_defaults.
    query_answer_provider: Literal["deterministic", "ollama", "anthropic"] | None = None
    query_answer_model: str = "llama3.2"
    query_answer_timeout_seconds: int = Field(default=180, ge=1)
    query_answer_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    query_answer_max_tokens: int = Field(default=1024, ge=1)
    query_support_provider: Literal["deterministic", "ollama", "anthropic"] | None = None
    query_support_model: str = "llama3.2"

    anthropic_api_key: str | None = None
    anthropic_answer_model: str = "claude-opus-4-8"
    anthropic_support_model: str = "claude-opus-4-8"
    anthropic_support_max_tokens: int = Field(default=1024, ge=1)
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    query_min_supported_claim_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    query_min_context_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    query_answer_stream_tokens: bool = True
    query_default_candidate_limit: int = Field(default=10, ge=1, le=100)
    query_max_candidate_limit: int = Field(default=50, ge=1, le=500)
    query_context_token_budget: int = Field(default=4000, ge=1, le=100_000)
    query_max_context_records: int = Field(default=25, ge=1, le=100)
    query_graph_depth: int = Field(default=1, ge=0, le=3)
    query_stream_heartbeat_seconds: int = Field(default=15, ge=1, le=300)

    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    opensearch_timeout_seconds: int = Field(default=30, ge=1)

    entity_resolution_auto_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    entity_resolution_review_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    entity_resolution_trigram_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    entity_resolution_candidate_limit: int = Field(default=20, ge=1)

    outbox_relay_id: str = "atlas-rag-outbox-relay"
    outbox_relay_batch_size: int = Field(default=10, ge=1, le=100)
    outbox_relay_poll_interval_seconds: float = Field(default=2.0, gt=0.0)
    outbox_relay_retry_delay_seconds: int = Field(default=30, ge=0)

    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = True
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("active_retrieval_index_version_id", mode="before")
    @classmethod
    def _empty_active_index_version_id_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @model_validator(mode="after")
    def _resolve_env_provider_defaults(self) -> Self:
        # Env-aware defaults: test stays fully deterministic (offline, no keys); other
        # environments default to real providers. Explicit settings always win. This runs
        # before _validate_resolution_thresholds so credential checks see resolved providers.
        answer_support_default: Literal["deterministic", "anthropic"] = (
            "deterministic" if self.env == "test" else "anthropic"
        )
        if self.query_answer_provider is None:
            self.query_answer_provider = answer_support_default
        if self.query_support_provider is None:
            self.query_support_provider = answer_support_default

        embedding_provider = self.embedding_provider
        if embedding_provider is None:
            if self.env == "test":
                embedding_provider = "deterministic"
            elif self.env == "local":
                embedding_provider = "ollama"
            else:
                embedding_provider = "openai_compatible"
            self.embedding_provider = embedding_provider

        # Follow the resolved real provider's model/dimensions only when they are still the
        # deterministic sentinels (operator did not choose them explicitly). Changing the
        # embedding model requires a new retrieval index version + backfill.
        if embedding_provider != "deterministic":
            if self.embedding_model == _DETERMINISTIC_EMBEDDING_MODEL:
                self.embedding_model = _REAL_EMBEDDING_MODELS[embedding_provider]
            if self.embedding_dimensions == _DETERMINISTIC_EMBEDDING_DIMENSIONS:
                self.embedding_dimensions = _REAL_EMBEDDING_DIMENSIONS[embedding_provider]
        return self

    @model_validator(mode="after")
    def _validate_resolution_thresholds(self) -> Self:
        if self.entity_resolution_review_threshold > self.entity_resolution_auto_threshold:
            raise ValueError(
                "entity_resolution_review_threshold must be <= entity_resolution_auto_threshold"
            )
        if self.embedding_provider == "openai_compatible":
            if not self.embedding_openai_base_url:
                raise ValueError(
                    "embedding_openai_base_url is required when embedding_provider is "
                    "openai_compatible"
                )
            if not self.embedding_openai_api_key:
                raise ValueError(
                    "embedding_openai_api_key is required when embedding_provider is "
                    "openai_compatible"
                )
        if self.query_default_candidate_limit > self.query_max_candidate_limit:
            raise ValueError(
                "query_default_candidate_limit must be <= query_max_candidate_limit"
            )
        uses_anthropic = "anthropic" in (
            self.query_answer_provider,
            self.query_support_provider,
        )
        if uses_anthropic and not self.anthropic_api_key and not os.environ.get(
            "ANTHROPIC_API_KEY"
        ):
            raise ValueError(
                "anthropic_api_key (or the ANTHROPIC_API_KEY environment variable) is "
                "required when an anthropic provider is selected"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
