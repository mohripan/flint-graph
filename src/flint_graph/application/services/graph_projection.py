from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.enums import EntityStatus, RelationshipStatus
from flint_graph.infrastructure.db.models import CanonicalEntity, EntityRelationship, Tenant

UPSERT_NODES = """
UNWIND $rows AS row
MERGE (e:Entity {id: row.id})
SET e.tenant_id = $tenant_id,
    e.type = row.type,
    e.canonical_name = row.canonical_name,
    e.normalized_name = row.normalized_name,
    e.status = row.status
"""
PRUNE_NODES = """
MATCH (e:Entity {tenant_id: $tenant_id})
WHERE NOT e.id IN $ids
DETACH DELETE e
"""
UPSERT_RELATIONSHIPS = """
UNWIND $rows AS row
MATCH (s:Entity {id: row.subject_id}), (o:Entity {id: row.object_id})
MERGE (s)-[r:RELATED {predicate: row.predicate}]->(o)
SET r.support = row.support, r.tenant_id = $tenant_id
"""
PRUNE_RELATIONSHIPS = """
MATCH (s:Entity {tenant_id: $tenant_id})-[r:RELATED]->(o:Entity)
WHERE NOT (s.id + '|' + r.predicate + '|' + o.id) IN $keys
DELETE r
"""


class SupportsCypher(Protocol):
    async def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class TenantGraph:
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]


async def load_tenant_graph(session: AsyncSession, *, tenant_id: UUID) -> TenantGraph:
    """Read a tenant's projectable graph (active entities and relationships) from PostgreSQL."""

    entity_rows = list(
        (
            await session.execute(
                select(CanonicalEntity).where(
                    CanonicalEntity.tenant_id == tenant_id,
                    CanonicalEntity.status == EntityStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    entities = [
        {
            "id": str(entity.id),
            "type": entity.entity_type.value,
            "canonical_name": entity.canonical_name,
            "normalized_name": entity.normalized_name,
            "status": entity.status.value,
        }
        for entity in entity_rows
    ]

    relationship_rows = list(
        (
            await session.execute(
                select(EntityRelationship).where(
                    EntityRelationship.tenant_id == tenant_id,
                    EntityRelationship.status == RelationshipStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    relationships = [
        {
            "subject_id": str(relationship.subject_entity_id),
            "object_id": str(relationship.object_entity_id),
            "predicate": relationship.predicate,
            "support": relationship.support_count,
        }
        for relationship in relationship_rows
    ]
    return TenantGraph(entities=entities, relationships=relationships)


async def project_tenant_graph(
    client: SupportsCypher, *, tenant_id: UUID, graph: TenantGraph
) -> None:
    """Reconcile a tenant's Neo4j subgraph to match ``graph`` (idempotent).

    Active entities and relationships are upserted with ``MERGE``; nodes and edges
    no longer present in PostgreSQL (including merged-away entities) are pruned.
    Running it repeatedly converges to the same graph, so it doubles as the
    rebuild/reconcile operation.
    """

    tenant = str(tenant_id)
    entity_ids = [row["id"] for row in graph.entities]
    relationship_keys = [
        f"{row['subject_id']}|{row['predicate']}|{row['object_id']}"
        for row in graph.relationships
    ]

    await client.execute(UPSERT_NODES, {"tenant_id": tenant, "rows": graph.entities})
    await client.execute(PRUNE_NODES, {"tenant_id": tenant, "ids": entity_ids})
    await client.execute(
        UPSERT_RELATIONSHIPS, {"tenant_id": tenant, "rows": graph.relationships}
    )
    await client.execute(PRUNE_RELATIONSHIPS, {"tenant_id": tenant, "keys": relationship_keys})


async def reconcile_tenant_graph(
    session: AsyncSession, client: SupportsCypher, *, tenant_id: UUID
) -> TenantGraph:
    graph = await load_tenant_graph(session, tenant_id=tenant_id)
    await project_tenant_graph(client, tenant_id=tenant_id, graph=graph)
    return graph


async def reconcile_all_tenants(session: AsyncSession, client: SupportsCypher) -> int:
    tenant_ids = list((await session.execute(select(Tenant.id))).scalars().all())
    for tenant_id in tenant_ids:
        await reconcile_tenant_graph(session, client, tenant_id=tenant_id)
    return len(tenant_ids)
