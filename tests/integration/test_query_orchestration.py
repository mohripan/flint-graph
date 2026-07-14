from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.query_orchestration import QueryCandidate
from atlas_rag.application.services.query_orchestration import (
    QueryRetrieverBundle,
    run_query_retrieval_graph,
)
from atlas_rag.application.services.query_runs import QueryRunCreate, create_query_run
from atlas_rag.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from atlas_rag.domain.enums import (
    AliasSource,
    EntityStatus,
    EntityType,
    QueryRunStatus,
    RetrievalIndexScope,
)
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    QueryContextPack,
    QueryContextPackRecord,
    QueryRun,
    QueryRunCandidate,
    QueryRunEvent,
    Tenant,
)


@dataclass
class FakeRetrievers:
    lexical_results: list[QueryCandidate] = field(default_factory=list)
    vector_results: list[QueryCandidate] = field(default_factory=list)
    graph_results: list[QueryCandidate] = field(default_factory=list)
    fail_source: str | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    started: dict[str, asyncio.Event] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for source in ("lexical", "vector", "graph"):
            self.started[source] = asyncio.Event()

    async def retrieve_lexical(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        limit: int,
    ) -> list[QueryCandidate]:
        self.started["lexical"].set()
        self.calls.append(
            (
                "lexical",
                {
                    "tenant_id": tenant_id,
                    "query": query,
                    "retrieval_index_version_id": retrieval_index_version_id,
                    "limit": limit,
                },
            )
        )
        await asyncio.sleep(0)
        if self.fail_source == "lexical":
            raise RuntimeError("lexical unavailable")
        return self.lexical_results

    async def retrieve_vector(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        limit: int,
    ) -> list[QueryCandidate]:
        self.started["vector"].set()
        self.calls.append(
            (
                "vector",
                {
                    "tenant_id": tenant_id,
                    "query": query,
                    "retrieval_index_version_id": retrieval_index_version_id,
                    "limit": limit,
                },
            )
        )
        await self.started["lexical"].wait()
        if self.fail_source == "vector":
            raise RuntimeError("vector unavailable")
        return self.vector_results

    async def retrieve_graph(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        linked_entity_ids: list[UUID],
        depth: int,
        limit: int,
    ) -> list[QueryCandidate]:
        self.started["graph"].set()
        self.calls.append(
            (
                "graph",
                {
                    "tenant_id": tenant_id,
                    "query": query,
                    "retrieval_index_version_id": retrieval_index_version_id,
                    "linked_entity_ids": linked_entity_ids,
                    "depth": depth,
                    "limit": limit,
                },
            )
        )
        if self.fail_source == "graph":
            raise RuntimeError("graph unavailable")
        return self.graph_results


async def _tenant(session: AsyncSession, name: str = "query-orchestration") -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    return tenant


def _index_spec(model: str = "deterministic-orchestration") -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model=model,
        vector_dimension=4,
        embedding_config_hash=f"sha256:{model}",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name=f"atlas_chunks_{model}",
        neo4j_vector_property_name="embedding",
        opensearch_index_name=f"atlas_chunks_{model}",
        opensearch_alias_name="atlas_chunks_active",
    )


async def _active_index_id(session: AsyncSession, tenant: Tenant) -> UUID:
    version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=_index_spec(),
    )
    active = await activate_retrieval_index_version(session, version_id=version.id)
    return active.id


async def _query_run(
    session: AsyncSession,
    tenant: Tenant,
    query_text: str,
) -> tuple[UUID, UUID]:
    index_id = await _active_index_id(session, tenant)
    run = await create_query_run(
        session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text=query_text,
            retrieval_index_version_id=index_id,
        ),
    )
    return run.id, index_id


async def _entity(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str,
    normalized: str,
    entity_type: EntityType,
    alias: str | None = None,
) -> CanonicalEntity:
    entity = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=entity_type,
        canonical_name=name,
        normalized_name=normalized,
        status=EntityStatus.ACTIVE,
        support_count=1,
    )
    session.add(entity)
    await session.flush()
    if alias is not None:
        session.add(
            EntityAlias(
                tenant_id=tenant.id,
                canonical_entity_id=entity.id,
                surface_form=alias,
                normalized_form=alias.casefold(),
                source=AliasSource.MANUAL,
            )
        )
        await session.flush()
    return entity


