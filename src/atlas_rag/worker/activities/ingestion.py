from __future__ import annotations

from asyncio import to_thread
from hashlib import sha256
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio import activity

from atlas_rag.application.chunking import ChunkingConfig
from atlas_rag.application.outbox_contracts import (
    IngestionFailurePayload,
    IngestionJobQueuedPayload,
)
from atlas_rag.application.parsing import BoundedParserRunner, ParserLimits, SourceMetadata
from atlas_rag.application.services.content_artifacts import persist_content_artifacts
from atlas_rag.application.services.extraction import (
    ExtractionServiceConfig,
    StructuredExtractionClient,
    persist_extraction_artifact,
)
from atlas_rag.application.services.job_transitions import transition_ingestion_job
from atlas_rag.application.services.mentions import persist_mentions_and_claims
from atlas_rag.config import Settings, get_settings
from atlas_rag.domain.enums import IngestionJobStatus
from atlas_rag.infrastructure.db.models import Document, DocumentVersion
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.infrastructure.object_store import ObjectStore, create_object_store
from atlas_rag.infrastructure.ollama import OllamaExtractionClient
from atlas_rag.workflows.ingestion import (
    MARK_JOB_CANCELLED_ACTIVITY,
    MARK_JOB_COMPLETED_ACTIVITY,
    MARK_JOB_FAILED_ACTIVITY,
    MARK_JOB_RUNNING_ACTIVITY,
    RUN_INGESTION_PIPELINE_ACTIVITY,
)


class RequiredExtractionFailedError(RuntimeError):
    pass


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
    extraction_client: StructuredExtractionClient,
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
    extraction_result = await persist_extraction_artifact(
        session,
        object_store=object_store,
        bucket=bucket,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        chunk_manifest=persisted_artifacts.chunk_manifest,
        config=extraction_config,
        client=extraction_client,
    )
    await persist_mentions_and_claims(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        extraction=extraction_result.extraction,
        source_artifact_id=extraction_result.extraction_artifact_id,
        prompt_hash=extraction_result.prompt_hash,
        response_hash=extraction_result.response_hash,
    )
    if extraction_result.blocks_version_activation:
        raise RequiredExtractionFailedError("required extraction failed")


@activity.defn(name=RUN_INGESTION_PIPELINE_ACTIVITY)
async def run_ingestion_pipeline(payload: IngestionJobQueuedPayload) -> None:
    settings = get_settings()
    object_store = create_object_store(settings)
    parser_runner = _parser_runner_from_settings(settings)
    chunking_config = _chunking_config_from_settings(settings)
    extraction_config = _extraction_config_from_settings(settings)
    async with httpx.AsyncClient(base_url=settings.ollama_base_url) as http_client:
        extraction_client = OllamaExtractionClient(http_client=http_client)
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
                    extraction_client=extraction_client,
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
