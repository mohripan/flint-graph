import os
from uuid import UUID, uuid4

import pytest

from atlas_rag.application.services.graph_projection import TenantGraph, project_tenant_graph
from atlas_rag.config import Settings
from atlas_rag.infrastructure.neo4j import Neo4jClient, create_neo4j_client

pytestmark = pytest.mark.skipif(
    not os.getenv("ATLAS_NEO4J_INTEGRATION"),
    reason="Set ATLAS_NEO4J_INTEGRATION=1 with a running Neo4j to run this test.",
)


def _node(entity_id: str, name: str, normalized: str) -> dict[str, str]:
    return {
        "id": entity_id,
        "type": "organization",
        "canonical_name": name,
        "normalized_name": normalized,
        "status": "active",
    }


async def _node_count(client: Neo4jClient, tenant: UUID) -> int:
    rows = await client.execute(
        "MATCH (e:Entity {tenant_id: $t}) RETURN count(e) AS c", {"t": str(tenant)}
    )
    return int(rows[0]["c"])


async def _rel_count(client: Neo4jClient, tenant: UUID) -> int:
    rows = await client.execute(
        "MATCH (:Entity {tenant_id: $t})-[r:RELATED]->() RETURN count(r) AS c",
        {"t": str(tenant)},
    )
    return int(rows[0]["c"])


async def test_projection_is_idempotent_reflects_merge_and_reconciles() -> None:
    client = create_neo4j_client(Settings())
    tenant = uuid4()
    e1, e2 = str(uuid4()), str(uuid4())
    full = TenantGraph(
        entities=[_node(e1, "Acme", "acme"), _node(e2, "Berlin", "berlin")],
        relationships=[
            {"subject_id": e1, "object_id": e2, "predicate": "hq_in", "support": 2}
        ],
    )
    try:
        await project_tenant_graph(client, tenant_id=tenant, graph=full)
        assert await _node_count(client, tenant) == 2
        assert await _rel_count(client, tenant) == 1

        # Idempotent: a second projection of the same graph changes nothing.
        await project_tenant_graph(client, tenant_id=tenant, graph=full)
        assert await _node_count(client, tenant) == 2
        assert await _rel_count(client, tenant) == 1

        # Merge reflected: Berlin merged away -> its node and the edge are pruned.
        merged = TenantGraph(entities=[_node(e1, "Acme", "acme")], relationships=[])
        await project_tenant_graph(client, tenant_id=tenant, graph=merged)
        assert await _node_count(client, tenant) == 1
        assert await _rel_count(client, tenant) == 0

        # Reconcile: a manual deletion in Neo4j is repaired by re-projecting.
        await client.execute("MATCH (e:Entity {id: $id}) DETACH DELETE e", {"id": e1})
        assert await _node_count(client, tenant) == 0
        await project_tenant_graph(client, tenant_id=tenant, graph=merged)
        assert await _node_count(client, tenant) == 1
    finally:
        await client.execute(
            "MATCH (e:Entity {tenant_id: $t}) DETACH DELETE e", {"t": str(tenant)}
        )
        await client.close()
