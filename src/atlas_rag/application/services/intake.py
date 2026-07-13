from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.outbox_contracts import (
    INGESTION_JOB_AGGREGATE_TYPE,
    INGESTION_JOB_QUEUED_TOPIC,
    IngestionJobQueuedPayload,
)
from atlas_rag.application.services.outbox import append_outbox_message, capture_trace_context
from atlas_rag.domain.enums import DocumentVersionStatus, IngestionJobStatus, SourceType
from atlas_rag.domain.errors import ConflictError
from atlas_rag.infrastructure.db.models import (
    Document,
    DocumentVersion,
    IngestionJob,
    IngestionJobEvent,
)
from atlas_rag.infrastructure.object_store import (
    ObjectStore,
    object_uri,
    raw_source_object_key,
)


@dataclass(slots=True)
class IntakeRecord:
    document: Document
    version: DocumentVersion
    job: IngestionJob
    version_number: int
    created: bool


async def create_upload_intake(
    session: AsyncSession,
    *,
    object_store: ObjectStore,
    bucket: str,
    tenant_id: UUID,
    title: str,
    external_id: str | None,
    idempotency_key: str,
    data: bytes,
    content_type: str,
    original_filename: str | None,
) -> IntakeRecord:
    content_hash = _content_hash(data)
    source_metadata: dict[str, object] = {
        "content_type": content_type,
        "original_filename": original_filename,
        "size_bytes": len(data),
        "type": SourceType.UPLOAD.value,
    }
    version_metadata = _version_metadata(
        title=title,
        external_id=external_id,
        source=source_metadata,
    )
    object_metadata = {
        "content-hash": content_hash,
        "content-type": content_type,
        "size-bytes": str(len(data)),
        "source-type": SourceType.UPLOAD.value,
    }
    if original_filename is not None:
        object_metadata["original-filename"] = original_filename

    return await _create_materialized_intake(
        session,
        object_store=object_store,
        bucket=bucket,
        tenant_id=tenant_id,
        title=title,
        source_type=SourceType.UPLOAD,
        source_uri=None,
        external_id=external_id,
        idempotency_key=idempotency_key,
        data=data,
        content_type=content_type,
        content_hash=content_hash,
        version_metadata=version_metadata,
        object_metadata=object_metadata,
    )


async def create_url_intake(
    session: AsyncSession,
    *,
    object_store: ObjectStore,
    bucket: str,
    tenant_id: UUID,
    title: str,
    source_url: str,
    external_id: str | None,
    idempotency_key: str,
    data: bytes,
    content_type: str,
    final_url: str,
) -> IntakeRecord:
    content_hash = _content_hash(data)
    source_metadata = {
        "content_type": content_type,
        "final_url": final_url,
        "size_bytes": len(data),
        "type": SourceType.URL.value,
        "url": source_url,
    }
    version_metadata = _version_metadata(
        title=title,
        external_id=external_id,
        source=source_metadata,
    )
    object_metadata = {
        "content-hash": content_hash,
        "content-type": content_type,
        "final-url": final_url,
        "size-bytes": str(len(data)),
        "source-type": SourceType.URL.value,
        "source-url": source_url,
    }

    return await _create_materialized_intake(
        session,
        object_store=object_store,
        bucket=bucket,
        tenant_id=tenant_id,
        title=title,
        source_type=SourceType.URL,
        source_uri=source_url,
        external_id=external_id,
        idempotency_key=idempotency_key,
        data=data,
        content_type=content_type,
        content_hash=content_hash,
        version_metadata=version_metadata,
        object_metadata=object_metadata,
    )


