from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.entity_resolution import normalize_name
from atlas_rag.application.extraction_evidence import ResolvedBatchEvidence, resolve_batch_evidence
from atlas_rag.application.extraction_proposals import (
    ExtractionBatch,
    ExtractionInputChunk,
)
from atlas_rag.domain.enums import (
    EntityType,
    ExtractionInvocationStatus,
    ExtractionRunStatus,
    StagedProposalStatus,
)
from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import (
    Document,
    DocumentVersion,
    EvidenceSpan,
    ExtractedClaim,
    ExtractedClaimEvidence,
    ExtractedEntity,
    ExtractedEntityEvidence,
    ExtractedRelation,
    ExtractedRelationEvidence,
    ExtractionArtifact,
    ExtractionInvocation,
    ExtractionRun,
)
from atlas_rag.infrastructure.object_store import ObjectStore, artifact_object_key, object_uri

MANIFEST_SCHEMA_VERSION = "1"


class ProvenanceExtractionMetadata(BaseModel):
    prompt_version: str
    extractor_version: str
    model_provider: str
    model_name: str
    request_hash: str
    response_hash: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_token_count: int | None = Field(default=None, ge=0)
    completion_token_count: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, slots=True)
class PersistedProvenanceExtraction:
    extraction_run_id: UUID
    manifest_uri: str
    manifest_hash: str


async def persist_provenance_extraction_run(
    session: AsyncSession,
    *,
    object_store: ObjectStore,
    bucket: str,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunks: list[ExtractionInputChunk],
    batch: ExtractionBatch,
    metadata: ProvenanceExtractionMetadata,
) -> PersistedProvenanceExtraction:
    await _ensure_version_exists(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
    )
    input_hash = _input_hash(chunks)
    existing = await _find_ready_run(
        session,
        version_id=version_id,
        input_hash=input_hash,
        schema_version=batch.schema_version,
        prompt_version=metadata.prompt_version,
        extractor_version=metadata.extractor_version,
        model_name=metadata.model_name,
    )
    if existing is not None:
        assert existing.manifest_uri is not None
        assert existing.manifest_hash is not None
        return PersistedProvenanceExtraction(
            extraction_run_id=existing.id,
            manifest_uri=existing.manifest_uri,
            manifest_hash=existing.manifest_hash,
        )

    resolved_evidence = resolve_batch_evidence(batch, chunks=chunks)
    manifest = _manifest_payload(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        chunks=chunks,
        batch=batch,
        resolved_evidence=resolved_evidence,
        metadata=metadata,
        input_hash=input_hash,
    )
    manifest_bytes = manifest.model_dump_json(exclude_none=True).encode("utf-8")
    manifest_hash = _content_hash(manifest_bytes)
    manifest_uri = object_uri(
        bucket,
        artifact_object_key(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            artifact_name=f"extraction/{manifest_hash.removeprefix('sha256:')}.json",
        ),
    )

    await object_store.put_bytes(
        manifest_uri,
        manifest_bytes,
        content_type="application/json",
        metadata={
            "artifact-type": "provenance-extraction-manifest",
            "content-hash": manifest_hash,
            "schema-version": MANIFEST_SCHEMA_VERSION,
        },
    )

    run = ExtractionRun(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=version_id,
        status=ExtractionRunStatus.READY,
        schema_version=batch.schema_version,
        prompt_version=metadata.prompt_version,
        extractor_version=metadata.extractor_version,
        model_provider=metadata.model_provider,
        model_name=metadata.model_name,
        input_hash=input_hash,
        manifest_uri=manifest_uri,
        manifest_hash=manifest_hash,
        input_chunk_count=len(chunks),
        invocation_count=1,
        accepted_entity_count=len(batch.entities),
        accepted_relation_count=len(batch.relations),
        accepted_claim_count=len(batch.claims),
        quality_metrics={},
        warnings=[],
        errors=[],
    )
    session.add(run)
    await session.flush()

    session.add(
        ExtractionInvocation(
            tenant_id=tenant_id,
            extraction_run_id=run.id,
            invocation_index=0,
            status=ExtractionInvocationStatus.SUCCEEDED,
            input_chunk_ids=[chunk.chunk_id for chunk in chunks],
            request_hash=metadata.request_hash,
            response_hash=metadata.response_hash,
            latency_ms=metadata.latency_ms,
            input_char_count=sum(len(chunk.text) for chunk in chunks),
            output_char_count=len(batch.model_dump_json(exclude_none=True)),
            prompt_token_count=metadata.prompt_token_count,
            completion_token_count=metadata.completion_token_count,
        )
    )
    session.add(
        ExtractionArtifact(
            tenant_id=tenant_id,
            extraction_run_id=run.id,
            object_uri=manifest_uri,
            content_hash=manifest_hash,
            size_bytes=len(manifest_bytes),
            schema_version=MANIFEST_SCHEMA_VERSION,
            metadata_={"kind": "provenance_extraction_manifest"},
        )
    )
    await session.flush()

    span_rows = _add_evidence_spans(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        run_id=run.id,
        resolved_evidence=resolved_evidence,
    )
    await session.flush()

    entity_rows = _add_extracted_entities(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        run_id=run.id,
        batch=batch,
        resolved_evidence=resolved_evidence,
    )
    await session.flush()

    _add_entity_evidence_links(
        session,
        tenant_id=tenant_id,
        entity_rows=entity_rows,
        span_rows=span_rows,
        resolved_evidence=resolved_evidence,
    )
    relation_rows = _add_extracted_relations(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        run_id=run.id,
        batch=batch,
        entity_rows=entity_rows,
        resolved_evidence=resolved_evidence,
    )
    claim_rows = _add_extracted_claims(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        run_id=run.id,
        batch=batch,
        entity_rows=entity_rows,
        resolved_evidence=resolved_evidence,
    )
    await session.flush()

    _add_relation_evidence_links(
        session,
        tenant_id=tenant_id,
        relation_rows=relation_rows,
        span_rows=span_rows,
        resolved_evidence=resolved_evidence,
    )
    _add_claim_evidence_links(
        session,
        tenant_id=tenant_id,
        claim_rows=claim_rows,
        span_rows=span_rows,
        resolved_evidence=resolved_evidence,
    )
    await session.flush()

    return PersistedProvenanceExtraction(
        extraction_run_id=run.id,
        manifest_uri=manifest_uri,
        manifest_hash=manifest_hash,
    )


