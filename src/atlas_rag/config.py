from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    llm_provider: Literal["ollama"] = "ollama"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "gemma3:1b"
    extraction_timeout_seconds: int = Field(default=60, ge=1)

    outbox_relay_id: str = "atlas-rag-outbox-relay"
    outbox_relay_batch_size: int = Field(default=10, ge=1, le=100)
    outbox_relay_poll_interval_seconds: float = Field(default=2.0, gt=0.0)
    outbox_relay_retry_delay_seconds: int = Field(default=30, ge=0)

    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = True
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