def _candidate(
    *,
    tenant_id: UUID,
    index_id: UUID,
    source: str,
    candidate_id: str,
    rank: int,
    normalized_score: float = 1.0,
    text_preview: str | None = None,
    source_ids: dict[str, str] | None = None,
) -> QueryCandidate:
    return QueryCandidate(
        candidate_id=candidate_id,
        source=source,  # type: ignore[arg-type]
        candidate_type="chunk",
        tenant_id=tenant_id,
        retrieval_index_version_id=index_id,
        source_ids=source_ids or {"chunk_id": candidate_id.rsplit(":", maxsplit=1)[-1]},
        text_preview=text_preview or f"{source} candidate",
        raw_score=normalized_score,
        normalized_score=normalized_score,
        rank=rank,
    )


async def test_query_retrieval_graph_runs_enabled_retrievers_and_persists_candidates(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    acme = await _entity(
        db_session,
        tenant,
        name="Acme Corporation",
        normalized="acme corporation",
        entity_type=EntityType.ORGANIZATION,
        alias="Acme",
    )
    berlin = await _entity(
        db_session,
        tenant,
        name="Berlin",
        normalized="berlin",
        entity_type=EntityType.PLACE,
    )
    run_id, index_id = await _query_run(
        db_session,
        tenant,
        "How are Acme Corporation and Berlin connected?",
    )
    retrievers = FakeRetrievers(
        lexical_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="lexical",
                candidate_id="lexical:chunk:chunk-000001",
                rank=1,
            )
        ],
        vector_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="vector",
                candidate_id="vector:chunk:chunk-000002",
                rank=1,
            )
        ],
        graph_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="graph",
                candidate_id="graph:relationship:rel-1",
                rank=1,
            ).model_copy(update={"candidate_type": "relationship"})
        ],
    )

    state = await run_query_retrieval_graph(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run_id,
        retrievers=QueryRetrieverBundle(
            lexical=retrievers,
            vector=retrievers,
            graph=retrievers,
        ),
    )

    rows = list(
        await db_session.scalars(
            select(QueryRunCandidate)
            .where(QueryRunCandidate.query_run_id == run_id)
            .order_by(QueryRunCandidate.source)
        )
    )
    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run_id)
            .order_by(QueryRunEvent.sequence)
        )
    )

    assert state.status == QueryRunStatus.COMPLETED
    assert state.classification_label == "relationship"
    assert state.enabled_retrievers == ["lexical", "vector", "graph"]
    assert state.retrieved_candidate_count == 3
    assert set(state.linked_entity_ids) == {acme.id, berlin.id}
    assert {source for source, _payload in retrievers.calls} == {"lexical", "vector", "graph"}
    graph_call = next(payload for source, payload in retrievers.calls if source == "graph")
    assert set(graph_call["linked_entity_ids"]) == {acme.id, berlin.id}
    assert [(row.source, row.dedupe_key) for row in rows] == [
        ("graph", "graph:relationship:rel-1"),
        ("lexical", "lexical:chunk:chunk-000001"),
        ("vector", "vector:chunk:chunk-000002"),
    ]
    assert [event.event_type for event in events] == [
        "query.started",
        "query.classified",
        "entities.linked",
        "retrieval.started",
        "retrieval.progress",
        "retrieval.progress",
        "retrieval.progress",
        "retrieval.completed",
        "fusion.completed",
        "rerank.completed",
        "context.packed",
        "answer.delta",
        "answer.citation",
        "answer.citation",
        "answer.citation",
        "query.completed",
    ]
    assert all(row.fusion_score is not None for row in rows)
    assert [row.rerank_rank for row in rows if row.rerank_rank is not None] == [1, 2, 3]


async def test_query_retrieval_graph_skips_graph_without_accepted_links(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    run_id, index_id = await _query_run(
        db_session,
        tenant,
        "How are Contoso and Fabrikam connected?",
    )
    retrievers = FakeRetrievers(
        lexical_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="lexical",
                candidate_id="lexical:chunk:chunk-000001",
                rank=1,
            )
        ],
        vector_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="vector",
                candidate_id="vector:chunk:chunk-000002",
                rank=1,
            )
        ],
    )

    state = await run_query_retrieval_graph(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run_id,
        retrievers=QueryRetrieverBundle(
            lexical=retrievers,
            vector=retrievers,
            graph=retrievers,
        ),
    )

    assert state.enabled_retrievers == ["lexical", "vector"]
    assert state.retrieved_candidate_count == 2
    assert [source for source, _payload in retrievers.calls] == ["lexical", "vector"]


