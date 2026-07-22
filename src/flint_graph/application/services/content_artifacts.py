from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.chunking import (
    ChunkingConfig,
    DocumentChunkManifest,
    chunk_normalized_document,
)
from flint_graph.application.parsing import NormalizedDocument
from flint_graph.domain.enums import DocumentArtifactType
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentArtifact,
    DocumentChunk,
    DocumentVersion,
)
from flint_graph.infrastructure.object_store import ObjectStore, artifact_object_key, object_uri


@dataclass(slots=True, frozen=True)
class PersistedContentArtifacts:
    normalized_artifact_uri: str
    chunk_manifest_uri: str
    chunk_count: int
    chunk_manifest: DocumentChunkManifest


async def persist_content_artifacts(
    session: AsyncSession,
    *,
    object_store: ObjectStore,
    bucket: str,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    normalized_document: NormalizedDocument,
    chunking_config: ChunkingConfig,
) -> PersistedContentArtifacts:
    await _ensure_version_exists(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    )
    manifest = chunk_normalized_document(normalized_document, config=chunking_config)

    normalized_bytes = _json_bytes(normalized_document)
    manifest_bytes = _json_bytes(manifest)
    normalized_uri = object_uri(
        bucket,
        artifact_object_key(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            artifact_name="normalized.json",
        ),
    )
    manifest_uri = object_uri(
        bucket,
        artifact_object_key(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            artifact_name="chunks.json",
        ),
    )

    normalized_hash = _content_hash(normalized_bytes)
    manifest_hash = _content_hash(manifest_bytes)
    await object_store.put_bytes(
        normalized_uri,
        normalized_bytes,
        content_type="application/json",
        metadata={
            "artifact-type": DocumentArtifactType.NORMALIZED.value,
            "content-hash": normalized_hash,
            "schema-version": normalized_document.schema_version,
        },
    )
    await object_store.put_bytes(
        manifest_uri,
        manifest_bytes,
        content_type="application/json",
        metadata={
            "artifact-type": DocumentArtifactType.CHUNK_MANIFEST.value,
            "content-hash": manifest_hash,
            "schema-version": manifest.schema_version,
        },
    )

    await _replace_artifact_rows(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        normalized_uri=normalized_uri,
        normalized_hash=normalized_hash,
        normalized_size=len(normalized_bytes),
        manifest_uri=manifest_uri,
        manifest_hash=manifest_hash,
        manifest_size=len(manifest_bytes),
        manifest=manifest,
        normalized_document=normalized_document,
    )

    return PersistedContentArtifacts(
        normalized_artifact_uri=normalized_uri,
        chunk_manifest_uri=manifest_uri,
        chunk_count=len(manifest.chunks),
        chunk_manifest=manifest,
    )


async def _ensure_version_exists(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> None:
    exists = await session.scalar(
        select(DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document_id,
            Document.tenant_id == tenant_id,
        )
    )
    if exists is None:
        raise NotFoundError(f"Document version '{version_id}' was not found.")


async def _replace_artifact_rows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    normalized_uri: str,
    normalized_hash: str,
    normalized_size: int,
    manifest_uri: str,
    manifest_hash: str,
    manifest_size: int,
    manifest: DocumentChunkManifest,
    normalized_document: NormalizedDocument,
) -> None:
    await session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_version_id == version_id)
    )
    await session.execute(
        delete(DocumentArtifact).where(
            DocumentArtifact.document_version_id == version_id,
            DocumentArtifact.artifact_type.in_(
                [
                    DocumentArtifactType.NORMALIZED,
                    DocumentArtifactType.CHUNK_MANIFEST,
                ]
            ),
        )
    )
    session.add_all(
        [
            DocumentArtifact(
                tenant_id=tenant_id,
                document_id=document_id,
                document_version_id=version_id,
                artifact_type=DocumentArtifactType.NORMALIZED,
                object_uri=normalized_uri,
                content_hash=normalized_hash,
                size_bytes=normalized_size,
                schema_version=normalized_document.schema_version,
                metadata_={"format": normalized_document.format.value},
            ),
            DocumentArtifact(
                tenant_id=tenant_id,
                document_id=document_id,
                document_version_id=version_id,
                artifact_type=DocumentArtifactType.CHUNK_MANIFEST,
                object_uri=manifest_uri,
                content_hash=manifest_hash,
                size_bytes=manifest_size,
                schema_version=manifest.schema_version,
                metadata_={"chunk_count": len(manifest.chunks)},
            ),
        ]
    )
    session.add_all(
        [
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                document_version_id=version_id,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                chunk_hash=chunk.chunk_hash,
                source_element_ids=chunk.source_element_ids,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                source_offsets=chunk.source_offsets,
                metadata_={"format": normalized_document.format.value},
            )
            for chunk in manifest.chunks
        ]
    )
    await session.flush()


def _json_bytes(payload: NormalizedDocument | DocumentChunkManifest) -> bytes:
    return payload.model_dump_json(exclude_none=True).encode("utf-8")


def _content_hash(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()
