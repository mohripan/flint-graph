from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.query_planning import (
    classify_query_run,
    link_query_entities,
)
from flint_graph.application.services.query_runs import QueryRunCreate, create_query_run
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.domain.enums import AliasSource, EntityStatus, EntityType, RetrievalIndexScope
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    QueryRunEvent,
    QueryRunLinkedEntity,
    Tenant,
)


async def _tenant(session: AsyncSession, name: str = "query-planning") -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    return tenant


def _index_spec(model: str = "deterministic-query-planning") -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model=model,
        vector_dimension=4,
        embedding_config_hash=f"sha256:{model}",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name=f"flint_graph_chunks_{model}",
        neo4j_vector_property_name="embedding",
        opensearch_index_name=f"flint_graph_chunks_{model}",
        opensearch_alias_name="flint_graph_chunks_active",
    )


async def _active_index_id(session: AsyncSession, tenant: Tenant) -> object:
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
) -> object:
    return await create_query_run(
        session,
        QueryRunCreate(
            tenant_id=tenant.id,
            query_text=query_text,
            retrieval_index_version_id=await _active_index_id(session, tenant),
        ),
    )


async def _entity(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str,
    normalized: str,
    entity_type: EntityType = EntityType.ORGANIZATION,
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


async def test_classify_query_run_persists_result_and_appends_event(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    run = await _query_run(
        db_session,
        tenant,
        "How are Acme Corporation and Berlin connected?",
    )

    classification = await classify_query_run(
        db_session,
        tenant_id=tenant.id,
        query_run_id=run.id,
    )

    events = list(
        await db_session.scalars(
            select(QueryRunEvent)
            .where(QueryRunEvent.query_run_id == run.id)
            .order_by(QueryRunEvent.sequence)
        )
    )
    await db_session.refresh(run)
    assert classification.label == "relationship"
    assert run.classification_label == "relationship"
    assert run.retrieval_strategy == "graph_relationship"
    assert run.classification_confidence == 0.85
    assert run.classification_metadata["requires_graph_expansion"] is True
    assert [(event.sequence, event.event_type) for event in events] == [
        (1, "query.classified")
    ]


async def test_link_query_entities_accepts_exact_alias_match(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    entity = await _entity(
        db_session,
        tenant,
        name="Acme Corporation",
        normalized="acme corporation",
        alias="Acme",
    )
    run = await _query_run(db_session, tenant, "Where is Acme headquartered?")

    links = await link_query_entities(db_session, tenant_id=tenant.id, query_run_id=run.id)

    rows = list(
        await db_session.scalars(
            select(QueryRunLinkedEntity).where(QueryRunLinkedEntity.query_run_id == run.id)
        )
    )
    assert [(link.mention_text, link.status, link.canonical_entity_id) for link in links] == [
        ("Acme", "accepted", entity.id)
    ]
    assert rows[0].canonical_entity_id == entity.id
    assert rows[0].method == "deterministic-exact"


async def test_link_query_entities_marks_multiple_exact_matches_ambiguous(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    first = await _entity(
        db_session,
        tenant,
        name="Acme Robotics",
        normalized="acme robotics",
        alias="Acme",
    )
    second = await _entity(
        db_session,
        tenant,
        name="Acme Research",
        normalized="acme research",
        alias="Acme",
    )
    run = await _query_run(db_session, tenant, "Tell me about Acme.")

    links = await link_query_entities(db_session, tenant_id=tenant.id, query_run_id=run.id)

    assert len(links) == 1
    assert links[0].status == "ambiguous"
    assert set(links[0].candidate_entity_ids) == {first.id, second.id}
    row = await db_session.scalar(
        select(QueryRunLinkedEntity).where(QueryRunLinkedEntity.query_run_id == run.id)
    )
    assert row is not None
    assert set(row.candidate_entity_ids) == {str(first.id), str(second.id)}


async def test_link_query_entities_persists_rejected_unmatched_mentions(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    run = await _query_run(db_session, tenant, "What does Contoso own?")

    links = await link_query_entities(db_session, tenant_id=tenant.id, query_run_id=run.id)

    assert [(link.mention_text, link.status) for link in links] == [("Contoso", "rejected")]
    row = await db_session.scalar(
        select(QueryRunLinkedEntity).where(QueryRunLinkedEntity.query_run_id == run.id)
    )
    assert row is not None
    assert row.mention_text == "Contoso"
    assert row.status == "rejected"
    assert row.canonical_entity_id is None


async def test_link_query_entities_does_not_link_foreign_tenant_aliases(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    other = await _tenant(db_session, "query-planning-other")
    await _entity(
        db_session,
        other,
        name="Acme Corporation",
        normalized="acme corporation",
        alias="Acme",
    )
    run = await _query_run(db_session, tenant, "Where is Acme headquartered?")

    links = await link_query_entities(db_session, tenant_id=tenant.id, query_run_id=run.id)

    assert [(link.mention_text, link.status) for link in links] == [("Acme", "rejected")]