async def _create_materialized_intake(
    session: AsyncSession,
    *,
    object_store: ObjectStore,
    bucket: str,
    tenant_id: UUID,
    title: str,
    source_type: SourceType,
    source_uri: str | None,
    external_id: str | None,
    idempotency_key: str,
    data: bytes,
    content_type: str,
    content_hash: str,
    version_metadata: dict[str, object],
    object_metadata: dict[str, str],
) -> IntakeRecord:
    existing = await _find_existing_intake(
        session,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        _ensure_replay_matches(
            existing,
            title=title,
            source_type=source_type,
            source_uri=source_uri,
            external_id=external_id,
            content_hash=content_hash,
            version_metadata=version_metadata,
        )
        return IntakeRecord(
            document=existing[0],
            version=existing[1],
            job=existing[2],
            version_number=existing[1].version_number,
            created=False,
        )

    document_id = uuid4()
    version_id = uuid4()
    uri = object_uri(
        bucket,
        raw_source_object_key(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
        ),
    )
    await object_store.put_bytes(
        uri,
        data,
        content_type=content_type,
        metadata=object_metadata,
    )

    try:
        async with session.begin_nested():
            document = Document(
                id=document_id,
                tenant_id=tenant_id,
                title=title,
                source_type=source_type,
                source_uri=source_uri,
                external_id=external_id,
                next_version_number=2,
            )
            session.add(document)

            version = DocumentVersion(
                id=version_id,
                document_id=document.id,
                version_number=1,
                status=DocumentVersionStatus.PENDING,
                content_hash=content_hash,
                object_uri=uri,
                metadata_=version_metadata,
            )
            session.add(version)
            await session.flush()

            job = IngestionJob(
                tenant_id=tenant_id,
                document_id=document.id,
                document_version_id=version.id,
                status=IngestionJobStatus.QUEUED,
                idempotency_key=idempotency_key,
            )
            session.add(job)
            await session.flush()

            session.add(
                IngestionJobEvent(
                    job_id=job.id,
                    event_type="job.queued",
                    from_status=None,
                    to_status=IngestionJobStatus.QUEUED,
                    details={"document_version": 1},
                    created_at=datetime.now(UTC),
                )
            )
            await session.flush()

            trace_context = capture_trace_context()
            payload = IngestionJobQueuedPayload(
                tenant_id=str(tenant_id),
                document_id=str(document.id),
                document_version_id=str(version.id),
                ingestion_job_id=str(job.id),
                idempotency_key=idempotency_key,
                source_type=document.source_type.value,
                source_uri=document.source_uri,
                trace_context=trace_context,
            )
            await append_outbox_message(
                session,
                tenant_id=tenant_id,
                topic=INGESTION_JOB_QUEUED_TOPIC,
                aggregate_type=INGESTION_JOB_AGGREGATE_TYPE,
                aggregate_id=job.id,
                payload=dict(payload),
                headers=trace_context,
            )
    except IntegrityError as exc:
        existing = await _find_existing_intake(
            session,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            raise ConflictError(
                "A document with this external_id already exists for the tenant."
            ) from exc
        _ensure_replay_matches(
            existing,
            title=title,
            source_type=source_type,
            source_uri=source_uri,
            external_id=external_id,
            content_hash=content_hash,
            version_metadata=version_metadata,
        )
        return IntakeRecord(
            document=existing[0],
            version=existing[1],
            job=existing[2],
            version_number=existing[1].version_number,
            created=False,
        )

    await session.refresh(document)
    await session.refresh(version)
    await session.refresh(job)
    return IntakeRecord(
        document=document,
        version=version,
        job=job,
        version_number=version.version_number,
        created=True,
    )


async def _find_existing_intake(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    idempotency_key: str,
) -> tuple[Document, DocumentVersion, IngestionJob] | None:
    row = (
        await session.execute(
            select(Document, DocumentVersion, IngestionJob)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .join(IngestionJob, IngestionJob.document_version_id == DocumentVersion.id)
            .where(
                IngestionJob.tenant_id == tenant_id,
                IngestionJob.idempotency_key == idempotency_key,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return row[0], row[1], row[2]


def _ensure_replay_matches(
    existing: tuple[Document, DocumentVersion, IngestionJob],
    *,
    title: str,
    source_type: SourceType,
    source_uri: str | None,
    external_id: str | None,
    content_hash: str,
    version_metadata: dict[str, object],
) -> None:
    document, version, _job = existing
    if (
        document.title != title
        or document.source_type != source_type
        or document.source_uri != source_uri
        or document.external_id != external_id
        or version.content_hash != content_hash
        or version.metadata_ != version_metadata
    ):
        raise ConflictError(
            "This idempotency key was already used for different intake content."
        )


def _content_hash(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def _version_metadata(
    *,
    title: str,
    external_id: str | None,
    source: dict[str, object],
) -> dict[str, object]:
    return {
        "intake": {
            "external_id": external_id,
            "title": title,
        },
        "source": source,
    }
