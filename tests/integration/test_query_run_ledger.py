from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.query_orchestration import (
    PackedContextRecord,
    QueryCandidate,
    QueryContextPack,
    QueryEntityLink,
)
from flint_graph.application.services.query_runs import (
    QueryRunCreate,
    append_query_run_event,
    create_query_run,
    get_query_run,
    list_query_runs,
    persist_query_candidate,
    persist_query_context_pack,
    persist_query_entity_link,
    record_query_classification,
    transition_query_run,
)
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.domain.enums import QueryRunStatus, RetrievalIndexScope
from flint_graph.domain.errors import ConflictError, NotFoundError
from flint_graph.infrastructure.db.models import (
    QueryContextPackRecord,
    QueryRunCandidate,
    QueryRunEvent,
    Tenant,
)


async def _tenant(session: AsyncSession, name: str = "query-ledger") -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    return tenant


def _index_spec(model: str = "deterministic-query") -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model=model,
        vector_dimension=4,
        embedding_config_hash=f"sha256:{model}",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name="flint_graph_chunks_query",
        neo4j_vector_property_name="embedding",
        opensearch_index_name="flint_graph_chunks_query",
        opensearch_alias_name="flint_graph_chunks_active",
        metadata={"phase": 2},
    )


async def _active_index_version(session: AsyncSession, tenant: Tenant) -> object:
    version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=_index_spec(),
    )
    return await activate_retrieval_index_version(session, version_id=version.id)


async def test_create_query_run_persists_hash_status_and_tenant_boundary(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    other = await _tenant(db_session, "query-ledger-other")
    index_version = await _active_index_version(db_session, tenant)

    run = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="  Where is Acme Corporation headquartered?  ",
            retrieval_index_version_id=index_version.id,
            metadata={"source": "test"},
        ),
    )

    assert run.tenant_id == tenant.id
    assert run.status == QueryRunStatus.QUEUED
    assert run.query_text == "Where is Acme Corporation headquartered?"
    assert run.normalized_query_hash.startswith("sha256:")
    assert run.metadata_ == {"source": "test"}

    assert await get_query_run(db_session, tenant_id=tenant.id, query_run_id=run.id) == run
    with pytest.raises(NotFoundError):
        await get_query_run(db_session, tenant_id=other.id, query_run_id=run.id)


async def test_list_query_runs_is_recent_first_and_tenant_scoped(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session, "query-history")
    other = await _tenant(db_session, "query-history-other")
    index_version = await _active_index_version(db_session, tenant)
    other_index_version = await _active_index_version(db_session, other)
    first = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="First question?",
            retrieval_index_version_id=index_version.id,
        ),
    )
    second = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Second question?",
            retrieval_index_version_id=index_version.id,
        ),
    )
    first.created_at = datetime.now(UTC) - timedelta(minutes=1)
    second.created_at = datetime.now(UTC)
    await db_session.flush()
    await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=other.id,
            query_text="Foreign question?",
            retrieval_index_version_id=other_index_version.id,
        ),
    )

    runs = await list_query_runs(db_session, tenant_id=tenant.id, limit=10)

    assert [run.id for run in runs] == [second.id, first.id]
    assert [run.query_text for run in runs] == ["Second question?", "First question?"]


async def test_query_run_transitions_set_timestamps_and_reject_invalid_moves(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    index_version = await _active_index_version(db_session, tenant)
    run = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Summarize Acme.",
            retrieval_index_version_id=index_version.id,
        ),
    )

    running = await transition_query_run(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        target_status=QueryRunStatus.RUNNING,
        event_type="query.started",
        payload={"node": "initialize_run"},
    )
    completed = await transition_query_run(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        target_status=QueryRunStatus.COMPLETED,
        event_type="query.completed",
        payload={"answer_chars": 42},
        answer_text="Acme is headquartered in Berlin. [c1]",
        answer_citations=[{"citation_id": "c1"}],
    )

    assert running.started_at is not None
    assert completed.status == QueryRunStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.answer_text == "Acme is headquartered in Berlin. [c1]"
    assert completed.answer_citations == [{"citation_id": "c1"}]

    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run.id)
            .order_by(QueryRunEvent.sequence)
        )
    )
    assert [(event.sequence, event.event_type) for event in events] == [
        (1, "query.started"),
        (2, "query.completed"),
    ]

    with pytest.raises(ConflictError):
        await transition_query_run(
            db_session,
            tenant_id=tenant.id,
            query_run_id=run.id,
            target_status=QueryRunStatus.RUNNING,
            event_type="query.started",
            payload={},
        )