async def test_query_retrieval_graph_fuses_duplicate_candidates_and_reranks(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    run_id, index_id = await _query_run(
        db_session,
        tenant,
        "Where is Acme Corporation headquartered in Berlin?",
    )
    retrievers = FakeRetrievers(
        lexical_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="lexical",
                candidate_id="lexical:chunk:chunk-acme",
                rank=1,
                normalized_score=0.8,
                source_ids={"chunk_id": "chunk-acme"},
                text_preview="Acme Corporation is headquartered in Berlin.",
            )
        ],
        vector_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="vector",
                candidate_id="vector:chunk:chunk-acme",
                rank=2,
                normalized_score=0.9,
                source_ids={"chunk_id": "chunk-acme"},
                text_preview="Acme Corporation is headquartered in Berlin.",
            ),
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="vector",
                candidate_id="vector:chunk:chunk-paris",
                rank=1,
                normalized_score=1.0,
                source_ids={"chunk_id": "chunk-paris"},
                text_preview="Quarterly revenue increased in Paris.",
            ),
        ],
    )

    state = await run_query_retrieval_graph(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run_id,
        retrievers=QueryRetrieverBundle(
            lexical=retrievers,
            vector=retrievers,
            graph=retrievers,
        ),
    )

    rows = list(
        await db_session.scalars(
            select(QueryRunCandidate)
            .where(QueryRunCandidate.query_run_id == run_id)
            .order_by(QueryRunCandidate.source, QueryRunCandidate.dedupe_key)
        )
    )
    ranked_rows = sorted(
        (row for row in rows if row.rerank_rank is not None),
        key=lambda row: row.rerank_rank or 0,
    )
    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run_id)
            .order_by(QueryRunEvent.sequence)
        )
    )

    assert state.status == QueryRunStatus.COMPLETED
    assert state.retrieved_candidate_count == 3
    assert state.fused_candidate_count == 2
    assert state.reranked_candidate_count == 2
    assert state.context_pack_record_count == 2
    assert state.answer_citation_count == 2
    assert [event.event_type for event in events][-4:] == [
        "answer.delta",
        "answer.citation",
        "answer.citation",
        "query.completed",
    ]
    assert [row.dedupe_key for row in ranked_rows] == [
        "lexical:chunk:chunk-acme",
        "vector:chunk:chunk-paris",
    ]
    assert ranked_rows[0].rerank_score is not None
    assert ranked_rows[0].rerank_score > (ranked_rows[1].rerank_score or 0)
    duplicate_rows = [row for row in rows if row.source_ids["chunk_id"] == "chunk-acme"]
    assert len(duplicate_rows) == 2
    assert {row.fusion_score for row in duplicate_rows} == {ranked_rows[0].fusion_score}


