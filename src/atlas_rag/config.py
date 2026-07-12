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