class ExtractionManifest(BaseModel):
    schema_version: str
    source: dict[str, str]
    provider: dict[str, str | None]
    input_hash: str
    counts: dict[str, int]
    batch: dict[str, Any]
    evidence_spans: list[dict[str, Any]]


def _manifest_payload(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunks: list[ExtractionInputChunk],
    batch: ExtractionBatch,
    resolved_evidence: ResolvedBatchEvidence,
    metadata: ProvenanceExtractionMetadata,
    input_hash: str,
) -> ExtractionManifest:
    return ExtractionManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        source={
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "document_version_id": str(version_id),
        },
        provider={
            "prompt_version": metadata.prompt_version,
            "extractor_version": metadata.extractor_version,
            "model_provider": metadata.model_provider,
            "model_name": metadata.model_name,
            "request_hash": metadata.request_hash,
            "response_hash": metadata.response_hash,
        },
        input_hash=input_hash,
        counts={
            "entities": len(batch.entities),
            "relations": len(batch.relations),
            "claims": len(batch.claims),
            "spans": len(resolved_evidence.spans_by_id),
        },
        batch=batch.model_dump(mode="json"),
        evidence_spans=[
            span.model_dump(mode="json")
            for span in sorted(
                resolved_evidence.spans_by_id.values(),
                key=lambda span: (span.chunk_id, span.start_offset, span.end_offset),
            )
        ],
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


async def _find_ready_run(
    session: AsyncSession,
    *,
    version_id: UUID,
    input_hash: str,
    schema_version: str,
    prompt_version: str,
    extractor_version: str,
    model_name: str,
) -> ExtractionRun | None:
    existing: ExtractionRun | None = await session.scalar(
        select(ExtractionRun).where(
            ExtractionRun.document_version_id == version_id,
            ExtractionRun.input_hash == input_hash,
            ExtractionRun.schema_version == schema_version,
            ExtractionRun.prompt_version == prompt_version,
            ExtractionRun.extractor_version == extractor_version,
            ExtractionRun.model_name == model_name,
            ExtractionRun.status == ExtractionRunStatus.READY,
            ExtractionRun.manifest_uri.is_not(None),
            ExtractionRun.manifest_hash.is_not(None),
        )
    )
    return existing


def _add_evidence_spans(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    run_id: UUID,
    resolved_evidence: ResolvedBatchEvidence,
) -> dict[str, EvidenceSpan]:
    rows: dict[str, EvidenceSpan] = {}
    for span in resolved_evidence.spans_by_id.values():
        row = EvidenceSpan(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            extraction_run_id=run_id,
            stable_id=span.stable_id,
            chunk_id=span.chunk_id,
            quote=span.quote,
            start_offset=span.start_offset,
            end_offset=span.end_offset,
            span_hash=span.span_hash,
        )
        session.add(row)
        rows[span.stable_id] = row
    return rows


