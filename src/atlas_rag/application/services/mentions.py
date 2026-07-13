from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.entity_resolution import normalize_name
from atlas_rag.application.extraction import ExtractedDocumentFacts
from atlas_rag.domain.enums import ClaimStatus, EntityType, MentionResolutionStatus
from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import Claim, Document, DocumentVersion, EntityMention


@dataclass(slots=True, frozen=True)
class PersistedMentions:
    mention_count: int
    claim_count: int


async def persist_mentions_and_claims(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    extraction: ExtractedDocumentFacts | None,
    source_artifact_id: UUID | None,
    prompt_hash: str | None,
    response_hash: str | None,
) -> PersistedMentions:
    """Derive and persist entity mentions and claims for a document version.

    Idempotent per version: any existing mentions and claims for the version are
    replaced, mirroring the chunk-persistence pattern. Mentions are created for
    every extracted entity and for any claim subject not already present (typed
    ``other``). A claim object links to an entity mention when its surface matches
    one; otherwise it is stored as an ``object_literal``.
    """

    await _ensure_version_exists(
        session, tenant_id=tenant_id, document_id=document_id, version_id=version_id
    )
    await _clear_existing(session, version_id=version_id)

    if extraction is None:
        await session.flush()
        return PersistedMentions(mention_count=0, claim_count=0)

    evidence_by_norm = _evidence_chunk_ids_by_norm(extraction)
    mentions_by_norm: dict[str, EntityMention] = {}

    def ensure_mention(surface: str, entity_type: EntityType) -> EntityMention | None:
        norm = normalize_name(surface)
        if not norm:
            return None
        existing = mentions_by_norm.get(norm)
        if existing is not None:
            return existing
        mention = EntityMention(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            source_artifact_id=source_artifact_id,
            surface_text=surface,
            normalized_text=norm,
            entity_type=entity_type,
            chunk_ids=sorted(evidence_by_norm.get(norm, set())),
            resolution_status=MentionResolutionStatus.PENDING,
            prompt_hash=prompt_hash,
            response_hash=response_hash,
        )
        session.add(mention)
        mentions_by_norm[norm] = mention
        return mention

    # Entities are authoritative for type; claim subjects fill in anything missing.
    for entity in extraction.entities:
        ensure_mention(entity.name, EntityType(entity.type))
    for claim in extraction.claims:
        ensure_mention(claim.subject, EntityType.OTHER)
    await session.flush()  # assign mention ids before wiring claims

    claim_count = 0
    for claim in extraction.claims:
        subject = mentions_by_norm.get(normalize_name(claim.subject))
        if subject is None:
            continue
        object_mention = mentions_by_norm.get(normalize_name(claim.object))
        session.add(
            Claim(
                tenant_id=tenant_id,
                document_id=document_id,
                document_version_id=version_id,
                subject_mention_id=subject.id,
                predicate=claim.predicate,
                object_mention_id=object_mention.id if object_mention is not None else None,
                object_literal=None if object_mention is not None else claim.object,
                evidence_chunk_ids=list(claim.evidence_chunk_ids),
                status=ClaimStatus.PENDING,
            )
        )
        claim_count += 1

    await session.flush()
    return PersistedMentions(mention_count=len(mentions_by_norm), claim_count=claim_count)


def _evidence_chunk_ids_by_norm(extraction: ExtractedDocumentFacts) -> dict[str, set[str]]:
    evidence: dict[str, set[str]] = {}
    for claim in extraction.claims:
        for surface in (claim.subject, claim.object):
            norm = normalize_name(surface)
            if norm:
                evidence.setdefault(norm, set()).update(claim.evidence_chunk_ids)
    return evidence


async def _clear_existing(session: AsyncSession, *, version_id: UUID) -> None:
    # Claims reference mentions, so remove claims first.
    await session.execute(delete(Claim).where(Claim.document_version_id == version_id))
    await session.execute(
        delete(EntityMention).where(EntityMention.document_version_id == version_id)
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
