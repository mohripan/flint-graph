from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.entity_resolution import normalize_name
from flint_graph.application.query_decomposition import coordinated_retrieval_queries
from flint_graph.application.query_orchestration import (
    DeterministicQueryClassifier,
    QueryClassification,
    QueryClassificationRequest,
    QueryClassifier,
    QueryEntityLink,
)
from flint_graph.application.services.query_runs import (
    append_query_run_event,
    get_query_run,
    persist_query_entity_link,
    record_query_classification,
)
from flint_graph.domain.enums import EntityStatus
from flint_graph.infrastructure.db.models import CanonicalEntity, EntityAlias

_CAPITALIZED_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*")
_QUESTION_LEADS = {
    "How",
    "Tell",
    "What",
    "When",
    "Where",
    "Which",
    "Who",
    "Why",
}


@dataclass(frozen=True, slots=True)
class _EntitySurface:
    entity_id: UUID
    surface: str
    normalized: str
    is_alias: bool


class EntityLinkProvider(Protocol):
    async def link(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
    ) -> list[QueryEntityLink]: ...


async def classify_query_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    classifier: QueryClassifier | None = None,
) -> QueryClassification:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    model = classifier or DeterministicQueryClassifier()
    classification = await model.classify(
        QueryClassificationRequest(
            tenant_id=tenant_id,
            query=run.query_text,
            retrieval_index_version_id=run.retrieval_index_version_id,
        )
    )
    queries = coordinated_retrieval_queries(run.query_text)
    if classification.label != "unsupported" and len(queries) > 1:
        classification = classification.model_copy(
            update={
                "metadata": {
                    **classification.metadata,
                    "retrieval_queries": queries,
                    "decomposition_method": "coordinated-possessive-v1",
                }
            }
        )
    await record_query_classification(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        label=classification.label,
        strategy=classification.retrieval_plan.strategy,
        confidence=classification.confidence,
        metadata={
            "reasons": classification.reasons,
            "enabled_retrievers": classification.retrieval_plan.enabled_retrievers,
            "retriever_weights": classification.retrieval_plan.retriever_weights,
            "candidate_limits": classification.retrieval_plan.candidate_limits,
            "requires_entity_linking": classification.retrieval_plan.requires_entity_linking,
            "requires_graph_expansion": classification.retrieval_plan.requires_graph_expansion,
            "allow_partial_retrieval": classification.retrieval_plan.allow_partial_retrieval,
            **classification.metadata,
        },
    )
    await append_query_run_event(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        event_type="query.classified",
        payload={
            "label": classification.label,
            "strategy": classification.retrieval_plan.strategy,
            "confidence": classification.confidence,
            **(
                {"retrieval_query_count": len(queries)}
                if classification.label != "unsupported" and len(queries) > 1
                else {}
            ),
        },
    )
    return classification


async def link_query_entities(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    linker: EntityLinkProvider | None = None,
) -> list[QueryEntityLink]:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    provider = linker or DeterministicEntityLinker()
    links = await provider.link(session, tenant_id=tenant_id, query=run.query_text)
    for link in links:
        await persist_query_entity_link(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            link=link,
        )
    await append_query_run_event(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        event_type="entities.linked",
        payload={
            "accepted": sum(1 for link in links if link.status == "accepted"),
            "ambiguous": sum(1 for link in links if link.status == "ambiguous"),
            "rejected": sum(1 for link in links if link.status == "rejected"),
        },
    )
    return links


class DeterministicEntityLinker:
    async def link(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
    ) -> list[QueryEntityLink]:
        surfaces = await _load_entity_surfaces(session, tenant_id=tenant_id)
        matched_by_mention = _match_known_surfaces(query, surfaces)
        for mention in _extract_unmatched_mentions(query, set(matched_by_mention)):
            matched_by_mention[mention] = []

        links: list[QueryEntityLink] = []
        for mention in sorted(matched_by_mention, key=lambda item: (query.find(item), item)):
            matches = matched_by_mention[mention]
            entity_ids = sorted({match.entity_id for match in matches}, key=str)
            if len(entity_ids) == 1:
                links.append(
                    QueryEntityLink(
                        mention_text=mention,
                        status="accepted",
                        canonical_entity_id=entity_ids[0],
                        score=1.0,
                        method="deterministic-exact",
                        reasons=["exact normalized name or alias match"],
                    )
                )
            elif len(entity_ids) > 1:
                links.append(
                    QueryEntityLink(
                        mention_text=mention,
                        status="ambiguous",
                        candidate_entity_ids=entity_ids,
                        score=1.0,
                        method="deterministic-exact",
                        reasons=["multiple exact normalized name or alias matches"],
                    )
                )
            else:
                links.append(
                    QueryEntityLink(
                        mention_text=mention,
                        status="rejected",
                        score=0.0,
                        method="deterministic-exact",
                        reasons=["no tenant-scoped canonical entity or alias match"],
                    )
                )
        return links


async def _load_entity_surfaces(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[_EntitySurface]:
    entities = list(
        await session.scalars(
            select(CanonicalEntity).where(
                CanonicalEntity.tenant_id == tenant_id,
                CanonicalEntity.status == EntityStatus.ACTIVE,
            )
        )
    )
    surfaces = [
        _EntitySurface(
            entity_id=entity.id,
            surface=entity.canonical_name,
            normalized=entity.normalized_name,
            is_alias=False,
        )
        for entity in entities
    ]
    aliases = list(
        await session.scalars(select(EntityAlias).where(EntityAlias.tenant_id == tenant_id))
    )
    surfaces.extend(
        _EntitySurface(
            entity_id=alias.canonical_entity_id,
            surface=alias.surface_form,
            normalized=alias.normalized_form,
            is_alias=True,
        )
        for alias in aliases
    )
    return [surface for surface in surfaces if surface.normalized]


def _match_known_surfaces(
    query: str,
    surfaces: list[_EntitySurface],
) -> dict[str, list[_EntitySurface]]:
    normalized_query = f" {normalize_name(query)} "
    matches_by_normalized: dict[str, list[_EntitySurface]] = defaultdict(list)
    display_by_normalized: dict[str, str] = {}
    for surface in sorted(
        surfaces,
        key=lambda item: (len(item.normalized.split()), len(item.normalized)),
        reverse=True,
    ):
        if f" {surface.normalized} " not in normalized_query:
            continue
        matches_by_normalized[surface.normalized].append(surface)
        display_by_normalized.setdefault(surface.normalized, surface.surface)

    return {
        display_by_normalized[normalized]: matches
        for normalized, matches in matches_by_normalized.items()
    }


def _extract_unmatched_mentions(query: str, existing_mentions: set[str]) -> list[str]:
    mentions: list[str] = []
    existing_normalized = {normalize_name(mention) for mention in existing_mentions}
    for match in _CAPITALIZED_PHRASE_RE.finditer(query):
        mention = _strip_leading_question_word(match.group(0).strip())
        normalized = normalize_name(mention)
        if not mention or normalized in existing_normalized:
            continue
        if normalized in {"i"}:
            continue
        mentions.append(mention)
        existing_normalized.add(normalized)
    return mentions


def _strip_leading_question_word(mention: str) -> str:
    parts = mention.split()
    while parts and parts[0] in _QUESTION_LEADS:
        parts = parts[1:]
    return " ".join(parts)
