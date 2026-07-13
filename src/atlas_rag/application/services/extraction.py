from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.chunking import DocumentChunkManifest
from atlas_rag.application.extraction import (
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    ExtractedDocumentFacts,
    build_extraction_prompt,
    parse_extraction_response,
)
from atlas_rag.domain.enums import DocumentArtifactType
from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import Document, DocumentArtifact, DocumentVersion
from atlas_rag.infrastructure.object_store import ObjectStore, artifact_object_key, object_uri

ExtractionMode = Literal["disabled", "optional", "required"]
ExtractionStatus = Literal["succeeded", "failed", "skipped"]


class StructuredExtractionClient(Protocol):
    async def extract(
        self,
        *,
        prompt: str,
        model: str,
        timeout_seconds: int,
    ) -> str: ...


class ExtractionServiceConfig(BaseModel):
    enabled: bool = True
    mode: ExtractionMode = "optional"
    provider: Literal["ollama"] = "ollama"
    model: str = "gemma3:1b"
    timeout_seconds: int = Field(default=60, ge=1)
    prompt_version: str = EXTRACTION_PROMPT_VERSION


class ExtractionProvenance(BaseModel):
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    input_manifest_hash: str
    prompt_hash: str
    response_hash: str | None = None
    status: ExtractionStatus
    error_code: str | None = None
    error_message: str | None = None


class ExtractionArtifactPayload(BaseModel):
    schema_version: Literal["2"] = "2"
    source: dict[str, str]
    status: ExtractionStatus
    extraction: ExtractedDocumentFacts | None
    provenance: ExtractionProvenance


@dataclass(slots=True, frozen=True)
class PersistedExtractionArtifact:
    extraction_artifact_uri: str
    extraction_artifact_id: UUID
    status: ExtractionStatus
    blocks_version_activation: bool
    extraction: ExtractedDocumentFacts | None
    prompt_hash: str
    response_hash: str | None


async def persist_extraction_artifact(
    session: AsyncSession,
    *,
    object_store: ObjectStore,
    bucket: str,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunk_manifest: DocumentChunkManifest,
    config: ExtractionServiceConfig,
    client: StructuredExtractionClient,
) -> PersistedExtractionArtifact:
    await _ensure_version_exists(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    )

    manifest_bytes = _json_bytes(chunk_manifest)
    input_manifest_hash = _content_hash(manifest_bytes)
    chunks = [(chunk.chunk_id, chunk.text) for chunk in chunk_manifest.chunks]
    prompt = build_extraction_prompt(chunks)
    prompt_hash = _content_hash(prompt.encode("utf-8"))

    response_text: str | None = None
    extraction: ExtractedDocumentFacts | None = None
    status: ExtractionStatus = "skipped"
    error_code: str | None = None
    error_message: str | None = None

    if config.enabled and config.mode != "disabled":
        try:
            response_text = await client.extract(
                prompt=prompt,
                model=config.model,
                timeout_seconds=config.timeout_seconds,
            )
            extraction = parse_extraction_response(response_text)
            status = "succeeded"
        except Exception as exc:
            status = "failed"
            error_code = "extraction_failed"
            error_message = str(exc)

    response_hash = (
        _content_hash(response_text.encode("utf-8")) if response_text is not None else None
    )
    provenance = ExtractionProvenance(
        provider=config.provider,
        model=config.model,
        prompt_version=config.prompt_version,
        schema_version=EXTRACTION_SCHEMA_VERSION,
        input_manifest_hash=input_manifest_hash,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        status=status,
        error_code=error_code,
        error_message=error_message,
    )
    payload = ExtractionArtifactPayload(
        source={
            "document_id": str(document_id),
            "document_version_id": str(version_id),
            "chunk_manifest_hash": input_manifest_hash,
        },
        status=status,
        extraction=extraction,
        provenance=provenance,
    )
    payload_bytes = _json_bytes(payload)
    extraction_hash = _content_hash(payload_bytes)
    extraction_uri = object_uri(
        bucket,
        artifact_object_key(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            artifact_name="extraction.json",
        ),
    )

    await object_store.put_bytes(
        extraction_uri,
        payload_bytes,
        content_type="application/json",
        metadata={
            "artifact-type": DocumentArtifactType.EXTRACTION.value,
            "content-hash": extraction_hash,
            "schema-version": payload.schema_version,
            "status": status,
        },
    )
    extraction_artifact_id = await _replace_extraction_artifact_row(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        extraction_uri=extraction_uri,
        extraction_hash=extraction_hash,
        extraction_size=len(payload_bytes),
        provenance=provenance,
    )

    return PersistedExtractionArtifact(
        extraction_artifact_uri=extraction_uri,
        extraction_artifact_id=extraction_artifact_id,
        status=status,
        blocks_version_activation=status == "failed" and config.mode == "required",
        extraction=extraction,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
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


async def _replace_extraction_artifact_row(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    extraction_uri: str,
    extraction_hash: str,
    extraction_size: int,
    provenance: ExtractionProvenance,
) -> UUID:
    await session.execute(
        delete(DocumentArtifact).where(
            DocumentArtifact.document_version_id == version_id,
            DocumentArtifact.artifact_type == DocumentArtifactType.EXTRACTION,
        )
    )
    artifact = DocumentArtifact(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=version_id,
        artifact_type=DocumentArtifactType.EXTRACTION,
        object_uri=extraction_uri,
        content_hash=extraction_hash,
        size_bytes=extraction_size,
        schema_version=EXTRACTION_SCHEMA_VERSION,
        metadata_=_provenance_metadata(provenance),
    )
    session.add(artifact)
    await session.flush()
    return artifact.id


def _provenance_metadata(provenance: ExtractionProvenance) -> dict[str, Any]:
    return provenance.model_dump(mode="json", exclude_none=True)


def _json_bytes(payload: BaseModel) -> bytes:
    return payload.model_dump_json().encode("utf-8")


def _content_hash(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()