async def test_append_query_run_event_uses_monotonic_per_run_sequence(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    index_version = await _active_index_version(db_session, tenant)
    first = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Where is Acme?",
            retrieval_index_version_id=index_version.id,
        ),
    )
    second = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="Where is Berlin?",
            retrieval_index_version_id=index_version.id,
        ),
    )

    first_event = await append_query_run_event(
        db_session,
        tenant_id=tenant.id,
        query_run_id=first.id,
        event_type="retrieval.started",
        payload={"retrievers": ["lexical"]},
    )
    second_event = await append_query_run_event(
        db_session,
        tenant_id=tenant.id,
        query_run_id=first.id,
        event_type="retrieval.completed",
        payload={"candidate_count": 3},
    )
    other_run_event = await append_query_run_event(
        db_session,
        tenant_id=tenant.id,
        query_run_id=second.id,
        event_type="retrieval.started",
        payload={},
    )

    assert first_event.sequence == 1
    assert second_event.sequence == 2
    assert other_run_event.sequence == 1


async def test_record_query_classification_and_summaries(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    index_version = await _active_index_version(db_session, tenant)
    run = await create_query_run(
        db_session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text="How are Acme and Berlin connected?",
            retrieval_index_version_id=index_version.id,
        ),
    )

    await record_query_classification(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        label="relationship",
        strategy="graph_relationship",
        confidence=0.85,
        metadata={"requires_graph": True},
    )
    await persist_query_entity_link(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        link=QueryEntityLink(
            mention_text="Acme",
            status="ambiguous",
            score=0.5,
            method="deterministic",
            candidate_entity_ids=[uuid4(), uuid4()],
            reasons=["multiple aliases"],
        ),
    )
    candidate = await persist_query_candidate(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        candidate=QueryCandidate(
            candidate_id="lexical:chunk:chunk-000001",
            source="lexical",
            candidate_type="chunk",
            tenant_id=tenant.id,
            retrieval_index_version_id=index_version.id,
            source_ids={"chunk_id": "chunk-000001"},
            text_preview="Acme Corporation is headquartered in Berlin.",
            raw_score=7.5,
            normalized_score=0.75,
            rank=1,
        ),
    )
    pack = await persist_query_context_pack(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
        context_pack=QueryContextPack(
            pack_id="pack-1",
            pack_version=1,
            token_budget=100,
            records=[
                PackedContextRecord(
                    context_id="ctx-1",
                    candidate_id="lexical:chunk:chunk-000001",
                    citation_id="c1",
                    text="Acme Corporation is headquartered in Berlin.",
                    token_count=7,
                    source_ids={"chunk_id": "chunk-000001"},
                )
            ],
        ),
    )

    await db_session.flush()
    run_id = run.id
    db_session.expire(run)
    reloaded = await get_query_run(db_session, tenant_id=tenant.id, query_run_id=run_id)
    rows = list(
        await db_session.scalars(
            select(QueryContextPackRecord).where(
                QueryContextPackRecord.query_context_pack_id == pack.id
            )
        )
    )
    candidates = list(
        await db_session.scalars(
            select(QueryRunCandidate).where(QueryRunCandidate.query_run_id == run_id)
        )
    )

    assert reloaded.classification_label == "relationship"
    assert reloaded.retrieval_strategy == "graph_relationship"
    assert reloaded.classification_confidence == 0.85
    assert candidate.dedupe_key == "lexical:chunk:chunk-000001"
    assert candidates[0].text_preview == "Acme Corporation is headquartered in Berlin."
    assert pack.token_budget == 100
    assert rows[0].citation_id == "c1"
    assert rows[0].token_count == 7
