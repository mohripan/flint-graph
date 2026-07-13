from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.services.graph_projection import (
    load_tenant_graph,
    reconcile_tenant_graph,
)
from atlas_rag.domain.enums import EntityStatus, EntityType, RelationshipStatus
from atlas_rag.infrastructure.db.models import CanonicalEntity, EntityRelationship, Tenant


class FakeCypherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((query, parameters or {}))
        return []


async def _entity(
    session: AsyncSession,
    tenant: Tenant,
    name: str,
    normalized: str,
    status: EntityStatus = EntityStatus.ACTIVE,
) -> CanonicalEntity:
    entity = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name=name,
        normalized_name=normalized,
        status=status,
        support_count=1,
    )
    session.add(entity)
    await session.flush()
    return entity


async def test_load_tenant_graph_includes_only_active_entities(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="acme")
    db_session.add(tenant)
    await db_session.flush()

    acme = await _entity(db_session, tenant, "Acme", "acme")
    berlin = await _entity(db_session, tenant, "Berlin", "berlin")
    await _entity(db_session, tenant, "Merged", "merged", status=EntityStatus.MERGED)
    db_session.add(
        EntityRelationship(
            tenant_id=tenant.id,
            subject_entity_id=acme.id,
            predicate="hq_in",
            object_entity_id=berlin.id,
            support_count=2,
            provenance=[],
            status=RelationshipStatus.ACTIVE,
        )
    )
    await db_session.flush()

    graph = await load_tenant_graph(db_session, tenant_id=tenant.id)

    normalized_names = {entity["normalized_name"] for entity in graph.entities}
    assert normalized_names == {"acme", "berlin"}
    assert len(graph.relationships) == 1
    assert graph.relationships[0]["predicate"] == "hq_in"
    assert graph.relationships[0]["support"] == 2


async def test_reconcile_tenant_graph_projects_loaded_graph(db_session: AsyncSession) -> None:
    tenant = Tenant(name="acme")
    db_session.add(tenant)
    await db_session.flush()
    await _entity(db_session, tenant, "Acme", "acme")
    await db_session.flush()

    client = FakeCypherClient()
    graph = await reconcile_tenant_graph(db_session, client, tenant_id=tenant.id)

    assert len(graph.entities) == 1
    assert len(client.calls) == 4
    assert client.calls[0][1]["rows"][0]["normalized_name"] == "acme"
