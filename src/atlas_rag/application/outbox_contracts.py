from typing import TypedDict

INGESTION_JOB_QUEUED_TOPIC = "ingestion.job_queued"
INGESTION_JOB_AGGREGATE_TYPE = "ingestion_job"


class IngestionJobQueuedPayload(TypedDict):
    tenant_id: str
    document_id: str
    document_version_id: str
    ingestion_job_id: str
    idempotency_key: str
    source_type: str
    source_uri: str | None
    trace_context: dict[str, str]


class IngestionFailurePayload(TypedDict):
    payload: IngestionJobQueuedPayload
    error_code: str
    error_message: str
