from typing import Any

from flint_graph.processes import retrieval_index_reconcile


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: Any) -> None:
        return None


async def test_retrieval_index_reconcile_process_closes_projection_clients(
    monkeypatch,
) -> None:
    neo4j_client = FakeClient()
    opensearch_client = FakeClient()

    async def fake_reconcile_completed_index_projections(
        session: object,
        *,
        neo4j_client: FakeClient,
        opensearch_client: FakeClient,
    ) -> int:
        return 3

    monkeypatch.setattr(retrieval_index_reconcile, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        retrieval_index_reconcile,
        "SessionFactory",
        lambda: FakeSessionContext(),
    )
    monkeypatch.setattr(
        retrieval_index_reconcile,
        "create_neo4j_client",
        lambda _settings: neo4j_client,
    )
    monkeypatch.setattr(
        retrieval_index_reconcile,
        "create_opensearch_client",
        lambda _settings: opensearch_client,
    )
    monkeypatch.setattr(
        retrieval_index_reconcile,
        "reconcile_completed_index_projections",
        fake_reconcile_completed_index_projections,
    )

    result = await retrieval_index_reconcile.reconcile()

    assert result == 3
    assert neo4j_client.closed
    assert opensearch_client.closed
