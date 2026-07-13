import json
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.chunking import ChunkingConfig
from atlas_rag.application.outbox_contracts import IngestionJobQueuedPayload
from atlas_rag.application.parsing import BoundedParserRunner, ParserLimits
from atlas_rag.application.services.documents import create_document
from atlas_rag.application.services.extraction import ExtractionServiceConfig
from atlas_rag.application.services.ingestion_jobs import create_ingestion_job
from atlas_rag.application.services.intake import create_upload_intake
from atlas_rag.application.services.tenants import create_tenant
from atlas_rag.domain.enums import DocumentVersionStatus, IngestionJobStatus, SourceType
from atlas_rag.infrastructure.db.models import (
    DocumentArtifact,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    IngestionJobEvent,
)
from atlas_rag.infrastructure.object_store import ObjectInfo
from atlas_rag.worker.activities.ingestion import (
    mark_ingestion_job_completed_for_payload,
    mark_ingestion_job_failed_for_payload,
    mark_ingestion_job_running_for_payload,
    run_ingestion_pipeline_for_payload,
)


async def _create_payload(
    db_session: AsyncSession,
    *,
    idempotency_key: str = "activity-job",
) -> IngestionJobQueuedPayload:
    tenant = await create_tenant(db_session, name=f"Activity Tenant {idempotency_key}")
    document = await create_document(
        db_session,
        tenant_id=tenant.id,
        title="Activity Document",
        source_type=SourceType.URL,
        source_uri="https://example.test/activity",
        external_id=f"activity-document-{idempotency_key}",
    )
    record = await create_ingestion_job(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        idempotency_key=idempotency_key,
    )
    return {
        "tenant_id": str(tenant.id),
        "document_id": str(document.id),
        "document_version_id": str(record.job.document_version_id),
        "ingestion_job_id": str(record.job.id),
        "idempotency_key": idempotency_key,
        "source_type": document.source_type.value,
        "source_uri": document.source_uri,
        "trace_context": {},
    }


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.content_types: dict[str, str] = {}

    async def put_bytes(
        self,
        uri: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.objects[uri] = data
        self.content_types[uri] = content_type
        self.metadata[uri] = dict(metadata or {})

    async def get_bytes(self, uri: str) -> bytes:
        return self.objects[uri]

    async def head_object(self, uri: str) -> ObjectInfo:
        return ObjectInfo(
            size_bytes=len(self.objects[uri]),
            content_type=self.content_types[uri],
            metadata=self.metadata[uri],
        )


class FakeExtractionClient:
    def __init__(self, response: str | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    async def extract(
        self,
        *,
        prompt: str,
        model: str,
        timeout_seconds: int,
    ) -> str:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


async def _create_upload_payload(
    db_session: AsyncSession,
    *,
    store: FakeObjectStore,
    idempotency_key: str,
    data: bytes = b"# Pipeline\n\nAtlasRAG parses and chunks content.",
) -> IngestionJobQueuedPayload:
    tenant = await create_tenant(db_session, name=f"Pipeline Tenant {idempotency_key}")
    intake = await create_upload_intake(
        db_session,
        object_store=store,
        bucket="atlas-rag",
        tenant_id=tenant.id,
        title="Pipeline",
        external_id=f"pipeline-{idempotency_key}",
        idempotency_key=idempotency_key,
        data=data,
        content_type="text/markdown",
        original_filename="pipeline.md",
    )
    return {
        "tenant_id": str(tenant.id),
        "document_id": str(intake.document.id),
        "document_version_id": str(intake.version.id),
        "ingestion_job_id": str(intake.job.id),
        "idempotency_key": idempotency_key,
        "source_type": intake.document.source_type.value,
        "source_uri": intake.document.source_uri,
        "trace_context": {},
    }


def _parser_runner() -> BoundedParserRunner:
    return BoundedParserRunner(
        limits=ParserLimits(
            timeout_seconds=10,
            max_raw_bytes=1024 * 1024,
            max_normalized_bytes=1024 * 1024,
            max_elements=100,
        )
    )


def _success_extraction_client() -> FakeExtractionClient:
    return FakeExtractionClient(
        response=json.dumps(
            {
                "title": "Pipeline",
                "summary": "AtlasRAG parses and chunks content.",
                "topics": ["pipeline"],
                "entities": [{"name": "AtlasRAG", "type": "concept"}],
            }
        )
    )


async def test_ingestion_activity_helpers_mark_job_completed(
    db_session: AsyncSession,
) -> None:
    payload = await _create_payload(db_session)

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await mark_ingestion_job_completed_for_payload(db_session, payload)

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    assert job is not None
    events = list(
        await db_session.scalars(
            select(IngestionJobEvent).where(IngestionJobEvent.job_id == job.id)
        )
    )

    assert job.status == IngestionJobStatus.COMPLETED
    assert job.started_at is not None
    assert job.completed_at is not None
    assert [event.event_type for event in events] == [
        "job.queued",
        "job.started",
        "job.completed",
    ]


async def test_ingestion_activity_helpers_mark_job_failed(
    db_session: AsyncSession,
) -> None:
    payload = await _create_payload(db_session, idempotency_key="activity-failed-job")

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await mark_ingestion_job_failed_for_payload(
        db_session,
        {
            "payload": payload,
            "error_code": "ingestion_failed",
            "error_message": "pipeline failed",
        },
    )

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    assert job is not None

    assert job.status == IngestionJobStatus.FAILED
    assert job.completed_at is not None
    assert job.error_code == "ingestion_failed"
    assert job.error_message == "pipeline failed"


async def test_ingestion_pipeline_parses_chunks_extracts_and_completes_version(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    payload = await _create_upload_payload(
        db_session,
        store=store,
        idempotency_key="pipeline-success",
    )

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await run_ingestion_pipeline_for_payload(
        db_session,
        payload,
        object_store=store,
        bucket="atlas-rag",
        parser_runner=_parser_runner(),
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
        extraction_config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        extraction_client=_success_extraction_client(),
    )
    await mark_ingestion_job_completed_for_payload(db_session, payload)

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    version = await db_session.get(DocumentVersion, UUID(payload["document_version_id"]))
    artifacts = list(
        await db_session.scalars(
            select(DocumentArtifact).order_by(DocumentArtifact.artifact_type)
        )
    )
    chunks = list(
        await db_session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index))
    )

    assert job is not None
    assert version is not None
    assert job.status == IngestionJobStatus.COMPLETED
    assert version.status == DocumentVersionStatus.ACTIVE
    assert [artifact.artifact_type for artifact in artifacts] == [
        "chunk_manifest",
        "extraction",
        "normalized",
    ]
    assert [chunk.text for chunk in chunks] == ["AtlasRAG parses and chunks content."]
    extraction_artifact = next(
        artifact for artifact in artifacts if artifact.artifact_type == "extraction"
    )
    assert extraction_artifact.metadata_["status"] == "succeeded"
    extraction_payload = json.loads(store.objects[extraction_artifact.object_uri])
    assert extraction_payload["extraction"]["summary"] == (
        "AtlasRAG parses and chunks content."
    )


async def test_ingestion_pipeline_optional_extraction_failure_still_completes(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    payload = await _create_upload_payload(
        db_session,
        store=store,
        idempotency_key="pipeline-optional-extraction-failure",
    )

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await run_ingestion_pipeline_for_payload(
        db_session,
        payload,
        object_store=store,
        bucket="atlas-rag",
        parser_runner=_parser_runner(),
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
        extraction_config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        extraction_client=FakeExtractionClient(error=RuntimeError("ollama unavailable")),
    )
    await mark_ingestion_job_completed_for_payload(db_session, payload)

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    version = await db_session.get(DocumentVersion, UUID(payload["document_version_id"]))
    extraction_artifact = await db_session.scalar(
        select(DocumentArtifact).where(DocumentArtifact.artifact_type == "extraction")
    )

    assert job is not None
    assert version is not None
    assert extraction_artifact is not None
    assert job.status == IngestionJobStatus.COMPLETED
    assert version.status == DocumentVersionStatus.ACTIVE
    assert extraction_artifact.metadata_["status"] == "failed"
    assert extraction_artifact.metadata_["error_message"] == "ollama unavailable"


async def test_ingestion_pipeline_required_extraction_failure_fails_version(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    payload = await _create_upload_payload(
        db_session,
        store=store,
        idempotency_key="pipeline-required-extraction-failure",
    )

    await mark_ingestion_job_running_for_payload(db_session, payload)
    try:
        await run_ingestion_pipeline_for_payload(
            db_session,
            payload,
            object_store=store,
            bucket="atlas-rag",
            parser_runner=_parser_runner(),
            chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
            extraction_config=ExtractionServiceConfig(mode="required", model="gemma3:1b"),
            extraction_client=FakeExtractionClient(error=RuntimeError("bad response")),
        )
    except RuntimeError as exc:
        await mark_ingestion_job_failed_for_payload(
            db_session,
            {
                "payload": payload,
                "error_code": "ingestion_failed",
                "error_message": str(exc),
            },
        )
    else:
        raise AssertionError("required extraction failure should fail ingestion")

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    version = await db_session.get(DocumentVersion, UUID(payload["document_version_id"]))
    extraction_artifact = await db_session.scalar(
        select(DocumentArtifact).where(DocumentArtifact.artifact_type == "extraction")
    )

    assert job is not None
    assert version is not None
    assert extraction_artifact is not None
    assert job.status == IngestionJobStatus.FAILED
    assert version.status == DocumentVersionStatus.FAILED
    assert job.error_message == "required extraction failed"
    assert extraction_artifact.metadata_["status"] == "failed"


async def test_ingestion_pipeline_rejects_raw_content_hash_mismatch(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    payload = await _create_upload_payload(
        db_session,
        store=store,
        idempotency_key="pipeline-hash-mismatch",
    )
    version = await db_session.get(DocumentVersion, UUID(payload["document_version_id"]))
    assert version is not None
    assert version.object_uri is not None
    store.objects[version.object_uri] = b"tampered"

    await mark_ingestion_job_running_for_payload(db_session, payload)

    try:
        await run_ingestion_pipeline_for_payload(
            db_session,
            payload,
            object_store=store,
            bucket="atlas-rag",
            parser_runner=_parser_runner(),
            chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
            extraction_config=ExtractionServiceConfig(enabled=False),
            extraction_client=_success_extraction_client(),
        )
    except RuntimeError as exc:
        await mark_ingestion_job_failed_for_payload(
            db_session,
            {
                "payload": payload,
                "error_code": "ingestion_failed",
                "error_message": str(exc),
            },
        )
    else:
        raise AssertionError("hash mismatch should fail ingestion")

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    version = await db_session.get(DocumentVersion, UUID(payload["document_version_id"]))
    artifacts = list(await db_session.scalars(select(DocumentArtifact)))

    assert job is not None
    assert version is not None
    assert job.status == IngestionJobStatus.FAILED
    assert version.status == DocumentVersionStatus.FAILED
    assert job.error_message == "raw source content hash mismatch"
    assert artifacts == []
