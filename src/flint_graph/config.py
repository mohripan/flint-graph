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

# Dependency names a deployment may list as readiness-required or readiness-optional.
READINESS_DEPENDENCY_NAMES: frozenset[str] = frozenset(
    {
        "postgres",
        "object_store",
        "temporal",
        "neo4j",
        "opensearch",
        "embedding_provider",
        "answer_provider",
    }
)
# Local and test stay ergonomic: PostgreSQL is the only hard requirement, so a
# developer without the full compose stack still gets a ready API.
_LOCAL_REQUIRED_DEPENDENCIES: list[str] = ["postgres"]
_DEPLOYED_REQUIRED_DEPENDENCIES: list[str] = [
    "postgres",
    "object_store",
    "temporal",
    "neo4j",
    "opensearch",
]
# Provider outages degrade answers but should not pull a replica out of service.
_DEPLOYED_OPTIONAL_DEPENDENCIES: list[str] = ["embedding_provider", "answer_provider"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FLINT_GRAPH_",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["local", "test", "staging", "production"] = "local"
    auth_mode: Literal["dev", "oidc"] = "dev"
    allow_unsafe_dev_auth: bool = False
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_email_claim: str = "email"
    oidc_name_claim: str = "name"
    oidc_groups_claim: str = "groups"
    oidc_system_admin_group: str | None = None
    dev_auth_subject: str = "dev-user"
    dev_auth_email: str = "dev@example.local"
    dev_auth_name: str = "Local Developer"
    service_name: str = "flint-graph-api"
    service_version: str = "0.1.0"
    log_level: str = "INFO"
    public_base_url: str | None = None
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "test"]
    )
    require_tls: bool = False
    max_upload_bytes: int | None = None
    max_url_intake_bytes: int | None = None
    allow_private_url_intake: bool | None = None
    rate_limit_enabled: bool = False
    rate_limit_backend: Literal["memory"] = "memory"
    allow_in_memory_rate_limit: bool = False
    rate_limit_requests: int = Field(default=60, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)

    database_url: str = "postgresql+asyncpg://flint_graph:flint_graph@localhost:5432/flint_graph"
    database_echo: bool = False

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "ingestion"
    temporal_workflow_name: str = "IngestDocumentWorkflow"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "flintgraphpassword"
    neo4j_database: str = "neo4j"
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1)
    neo4j_connection_timeout_seconds: float = Field(default=30.0, gt=0.0)

    object_store_provider: Literal["s3"] = "s3"
    object_store_bucket: str = "flint-graph"
    object_store_endpoint_url: str | None = "http://localhost:9000"
    object_store_region: str = "us-east-1"
    object_store_access_key_id: str = "flint_graph"
    object_store_secret_access_key: str = "flint-graph-secret"
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
    query_ollama_context_tokens: int = Field(default=8192, ge=2048, le=131072)
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

    outbox_relay_id: str = "flint-graph-outbox-relay"
    outbox_relay_batch_size: int = Field(default=10, ge=1, le=100)
    outbox_relay_poll_interval_seconds: float = Field(default=2.0, gt=0.0)
    outbox_relay_retry_delay_seconds: int = Field(default=30, ge=0)
    projection_cleanup_poll_interval_seconds: float = Field(default=5.0, gt=0.0)

    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = True
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_metric_export_interval_millis: int = Field(default=60_000, ge=1_000)

    # Prometheus-style scrape endpoint. Off by default: it is an operational
    # surface, not part of the public API, and must not leak on a public origin.
    metrics_enabled: bool = False
    metrics_path: str = "/metrics"
    metrics_token: str | None = None

    # Structured logging never carries prompts, answers, or document text unless a
    # local operator explicitly opts in. Staging/production reject the opt-in.
    log_payloads: bool = False
    log_renderer: Literal["auto", "json", "console"] = "auto"

    # Readiness probes. Required dependencies fail readiness (503); optional ones are
    # reported but keep the instance in service so an outage alerts instead of
    # removing capacity that still works.
    readiness_required_dependencies: list[str] | None = None
    readiness_optional_dependencies: list[str] | None = None
    readiness_probe_timeout_seconds: float = Field(default=2.0, gt=0.0)
    readiness_cache_seconds: float = Field(default=5.0, ge=0.0)

    # Provider pricing, keyed "<provider>:<model>" (or "<provider>:*" as a fallback),
    # with per-million-token rates. Unpriced usage is recorded with a null cost
    # rather than a fabricated one.
    usage_pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    usage_currency: str = "USD"

    @field_validator("active_retrieval_index_version_id", mode="before")
    @classmethod
    def _empty_active_index_version_id_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator(
        "allowed_origins",
        "trusted_hosts",
        "readiness_required_dependencies",
        "readiness_optional_dependencies",
        mode="before",
    )
    @classmethod
    def _split_csv_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "readiness_required_dependencies",
        "readiness_optional_dependencies",
        mode="after",
    )
    @classmethod
    def _validate_dependency_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unknown = sorted(set(value) - READINESS_DEPENDENCY_NAMES)
        if unknown:
            raise ValueError(
                f"unknown readiness dependency name(s): {', '.join(unknown)}; "
                f"supported names are {', '.join(sorted(READINESS_DEPENDENCY_NAMES))}"
            )
        return value

    @field_validator("usage_pricing", mode="after")
    @classmethod
    def _validate_usage_pricing(
        cls, value: dict[str, dict[str, float]]
    ) -> dict[str, dict[str, float]]:
        allowed_rates = {"input_per_million", "output_per_million"}
        for key, rates in value.items():
            if ":" not in key:
                raise ValueError(
                    f"usage_pricing key '{key}' must use '<provider>:<model>' form"
                )
            unknown = sorted(set(rates) - allowed_rates)
            if unknown:
                raise ValueError(
                    f"usage_pricing['{key}'] has unsupported rate(s): {', '.join(unknown)}"
                )
            for rate_name, rate in rates.items():
                if rate < 0:
                    raise ValueError(
                        f"usage_pricing['{key}']['{rate_name}'] must not be negative"
                    )
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
        if self.max_upload_bytes is None:
            self.max_upload_bytes = self.intake_max_source_bytes
        if self.max_url_intake_bytes is None:
            self.max_url_intake_bytes = self.intake_max_source_bytes
        if self.allow_private_url_intake is None:
            self.allow_private_url_intake = self.env in {"local", "test"}
        if self.readiness_required_dependencies is None:
            self.readiness_required_dependencies = (
                list(_DEPLOYED_REQUIRED_DEPENDENCIES)
                if self.env in {"staging", "production"}
                else list(_LOCAL_REQUIRED_DEPENDENCIES)
            )
        if self.readiness_optional_dependencies is None:
            self.readiness_optional_dependencies = (
                list(_DEPLOYED_OPTIONAL_DEPENDENCIES)
                if self.env in {"staging", "production"}
                else []
            )
        return self

    @model_validator(mode="after")
    def _validate_resolution_thresholds(self) -> Self:
        if "ollama" in (self.query_answer_provider, self.query_support_provider):
            # Packing counts are estimates, not model-tokenizer admission. Reserve
            # additional capacity for instructions, schema, query and claim text.
            minimum_context = self.query_context_token_budget + self.query_answer_max_tokens + 2048
            if self.query_ollama_context_tokens < minimum_context:
                raise ValueError(
                    "query_ollama_context_tokens must cover query_context_token_budget "
                    "+ query_answer_max_tokens + 2048 prompt-overhead reserve"
                )
        if (
            self.auth_mode == "dev"
            and self.env in {"staging", "production"}
            and not self.allow_unsafe_dev_auth
        ):
            raise ValueError(
                "auth_mode='dev' is not allowed in staging/production unless "
                "allow_unsafe_dev_auth is explicitly enabled"
            )
        if self.auth_mode == "oidc":
            if not self.oidc_issuer:
                raise ValueError("oidc_issuer is required when auth_mode='oidc'")
            if not self.oidc_audience:
                raise ValueError("oidc_audience is required when auth_mode='oidc'")
        if self.env in {"staging", "production"}:
            if not self.public_base_url:
                raise ValueError("public_base_url is required in staging/production")
            if not self.allowed_origins:
                raise ValueError("allowed_origins is required in staging/production")
            if not self.trusted_hosts:
                raise ValueError("trusted_hosts is required in staging/production")
            if not self.require_tls:
                raise ValueError("require_tls must be enabled in staging/production")
            if self.allow_private_url_intake:
                raise ValueError("allow_private_url_intake is not allowed in staging/production")
            if not self.rate_limit_enabled:
                raise ValueError("rate_limit_enabled must be enabled in staging/production")
            if self.rate_limit_backend == "memory" and not self.allow_in_memory_rate_limit:
                raise ValueError(
                    "rate_limit_backend='memory' is not allowed in staging/production "
                    "unless allow_in_memory_rate_limit is explicitly enabled"
                )
            if self.log_payloads:
                raise ValueError(
                    "log_payloads is not allowed in staging/production: prompts, answers, "
                    "and document text must never be written to logs"
                )
            if self.metrics_enabled and not self.metrics_token:
                raise ValueError(
                    "metrics_token is required in staging/production when metrics_enabled "
                    "is true, so the scrape endpoint is not publicly readable"
                )
            if "postgres" not in (self.readiness_required_dependencies or []):
                raise ValueError(
                    "readiness_required_dependencies must include 'postgres' in "
                    "staging/production"
                )
            if self.object_store_access_key_id == "flint_graph":
                raise ValueError("object_store_access_key_id must not use the local default")
            if self.object_store_secret_access_key == "flint-graph-secret":
                raise ValueError("object_store_secret_access_key must not use the local default")
        overlapping = sorted(
            set(self.readiness_required_dependencies or [])
            & set(self.readiness_optional_dependencies or [])
        )
        if overlapping:
            raise ValueError(
                "readiness dependencies cannot be both required and optional: "
                + ", ".join(overlapping)
            )
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
