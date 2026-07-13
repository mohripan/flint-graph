from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.entity_resolution import CandidateEntity
from atlas_rag.domain.enums import EntityStatus, EntityType
from atlas_rag.infrastructure.db.models import CanonicalEntity, EntityAlias, EntityMention


async def generate_candidates(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    normalized_text: str,
    entity_type: EntityType,
    trigram_threshold: float,
    limit: int,
    exclude_entity_id: UUID | None = None,
) -> list[CandidateEntity]:
    """Block candidate canonical entities for a mention (PostgreSQL / pg_trgm).

    Blocking is type-constrained and matches on exact normalized name, exact alias
    form, or trigram similarity above ``trigram_threshold`` on either. Only active
    entities are considered. Scoring/ranking is performed separately by the pure
    scoring module.
    """

    if not normalized_text:
        return []

    alias_matches = select(EntityAlias.canonical_entity_id).where(
        EntityAlias.tenant_id == tenant_id,
        or_(
            EntityAlias.normalized_form == normalized_text,
            func.similarity(EntityAlias.normalized_form, normalized_text) >= trigram_threshold,
        ),
    )
    stmt = (
        select(CanonicalEntity.id)
        .where(
            CanonicalEntity.tenant_id == tenant_id,
            CanonicalEntity.entity_type == entity_type,
            CanonicalEntity.status == EntityStatus.ACTIVE,
            or_(
                CanonicalEntity.normalized_name == normalized_text,
                func.similarity(CanonicalEntity.normalized_name, normalized_text)
                >= trigram_threshold,
                CanonicalEntity.id.in_(alias_matches),
            ),
        )
        .limit(limit)
    )
    if exclude_entity_id is not None:
        stmt = stmt.where(CanonicalEntity.id != exclude_entity_id)

    entity_ids = list((await session.execute(stmt)).scalars().all())
    if not entity_ids:
        return []
    return await load_candidate_entities(session, entity_ids=entity_ids)


async def load_candidate_entities(
    session: AsyncSession, *, entity_ids: list[UUID]
) -> list[CandidateEntity]:
    entities = list(
        (
            await session.execute(
                select(CanonicalEntity).where(CanonicalEntity.id.in_(entity_ids))
            )
        )
        .scalars()
        .all()
    )

    aliases_by_entity: dict[UUID, list[str]] = {}
    alias_rows = (
        await session.execute(
            select(EntityAlias.canonical_entity_id, EntityAlias.normalized_form).where(
                EntityAlias.canonical_entity_id.in_(entity_ids)
            )
        )
    ).all()
    for entity_id, normalized_form in alias_rows:
        aliases_by_entity.setdefault(entity_id, []).append(normalized_form)

    documents_by_entity: dict[UUID, set[UUID]] = {}
    document_rows = (
        await session.execute(
            select(EntityMention.resolved_entity_id, EntityMention.document_id)
            .where(EntityMention.resolved_entity_id.in_(entity_ids))
            .distinct()
        )
    ).all()
    for entity_id, document_id in document_rows:
        if entity_id is not None:
            documents_by_entity.setdefault(entity_id, set()).add(document_id)

    return [
        CandidateEntity(
            entity_id=entity.id,
            entity_type=entity.entity_type,
            normalized_name=entity.normalized_name,
            alias_forms=tuple(sorted(aliases_by_entity.get(entity.id, []))),
            document_ids=frozenset(documents_by_entity.get(entity.id, set())),
        )
        for entity in entities
    ]