async def test_query_retrieval_graph_packs_ranked_context_with_budget(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    run_id, index_id = await _query_run(
        db_session,
        tenant,
        "Where is Acme Corporation headquartered in Berlin?",
    )
    retrievers = FakeRetrievers(
        lexical_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="lexical",
                candidate_id="lexical:chunk:chunk-acme",
                rank=1,
                normalized_score=0.8,
                source_ids={"chunk_id": "chunk-acme"},
                text_preview="Acme Corporation is headquartered in Berlin.",
            )
        ],
        vector_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="vector",
                candidate_id="vector:chunk:chunk-paris",
                rank=1,
                normalized_score=1.0,
                source_ids={"chunk_id": "chunk-paris"},
                text_preview="Quarterly revenue increased in Paris.",
            ),
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="vector",
                candidate_id="vector:chunk:chunk-empty",
                rank=2,
                normalized_score=0.7,
                source_ids={"chunk_id": "chunk-empty"},
                text_preview="",
            ),
        ],
    )

    state = await run_query_retrieval_graph(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run_id,
        retrievers=QueryRetrieverBundle(
            lexical=retrievers,
            vector=retrievers,
            graph=retrievers,
        ),
        context_token_budget=6,
        context_max_records=5,
    )

    pack = await db_session.scalar(
        select(QueryContextPack).where(QueryContextPack.query_run_id == run_id)
    )
    records = list(
        await db_session.scalars(
            select(QueryContextPackRecord)
            .where(QueryContextPackRecord.query_run_id == run_id)
            .order_by(QueryContextPackRecord.citation_id)
        )
    )
    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run_id)
            .order_by(QueryRunEvent.sequence)
        )
    )

    assert state.status == QueryRunStatus.COMPLETED
    assert state.context_pack_record_count == 1
    assert state.context_token_count == 6
    assert state.answer_citation_count == 1
    assert pack is not None
    assert pack.token_budget == 6
    assert pack.token_count == 6
    assert pack.selected_candidate_ids == ["lexical:chunk:chunk-acme"]
    assert records[0].context_id == "ctx-0001"
    assert records[0].citation_id == "c1"
    assert records[0].candidate_id == "lexical:chunk:chunk-acme"
    assert records[0].source_ids == {"chunk_id": "chunk-acme"}
    assert records[0].text == "Acme Corporation is headquartered in Berlin."
    packed_event = next(event for event in events if event.event_type == "context.packed")
    assert packed_event.payload["token_count"] == 6
    assert [event.event_type for event in events][-3:] == [
        "answer.delta",
        "answer.citation",
        "query.completed",
    ]
    assert events[-1].event_type == "query.completed"


async def test_query_retrieval_graph_generates_answer_and_completes_run(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    run_id, index_id = await _query_run(
        db_session,
        tenant,
        "Where is Acme Corporation headquartered?",
    )
    retrievers = FakeRetrievers(
        lexical_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="lexical",
                candidate_id="lexical:chunk:chunk-acme",
                rank=1,
                normalized_score=0.9,
                source_ids={"chunk_id": "chunk-acme"},
                text_preview="Acme Corporation is headquartered in Berlin.",
            )
        ],
        vector_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="vector",
                candidate_id="vector:chunk:chunk-acme",
                rank=1,
                normalized_score=0.8,
                source_ids={"chunk_id": "chunk-acme"},
                text_preview="Acme Corporation is headquartered in Berlin.",
            )
        ],
    )

    state = await run_query_retrieval_graph(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run_id,
        retrievers=QueryRetrieverBundle(
            lexical=retrievers,
            vector=retrievers,
            graph=retrievers,
        ),
    )

    run = await db_session.scalar(select(QueryRun).where(QueryRun.id == run_id))
    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run_id)
            .order_by(QueryRunEvent.sequence)
        )
    )

    assert state.status == QueryRunStatus.COMPLETED
    assert state.answer_citation_count == 1
    assert state.insufficient_context is False
    assert state.answer_text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert run is not None
    assert run.status == QueryRunStatus.COMPLETED
    assert run.completed_at is not None
    assert run.answer_text == "Acme Corporation is headquartered in Berlin. [c1]"
    assert run.answer_citations == [
        {
            "citation_id": "c1",
            "context_id": "ctx-0001",
            "marker": "[c1]",
            "source_ids": {"chunk_id": "chunk-acme"},
        }
    ]
    assert events[-1].event_type == "query.completed"
    assert events[-1].payload["answer_citation_count"] == 1


async def test_query_retrieval_graph_fails_run_when_required_retriever_fails(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    run_id, index_id = await _query_run(
        db_session,
        tenant,
        "Where is Acme Corporation headquartered?",
    )
    retrievers = FakeRetrievers(
        lexical_results=[
            _candidate(
                tenant_id=tenant.id,
                index_id=index_id,
                source="lexical",
                candidate_id="lexical:chunk:chunk-000001",
                rank=1,
            )
        ],
        fail_source="vector",
    )

    state = await run_query_retrieval_graph(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run_id,
        retrievers=QueryRetrieverBundle(
            lexical=retrievers,
            vector=retrievers,
            graph=retrievers,
        ),
    )

    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run_id)
            .order_by(QueryRunEvent.sequence)
        )
    )
    assert state.status == QueryRunStatus.FAILED
    assert state.errors[0]["source"] == "vector"
    assert events[-1].event_type == "query.failed"