def _add_extracted_entities(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    run_id: UUID,
    batch: ExtractionBatch,
    resolved_evidence: ResolvedBatchEvidence,
) -> dict[str, ExtractedEntity]:
    rows: dict[str, ExtractedEntity] = {}
    for entity in batch.entities:
        stable_id = _stable_id(
            "xe",
            entity.entity_type,
            normalize_name(entity.name),
            *resolved_evidence.entity_evidence_ids[entity.local_id],
        )
        row = ExtractedEntity(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            extraction_run_id=run_id,
            stable_id=stable_id,
            local_id=entity.local_id,
            name=entity.name,
            normalized_name=normalize_name(entity.name),
            entity_type=EntityType(entity.entity_type),
            aliases=list(entity.aliases),
            confidence=entity.confidence,
            attributes=dict(entity.attributes),
            status=StagedProposalStatus.ACCEPTED,
        )
        session.add(row)
        rows[entity.local_id] = row
    return rows


def _add_entity_evidence_links(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity_rows: dict[str, ExtractedEntity],
    span_rows: dict[str, EvidenceSpan],
    resolved_evidence: ResolvedBatchEvidence,
) -> None:
    for local_id, evidence_ids in resolved_evidence.entity_evidence_ids.items():
        for evidence_id in evidence_ids:
            session.add(
                ExtractedEntityEvidence(
                    tenant_id=tenant_id,
                    extracted_entity_id=entity_rows[local_id].id,
                    evidence_span_id=span_rows[evidence_id].id,
                )
            )


def _add_extracted_relations(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    run_id: UUID,
    batch: ExtractionBatch,
    entity_rows: dict[str, ExtractedEntity],
    resolved_evidence: ResolvedBatchEvidence,
) -> dict[str, ExtractedRelation]:
    rows: dict[str, ExtractedRelation] = {}
    for relation in batch.relations:
        stable_id = _stable_id(
            "xr",
            relation.subject_entity_id,
            relation.predicate,
            relation.object_entity_id,
            *resolved_evidence.relation_evidence_ids[relation.local_id],
        )
        row = ExtractedRelation(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            extraction_run_id=run_id,
            stable_id=stable_id,
            local_id=relation.local_id,
            subject_extracted_entity_id=entity_rows[relation.subject_entity_id].id,
            predicate=relation.predicate,
            object_extracted_entity_id=entity_rows[relation.object_entity_id].id,
            confidence=relation.confidence,
            attributes={},
            status=StagedProposalStatus.ACCEPTED,
        )
        session.add(row)
        rows[relation.local_id] = row
    return rows


def _add_extracted_claims(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    run_id: UUID,
    batch: ExtractionBatch,
    entity_rows: dict[str, ExtractedEntity],
    resolved_evidence: ResolvedBatchEvidence,
) -> dict[str, ExtractedClaim]:
    rows: dict[str, ExtractedClaim] = {}
    for claim in batch.claims:
        stable_id = _stable_id(
            "xc",
            claim.subject_entity_id or "",
            claim.predicate,
            claim.object_entity_id or claim.object_text or "",
            *resolved_evidence.claim_evidence_ids[claim.local_id],
        )
        row = ExtractedClaim(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            extraction_run_id=run_id,
            stable_id=stable_id,
            local_id=claim.local_id,
            subject_extracted_entity_id=(
                entity_rows[claim.subject_entity_id].id
                if claim.subject_entity_id is not None
                else None
            ),
            predicate=claim.predicate,
            object_extracted_entity_id=(
                entity_rows[claim.object_entity_id].id
                if claim.object_entity_id is not None
                else None
            ),
            object_text=claim.object_text,
            claim_text=None,
            confidence=claim.confidence,
            attributes={},
            status=StagedProposalStatus.ACCEPTED,
        )
        session.add(row)
        rows[claim.local_id] = row
    return rows


def _add_relation_evidence_links(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    relation_rows: dict[str, ExtractedRelation],
    span_rows: dict[str, EvidenceSpan],
    resolved_evidence: ResolvedBatchEvidence,
) -> None:
    for local_id, evidence_ids in resolved_evidence.relation_evidence_ids.items():
        for evidence_id in evidence_ids:
            session.add(
                ExtractedRelationEvidence(
                    tenant_id=tenant_id,
                    extracted_relation_id=relation_rows[local_id].id,
                    evidence_span_id=span_rows[evidence_id].id,
                )
            )


def _add_claim_evidence_links(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    claim_rows: dict[str, ExtractedClaim],
    span_rows: dict[str, EvidenceSpan],
    resolved_evidence: ResolvedBatchEvidence,
) -> None:
    for local_id, evidence_ids in resolved_evidence.claim_evidence_ids.items():
        for evidence_id in evidence_ids:
            session.add(
                ExtractedClaimEvidence(
                    tenant_id=tenant_id,
                    extracted_claim_id=claim_rows[local_id].id,
                    evidence_span_id=span_rows[evidence_id].id,
                )
            )


def _input_hash(chunks: list[ExtractionInputChunk]) -> str:
    payload = [
        {"chunk_id": chunk.chunk_id, "text_hash": _content_hash(chunk.text.encode("utf-8"))}
        for chunk in chunks
    ]
    encoded = repr(payload).encode("utf-8")
    return _content_hash(encoded)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


def _content_hash(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()
