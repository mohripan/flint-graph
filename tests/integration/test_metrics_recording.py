"""Driving real request paths must actually populate the declared instruments.

The registry test proves the instruments are well-formed; this proves they are
wired to call sites, which is the part that silently rots.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from flint_graph.api.dependencies import get_neo4j_client, get_settings
from flint_graph.config import Settings
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.session import get_session
from flint_graph.main import create_app
from flint_graph.observability import metrics
from flint_graph.observability.instruments import (
    AUDIT_EVENTS,
    HTTP_RATE_LIMIT_REJECTIONS,
    HTTP_REQUEST_DURATION,
    HTTP_REQUEST_SIZE_REJECTIONS,
    HTTP_REQUESTS_IN_FLIGHT,
    InstrumentSpec,
)


class _NoOpNeo4jClient:
    async def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def close(self) -> None:
        return None


def _collect(reader: InMemoryMetricReader, spec: InstrumentSpec) -> list[Any]:
    """Return every data point recorded for one instrument."""
    data = reader.get_metrics_data()
    points: list[Any] = []
    for resource_metric in data.resource_metrics if data else []:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == spec.name:
                    points.extend(metric.data.data_points)
    return points


@pytest_asyncio.fixture
async def instrumented(request) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    overrides: dict[str, Any] = getattr(request, "param", {}) or {}
    metrics.reset_metrics()
    settings = Settings(
        env="test",
        metrics_enabled=True,
        metrics_token="scrape-token",
        trusted_hosts=["test", "testserver"],
        **overrides,
    )
    reader = InMemoryMetricReader()
    metrics.configure_metrics(settings, extra_readers=[reader])

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session
            await session.commit()

    app = create_app(settings)
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_neo4j_client] = lambda: _NoOpNeo4jClient()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, reader

    app.dependency_overrides.clear()
    await engine.dispose()
    metrics.reset_metrics()


async def test_api_requests_record_duration_by_route_template(instrumented) -> None:
    client, reader = instrumented

    workspace = (await client.post("/v1/workspaces", json={"name": "Metrics"})).json()
    listed = await client.get(
        "/v1/documents", headers={"X-Tenant-ID": workspace["id"]}
    )
    assert listed.status_code == 200

    points = _collect(reader, HTTP_REQUEST_DURATION)
    routes = {point.attributes["http.route"] for point in points}

    # Route templates, never the literal path with identifiers in it.
    assert "/v1/workspaces" in routes
    assert "/v1/documents" in routes
    for point in points:
        assert point.attributes["http.response.status_class"].endswith("xx")
        assert "tenant" not in "".join(point.attributes)


async def test_unmatched_requests_do_not_leak_paths_into_metric_labels(
    instrumented,
) -> None:
    client, reader = instrumented

    missing = await client.get("/v1/there-is-no-such-route/8f14e45f")
    assert missing.status_code == 404

    routes = {
        point.attributes["http.route"] for point in _collect(reader, HTTP_REQUEST_DURATION)
    }
    assert "unmatched" in routes
    assert not any("8f14e45f" in route for route in routes)


async def test_in_flight_gauge_returns_to_zero_after_requests_complete(
    instrumented,
) -> None:
    client, reader = instrumented

    await client.get("/health/live")

    points = _collect(reader, HTTP_REQUESTS_IN_FLIGHT)
    assert points
    assert points[-1].value == 0


async def test_audit_events_are_counted_by_action_and_outcome(instrumented) -> None:
    client, reader = instrumented

    await client.post("/v1/workspaces", json={"name": "Counted"})

    points = _collect(reader, AUDIT_EVENTS)
    assert points
    actions = {point.attributes["flint_graph.audit.action"] for point in points}
    assert "workspace.created" in actions
    assert all(
        point.attributes["flint_graph.audit.outcome"] == "allowed" for point in points
    )


@pytest.mark.parametrize("instrumented", [{"max_upload_bytes": 8}], indirect=True)
async def test_oversized_request_rejection_is_counted_against_its_route_prefix(
    instrumented,
) -> None:
    client, reader = instrumented

    rejected = await client.post(
        "/v1/documents/uploads",
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000000"},
        content=b"x" * 64,
    )

    assert rejected.status_code == 413
    points = _collect(reader, HTTP_REQUEST_SIZE_REJECTIONS)
    # Attributed to the configured prefix: this middleware runs before routing and
    # sees raw paths, which can embed identifiers.
    assert {point.attributes["http.route"] for point in points} == {
        "/v1/documents/uploads"
    }


@pytest.mark.parametrize(
    "instrumented",
    [{"rate_limit_enabled": True, "rate_limit_requests": 1}],
    indirect=True,
)
async def test_rate_limited_requests_increment_the_rejection_counter(
    instrumented,
) -> None:
    client, reader = instrumented
    workspace = (await client.post("/v1/workspaces", json={"name": "Limited"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}

    first = await client.post(
        "/v1/search/lexical", headers=headers, json={"query": "acme", "limit": 1}
    )
    second = await client.post(
        "/v1/search/lexical", headers=headers, json={"query": "acme", "limit": 1}
    )

    assert 429 in {first.status_code, second.status_code}
    points = _collect(reader, HTTP_RATE_LIMIT_REJECTIONS)
    assert points
    assert {point.attributes["http.route"] for point in points} == {"/v1/search/lexical"}
