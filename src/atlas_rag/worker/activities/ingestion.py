from __future__ import annotations

from asyncio import to_thread
from hashlib import sha256
from time import perf_counter
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

from atlas_rag.application.chunking import ChunkingConfig
from atlas_rag.application.extraction_proposals import (
    DeterministicExtractionModel,
    ExtractionBatchRequest,
    ExtractionInputChunk,
    StructuredExtractionModel,
)
from atlas_rag.application.outbox_contracts import (
    IngestionFailurePayload,
    IngestionJobQueuedPayload,
)
from atlas_rag.application.parsing import BoundedParserRunner, ParserLimits, SourceMetadata
from atlas_rag.application.services.content_artifacts import persist_content_artifacts
from atlas_rag.application.services.extraction import (
    ExtractionServiceConfig,
)
from atlas_rag.application.services.job_transitions import transition_ingestion_job
from atlas_rag.application.services.proposal_candidate_generation import (
    generate_proposal_candidates_for_run,
)
from atlas_rag.application.services.provenance_extraction import (
    ProvenanceExtractionMetadata,
    persist_failed_provenance_extraction_run,
    persist_provenance_extraction_run,
)
from atlas_rag.config import Settings, get_settings
from atlas_rag.domain.enums import IngestionJobStatus
from atlas_rag.infrastructure.db.models import Document, DocumentVersion
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.infrastructure.object_store import ObjectStore, create_object_store
from atlas_rag.infrastructure.ollama import OllamaProposalExtractionModel
from atlas_rag.workflows.ingestion import (
    MARK_JOB_CANCELLED_ACTIVITY,
    MARK_JOB_COMPLETED_ACTIVITY,
    MARK_JOB_FAILED_ACTIVITY,
    MARK_JOB_RUNNING_ACTIVITY,
    RUN_INGESTION_PIPELINE_ACTIVITY,
)


class RequiredExtractionFailedError(RuntimeError):
    pass


PROVENANCE_EXTRACTION_PROMPT_VERSION = "proposal-v1"
PROVENANCE_EXTRACTOR_VERSION = "structured-proposal-v1"


def _tenant_id(payload: IngestionJobQueuedPayload) -> UUID:
    return UUID(payload["tenant_id"])


def _job_id(payload: IngestionJobQueuedPayload) -> UUID:
    return UUID(payload["ingestion_job_id"])


async def mark_ingestion_job_running_for_payload(
    session: AsyncSession,
    payload: IngestionJobQueuedPayload,
) -> None:
    await transition_ingestion_job(
        session,
        tenant_id=_tenant_id(payload),
        job_id=_job_id(payload),
        target_status=IngestionJobStatus.RUNNING,
        event_type="job.started",
        details={"worker": "temporal"},
        expected_current_statuses={IngestionJobStatus.QUEUED},
    )


async def mark_ingestion_job_completed_for_payload(
    session: AsyncSession,
    payload: IngestionJobQueuedPayload,
) -> None:
    await transition_ingestion_job(
        session,
        tenant_id=_tenant_id(payload),
        job_id=_job_id(payload),
        target_status=IngestionJobStatus.COMPLETED,
        event_type="job.completed",
        details={"mode": "pipeline"},
        expected_current_statuses={IngestionJobStatus.RUNNING},
    )


async def mark_ingestion_job_failed_for_payload(
    session: AsyncSession,
    failure: IngestionFailurePayload,
) -> None:
    payload = failure["payload"]
    await transition_ingestion_job(
        session,
        tenant_id=_tenant_id(payload),
        job_id=_job_id(payload),
        target_status=IngestionJobStatus.FAILED,
        event_type="job.failed",
        details={"mode": "pipeline"},
        error_code=failure["error_code"],
        error_message=failure["error_message"],
    )


async def mark_ingestion_job_cancelled_for_payload(
    session: AsyncSession,
    payload: IngestionJobQueuedPayload,
) -> None:
    await transition_ingestion_job(
        session,
        tenant_id=_tenant_id(payload),
        job_id=_job_id(payload),
        target_status=IngestionJobStatus.CANCELLED,
        event_type="job.cancelled",
        details={"requested_by": "temporal"},
        expected_current_statuses={
            IngestionJobStatus.QUEUED,
            IngestionJobStatus.RUNNING,
        },
    )


