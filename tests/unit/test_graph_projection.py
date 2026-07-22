from typing import Any
from uuid import UUID

from flint_graph.application.services.graph_projection import (
    PRUNE_NODES,
    PRUNE_RELATIONSHIPS,
    UPSERT_NODES,
    UPSERT_RELATIONSHIPS,
    TenantGraph,
    project_tenant_graph,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")


class FakeCypherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((query, parameters or {}))
        return []


async def test_project_tenant_graph_upserts_then_prunes() -> None:
    client = FakeCypherClient()
    graph = TenantGraph(
        entities=[
            {
                "id": "e1",
                "type": "organization",
                "canonical_name": "Acme",
                "normalized_name": "acme",
                "status": "active",
            },
            {
                "id": "e2",
                "type": "place",
                "canonical_name": "Berlin",
                "normalized_name": "berlin",
                "status": "active",
            },
        ],
        relationships=[
            {"subject_id": "e1", "object_id": "e2", "predicate": "hq_in", "support": 3},
        ],
    )

    await project_tenant_graph(client, tenant_id=TENANT, graph=graph)

    queries = [query for query, _ in client.calls]
    assert queries == [UPSERT_NODES, PRUNE_NODES, UPSERT_RELATIONSHIPS, PRUNE_RELATIONSHIPS]

    assert client.calls[0][1]["rows"] == graph.entities
    assert client.calls[0][1]["tenant_id"] == str(TENANT)
    assert client.calls[1][1]["ids"] == ["e1", "e2"]
    assert client.calls[2][1]["rows"] == graph.relationships
    assert client.calls[3][1]["keys"] == ["e1|hq_in|e2"]


async def test_project_empty_graph_prunes_everything() -> None:
    client = FakeCypherClient()

    await project_tenant_graph(
        client, tenant_id=TENANT, graph=TenantGraph(entities=[], relationships=[])
    )

    # Empty id/key lists cause the prune statements to remove all tenant nodes/edges.
    assert client.calls[1][1]["ids"] == []
    assert client.calls[3][1]["keys"] == []
