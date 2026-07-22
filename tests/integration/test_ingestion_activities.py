from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.chunking import ChunkingConfig
from flint_graph.application.extraction_proposals import (
    EvidenceProposal,
    ExtractedClaimProposal,
    ExtractedEntityProposal,
    ExtractedRelationProposal,
    ExtractionBatch,
    ExtractionBatchRequest,
)
from flint_graph.application.outbox_contracts import IngestionJobQueuedPayload
from flint_graph.application.parsing import BoundedParserRunner, ParserLimits
from flint_graph.application.services.documents import create_document
from flint_graph.application.services.extraction import ExtractionServiceConfig
from flint_graph.application.services.ingestion_jobs import create_ingestion_job
from flint_graph.application.services.intake import create_upload_intake
from flint_graph.application.services.staged_resolution import resolve_pending_staged_entities
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import (
    DocumentVersionStatus,
    EntityStatus,
    EntityType,
    ExtractionRunStatus,
    IngestionJobStatus,
    SourceType,
    StagedResolutionStatus,
)
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    DocumentArtifact,
    DocumentChunk,
    DocumentVersion,
    EntityAlias,
    EntityRelationship,
    EntityResolutionCandidate,
    ExtractedEntity,
    ExtractionRun,
    IngestionJob,
    IngestionJobEvent,
)
from flint_graph.infrastructure.object_store import ObjectInfo
from flint_graph.worker.activities.ingestion import (
    _proposal_model_from_settings,
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


class FakeProposalExtractionModel:
    def __init__(
        self,
        batch: ExtractionBatch | None = None,
        error: Exception | None = None,
    ) -> None:
        self.batch = batch
        self.error = error
        self.requests: list[ExtractionBatchRequest] = []

    async def extract_batch(self, request: ExtractionBatchRequest) -> ExtractionBatch:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.batch is not None
        return self.batch


async def _create_upload_payload(
    db_session: AsyncSession,
    *,
    store: FakeObjectStore,
    idempotency_key: str,
    data: bytes = b"# Pipeline\n\nFlintGraph parses and chunks content.",
) -> IngestionJobQueuedPayload:
    tenant = await create_tenant(db_session, name=f"Pipeline Tenant {idempotency_key}")
    intake = await create_upload_intake(
        db_session,
        object_store=store,
        bucket="flint-graph",
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


def _success_proposal_model() -> FakeProposalExtractionModel:
    return FakeProposalExtractionModel(
        batch=ExtractionBatch(
            input_chunk_ids=["chunk-000001"],
            entities=[
                ExtractedEntityProposal(
                    local_id="e1",
                    name="Acme Corporation",
                    entity_type="organization",
                    aliases=["Acme"],
                    confidence=0.95,
                    evidence=[
                        EvidenceProposal(
                            chunk_id="chunk-000001",
                            quote="Acme Corporation",
                        )
                    ],
                ),
                ExtractedEntityProposal(
                    local_id="e2",
                    name="Berlin",
                    entity_type="place",
                    confidence=0.9,
                    evidence=[
                        EvidenceProposal(chunk_id="chunk-000001", quote="Berlin")
                    ],
                ),
            ],
            relations=[
                ExtractedRelationProposal(
                    local_id="r1",
                    subject_entity_id="e1",
                    predicate="headquartered_in",
                    object_entity_id="e2",
                    confidence=0.88,
                    evidence=[
                        EvidenceProposal(
                            chunk_id="chunk-000001",
                            quote="Acme Corporation is headquartered in Berlin",
                        )
                    ],
                )
            ],
            claims=[
                ExtractedClaimProposal(
                    local_id="c1",
                    subject_entity_id="e1",
                    predicate="headquartered_in",
                    object_entity_id="e2",
                    confidence=0.86,
                    evidence=[
                        EvidenceProposal(
                            chunk_id="chunk-000001",
                            quote="Acme Corporation is headquartered in Berlin",
                        )
                    ],
                )
            ],
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


def test_ingestion_activity_supports_deterministic_provenance_provider() -> None:
    from flint_graph.application.extraction_proposals import DeterministicExtractionModel
    from flint_graph.config import Settings

    settings = Settings(llm_provider="deterministic")

    assert isinstance(_proposal_model_from_settings(settings), DeterministicExtractionModel)


async def test_ingestion_pipeline_persists_provenance_extracts_candidates_and_resolves_graph(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    payload = await _create_upload_payload(
        db_session,
        store=store,
        idempotency_key="pipeline-success",
        data=b"# Pipeline\n\nAcme Corporation is headquartered in Berlin.",
    )
    db_session.add(
        CanonicalEntity(
            tenant_id=UUID(payload["tenant_id"]),
            entity_type=EntityType.ORGANIZATION,
            canonical_name="Acme Corporation",
            normalized_name="acme corporation",
            status=EntityStatus.ACTIVE,
        )
    )
    await db_session.flush()

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await run_ingestion_pipeline_for_payload(
        db_session,
        payload,
        object_store=store,
        bucket="flint-graph",
        parser_runner=_parser_runner(),
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
        extraction_config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        extraction_model=_success_proposal_model(),
    )
    await mark_ingestion_job_completed_for_payload(db_session, payload)
    await resolve_pending_staged_entities(db_session, tenant_id=UUID(payload["tenant_id"]))

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
    run = await db_session.scalar(select(ExtractionRun))
    staged_entities = list(
        await db_session.scalars(select(ExtractedEntity).order_by(ExtractedEntity.local_id))
    )
    candidates = list(await db_session.scalars(select(EntityResolutionCandidate)))
    canonical_entities = list(
        await db_session.scalars(select(CanonicalEntity).order_by(CanonicalEntity.normalized_name))
    )
    relationship = await db_session.scalar(select(EntityRelationship))

    assert job is not None
    assert version is not None
    assert run is not None
    assert job.status == IngestionJobStatus.COMPLETED
    assert version.status == DocumentVersionStatus.ACTIVE
    assert [artifact.artifact_type for artifact in artifacts] == [
        "chunk_manifest",
        "normalized",
    ]
    assert [chunk.text for chunk in chunks] == [
        "Acme Corporation is headquartered in Berlin."
    ]
    assert run.status == ExtractionRunStatus.READY
    assert run.accepted_entity_count == 2
    assert run.accepted_relation_count == 1
    assert run.accepted_claim_count == 1
    assert run.manifest_uri in store.objects
    assert len(staged_entities) == 2
    assert {entity.resolution_status for entity in staged_entities} == {
        StagedResolutionStatus.RESOLVED
    }
    assert candidates
    assert {entity.normalized_name for entity in canonical_entities} == {
        "acme corporation",
        "berlin",
    }
    assert (await db_session.scalar(select(EntityAlias))) is not None
    assert relationship is not None
    assert relationship.predicate == "headquartered_in"
    assert relationship.support_count == 2


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
        bucket="flint-graph",
        parser_runner=_parser_runner(),
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
        extraction_config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        extraction_model=FakeProposalExtractionModel(
            error=RuntimeError("ollama unavailable")
        ),
    )
    await mark_ingestion_job_completed_for_payload(db_session, payload)

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    version = await db_session.get(DocumentVersion, UUID(payload["document_version_id"]))
    extraction_run = await db_session.scalar(select(ExtractionRun))

    assert job is not None
    assert version is not None
    assert extraction_run is not None
    assert job.status == IngestionJobStatus.COMPLETED
    assert version.status == DocumentVersionStatus.ACTIVE
    assert extraction_run.status == ExtractionRunStatus.FAILED
    assert extraction_run.errors[0]["message"] == "ollama unavailable"


async def test_ingestion_pipeline_persists_exception_type_for_blank_error_message(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    payload = await _create_upload_payload(
        db_session,
        store=store,
        idempotency_key="pipeline-optional-blank-error-message",
    )

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await run_ingestion_pipeline_for_payload(
        db_session,
        payload,
        object_store=store,
        bucket="flint-graph",
        parser_runner=_parser_runner(),
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
        extraction_config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        extraction_model=FakeProposalExtractionModel(error=TimeoutError()),
    )
    await mark_ingestion_job_completed_for_payload(db_session, payload)

    extraction_run = await db_session.scalar(select(ExtractionRun))

    assert extraction_run is not None
    assert extraction_run.status == ExtractionRunStatus.FAILED
    assert extraction_run.errors[0]["message"] == "TimeoutError"


async def test_ingestion_pipeline_optional_local_validation_failure_still_completes(
    db_session: AsyncSession,
) -> None:
    store = FakeObjectStore()
    payload = await _create_upload_payload(
        db_session,
        store=store,
        idempotency_key="pipeline-optional-local-validation-failure",
    )
    bad_batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Missing Quote",
                entity_type="other",
                evidence=[
                    EvidenceProposal(chunk_id="chunk-000001", quote="not in chunk")
                ],
            )
        ],
    )

    await mark_ingestion_job_running_for_payload(db_session, payload)
    await run_ingestion_pipeline_for_payload(
        db_session,
        payload,
        object_store=store,
        bucket="flint-graph",
        parser_runner=_parser_runner(),
        chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
        extraction_config=ExtractionServiceConfig(mode="optional", model="gemma3:1b"),
        extraction_model=FakeProposalExtractionModel(batch=bad_batch),
    )
    await mark_ingestion_job_completed_for_payload(db_session, payload)

    job = await db_session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
    extraction_run = await db_session.scalar(select(ExtractionRun))

    assert job is not None
    assert extraction_run is not None
    assert job.status == IngestionJobStatus.COMPLETED
    assert extraction_run.status == ExtractionRunStatus.FAILED
    assert extraction_run.errors[0]["message"] == (
        "evidence quote was not found in chunk text"
    )


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
            bucket="flint-graph",
            parser_runner=_parser_runner(),
            chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
            extraction_config=ExtractionServiceConfig(mode="required", model="gemma3:1b"),
            extraction_model=FakeProposalExtractionModel(error=RuntimeError("bad response")),
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
    extraction_run = await db_session.scalar(select(ExtractionRun))

    assert job is not None
    assert version is not None
    assert extraction_run is not None
    assert job.status == IngestionJobStatus.FAILED
    assert version.status == DocumentVersionStatus.FAILED
    assert job.error_message == "required extraction failed"
    assert extraction_run.status == ExtractionRunStatus.FAILED


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
            bucket="flint-graph",
            parser_runner=_parser_runner(),
            chunking_config=ChunkingConfig(max_chunk_chars=200, overlap_chars=24),
            extraction_config=ExtractionServiceConfig(enabled=False),
            extraction_model=_success_proposal_model(),
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