@activity.defn(name=MARK_JOB_RUNNING_ACTIVITY)
async def mark_ingestion_job_running(payload: IngestionJobQueuedPayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_ingestion_job_running_for_payload(session, payload)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def run_ingestion_pipeline_for_payload(
    session: AsyncSession,
    payload: IngestionJobQueuedPayload,
    *,
    object_store: ObjectStore,
    bucket: str,
    parser_runner: BoundedParserRunner,
    chunking_config: ChunkingConfig,
    extraction_config: ExtractionServiceConfig,
    extraction_model: StructuredExtractionModel,
    candidate_auto_threshold: float = 0.85,
    candidate_review_threshold: float = 0.6,
    candidate_limit: int = 20,
) -> None:
    tenant_id = _tenant_id(payload)
    document_id = UUID(payload["document_id"])
    version_id = UUID(payload["document_version_id"])
    version = await _get_document_version(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    )
    if version.object_uri is None:
        raise RuntimeError("document version has no raw object uri")
    if version.content_hash is None:
        raise RuntimeError("document version has no raw content hash")

    raw_source = await object_store.get_bytes(version.object_uri)
    if _content_hash(raw_source) != version.content_hash:
        raise RuntimeError("raw source content hash mismatch")

    source_metadata = _source_metadata(version, document_id=document_id, version_id=version_id)
    normalized_document = await to_thread(
        parser_runner.parse,
        raw_source,
        metadata=source_metadata,
    )
    persisted_artifacts = await persist_content_artifacts(
        session,
        object_store=object_store,
        bucket=bucket,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        normalized_document=normalized_document,
        chunking_config=chunking_config,
    )
    extraction_run_id = await _run_provenance_extraction(
        session,
        object_store=object_store,
        bucket=bucket,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        chunks=[
            ExtractionInputChunk(chunk_id=chunk.chunk_id, text=chunk.text)
            for chunk in persisted_artifacts.chunk_manifest.chunks
        ],
        config=extraction_config,
        extraction_model=extraction_model,
    )
    if extraction_run_id is not None:
        await generate_proposal_candidates_for_run(
            session,
            tenant_id=tenant_id,
            extraction_run_id=extraction_run_id,
            auto_threshold=candidate_auto_threshold,
            review_threshold=candidate_review_threshold,
            limit_per_source=candidate_limit,
        )


@activity.defn(name=RUN_INGESTION_PIPELINE_ACTIVITY)
async def run_ingestion_pipeline(payload: IngestionJobQueuedPayload) -> None:
    settings = get_settings()
    object_store = create_object_store(settings)
    parser_runner = _parser_runner_from_settings(settings)
    chunking_config = _chunking_config_from_settings(settings)
    extraction_config = _extraction_config_from_settings(settings)
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as http_client:
        extraction_model = _proposal_model_from_settings(
            settings, http_client=http_client
        )
        async with SessionFactory() as session:
            try:
                await run_ingestion_pipeline_for_payload(
                    session,
                    payload,
                    object_store=object_store,
                    bucket=settings.object_store_bucket,
                    parser_runner=parser_runner,
                    chunking_config=chunking_config,
                    extraction_config=extraction_config,
                    extraction_model=extraction_model,
                    candidate_auto_threshold=settings.entity_resolution_auto_threshold,
                    candidate_review_threshold=settings.entity_resolution_review_threshold,
                    candidate_limit=settings.entity_resolution_candidate_limit,
                )
                await session.commit()
            except RequiredExtractionFailedError:
                await session.commit()
                raise
            except Exception:
                await session.rollback()
                raise


@activity.defn(name=MARK_JOB_COMPLETED_ACTIVITY)
async def mark_ingestion_job_completed(payload: IngestionJobQueuedPayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_ingestion_job_completed_for_payload(session, payload)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_JOB_FAILED_ACTIVITY)
async def mark_ingestion_job_failed(failure: IngestionFailurePayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_ingestion_job_failed_for_payload(session, failure)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_JOB_CANCELLED_ACTIVITY)
async def mark_ingestion_job_cancelled(payload: IngestionJobQueuedPayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_ingestion_job_cancelled_for_payload(session, payload)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _get_document_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> DocumentVersion:
    version = await session.scalar(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == tenant_id,
            DocumentVersion.document_id == document_id,
            DocumentVersion.id == version_id,
        )
    )
    if version is None:
        raise RuntimeError("document version was not found")
    return version


def _source_metadata(
    version: DocumentVersion,
    *,
    document_id: UUID,
    version_id: UUID,
) -> SourceMetadata:
    source = version.metadata_.get("source")
    source_metadata = source if isinstance(source, dict) else {}
    content_type = _optional_string(source_metadata.get("content_type"))
    filename = _optional_string(
        source_metadata.get("original_filename")
        or source_metadata.get("final_url")
        or source_metadata.get("url")
    )
    content_hash = version.content_hash
    if content_hash is None:
        raise RuntimeError("document version has no raw content hash")
    return SourceMetadata(
        document_id=document_id,
        document_version_id=version_id,
        content_hash=content_hash,
        content_type=content_type,
        filename=filename,
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _content_hash(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def _parser_runner_from_settings(settings: Settings) -> BoundedParserRunner:
    return BoundedParserRunner(
        limits=ParserLimits(
            timeout_seconds=settings.parser_timeout_seconds,
            max_raw_bytes=settings.parser_max_raw_bytes,
            max_normalized_bytes=settings.parser_max_normalized_bytes,
            max_elements=settings.parser_max_elements,
        )
    )


def _chunking_config_from_settings(settings: Settings) -> ChunkingConfig:
    return ChunkingConfig(
        max_chunk_chars=settings.chunking_max_chunk_chars,
        overlap_chars=settings.chunking_overlap_chars,
    )


def _extraction_config_from_settings(settings: Settings) -> ExtractionServiceConfig:
    return ExtractionServiceConfig(
        enabled=settings.extraction_enabled,
        mode=settings.extraction_mode,
        provider=settings.llm_provider,
        model=settings.ollama_model,
        timeout_seconds=settings.extraction_timeout_seconds,
    )


def _proposal_model_from_settings(
    settings: Settings, *, http_client: httpx.AsyncClient | None = None
) -> StructuredExtractionModel:
    if settings.llm_provider == "deterministic":
        return DeterministicExtractionModel()
    return OllamaProposalExtractionModel(
        model=settings.ollama_model,
        timeout_seconds=settings.extraction_timeout_seconds,
        http_client=http_client,
        base_url=settings.ollama_base_url,
    )


async def _run_provenance_extraction(
    session: AsyncSession,
    *,
    object_store: ObjectStore,
    bucket: str,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunks: list[ExtractionInputChunk],
    config: ExtractionServiceConfig,
    extraction_model: StructuredExtractionModel,
) -> UUID | None:
    if not config.enabled or config.mode == "disabled":
        return None

    request = ExtractionBatchRequest(chunks=chunks)
    request_hash = _content_hash(request.model_dump_json().encode("utf-8"))
    metadata = ProvenanceExtractionMetadata(
        prompt_version=PROVENANCE_EXTRACTION_PROMPT_VERSION,
        extractor_version=PROVENANCE_EXTRACTOR_VERSION,
        model_provider=config.provider,
        model_name=config.model,
        request_hash=request_hash,
    )
    started = perf_counter()
    response_hash: str | None = None
    try:
        batch = await extraction_model.extract_batch(request)
        response_bytes = batch.model_dump_json(exclude_none=True).encode("utf-8")
        response_hash = _content_hash(response_bytes)
        result = await persist_provenance_extraction_run(
            session,
            object_store=object_store,
            bucket=bucket,
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            chunks=chunks,
            batch=batch,
            metadata=metadata.model_copy(
                update={
                    "response_hash": response_hash,
                    "latency_ms": _elapsed_ms(started),
                }
            ),
        )
        return result.extraction_run_id
    except Exception as exc:
        await persist_failed_provenance_extraction_run(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            chunks=chunks,
            metadata=metadata.model_copy(
                update={
                    "response_hash": response_hash,
                    "latency_ms": _elapsed_ms(started),
                }
            ),
            error_code="extraction_failed",
            error_message=_exception_message(exc),
        )
        if config.mode == "required":
            raise RequiredExtractionFailedError("required extraction failed") from exc
        return None


def _exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
