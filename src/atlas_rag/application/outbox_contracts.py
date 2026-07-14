from typing import Literal, NotRequired, TypedDict

INGESTION_JOB_QUEUED_TOPIC = "ingestion.job_queued"
INGESTION_JOB_CANCELLED_TOPIC = "ingestion.job_cancelled"
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


class IngestionJobCancelledPayload(TypedDict):
    tenant_id: str
    document_id: str
    document_version_id: str
    ingestion_job_id: str
    idempotency_key: str
    trace_context: dict[str, str]


class IngestionFailurePayload(TypedDict):
    payload: IngestionJobQueuedPayload
    error_code: str
    error_message: str


class IndexDocumentVersionPayload(TypedDict):
    tenant_id: str
    document_id: str
    document_version_id: str
    retrieval_index_version_id: str
    source: Literal["ingestion", "backfill", "manual"]


class PreparedDocumentIndexingPayload(TypedDict):
    mode: Literal["disabled", "optional", "required"]
    should_index: bool
    payload: NotRequired[IndexDocumentVersionPayload]


class IndexDocumentBatchPayload(IndexDocumentVersionPayload):
    batch_index: int


class DocumentIndexingFailurePayload(TypedDict):
    payload: IndexDocumentVersionPayload
    error_code: str
    error_message: str
