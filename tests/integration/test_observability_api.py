"""Operational endpoints: metrics scrape, usage summary, and deep readiness.

The metrics tests double as Milestone 13 regression cover: the scrape endpoint is
an operator surface and must not become a hole in the public API boundary.
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

from flint_graph.api.dependencies import (
    get_neo4j_client,
    get_readiness_checker,
    get_settings,
)
from flint_graph.api.middleware import FixedWindowRateLimitMiddleware
from flint_graph.application.services.health_probes import ReadinessChecker
from flint_graph.config import Settings
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.session import get_session
from flint_graph.main import create_app
from flint_graph.observability import metrics
from flint_graph.observability.instruments import HTTP_REQUEST_DURATION


class _NoOpNeo4jClient:
    async def execute(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def close(self) -> None:
        return None


@pytest_asyncio.fixture
async def metrics_client() -> AsyncIterator[tuple[httpx.AsyncClient, Settings, Any]]:
    """An app with the scrape endpoint enabled and an in-memory metric reader."""
    metrics.reset_metrics()
    settings = Settings(
        env="test",
        metrics_enabled=True,
        metrics_token="scrape-token",
        allowed_origins=["https://app.example"],
        trusted_hosts=["test", "testserver"],
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
        yield client, settings, app

    app.dependency_overrides.clear()
    await engine.dispose()
    metrics.reset_metrics()


async def test_scrape_endpoint_requires_the_configured_token(metrics_client) -> None:
    client, _settings, _app = metrics_client

    unauthorized = await client.get("/metrics")
    wrong_token = await client.get(
        "/metrics", headers={"Authorization": "Bearer nope"}
    )
    authorized = await client.get(
        "/metrics", headers={"Authorization": "Bearer scrape-token"}
    )

    assert unauthorized.status_code == 401
    assert unauthorized.headers["content-type"].startswith("application/problem+json")
    assert wrong_token.status_code == 401
    assert authorized.status_code == 200
    assert authorized.headers["content-type"].startswith("text/plain")


async def test_scrape_output_contains_api_request_metrics(metrics_client) -> None:
    client, _settings, _app = metrics_client

    await client.get("/health/live")
    scraped = await client.get(
        "/metrics", headers={"Authorization": "Bearer scrape-token"}
    )
    body = scraped.text

    # Prometheus renames dots to underscores; the registry name is the contract.
    prometheus_name = HTTP_REQUEST_DURATION.name.replace(".", "_")
    assert prometheus_name in body
    assert 'http_route="/health/live"' in body
    assert 'http_response_status_class="2xx"' in body
    # Workspace and user identity must never reach metric labels.
    assert "tenant_id" not in body


async def test_scrape_endpoint_is_absent_when_metrics_are_disabled(client) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 404


async def test_scrape_endpoint_is_not_rate_limited(metrics_client) -> None:
    """Rate limiting the scrape endpoint would blind the operator under load."""
    assert not any(
        path.startswith("/metrics")
        for path in FixedWindowRateLimitMiddleware.EXPENSIVE_PATHS
    )
    client, _settings, _app = metrics_client
    for _ in range(3):
        response = await client.get(
            "/metrics", headers={"Authorization": "Bearer scrape-token"}
        )
        assert response.status_code == 200


async def test_readiness_returns_503_problem_json_naming_the_failed_dependency(
    metrics_client,
) -> None:
    client, _settings, app = metrics_client

    async def failing(_session: object, _settings: Settings) -> str | None:
        raise ConnectionRefusedError("neo4j is down")

    app.dependency_overrides[get_readiness_checker] = lambda: ReadinessChecker(
        Settings(
            env="test",
            readiness_required_dependencies=["postgres", "neo4j"],
            readiness_cache_seconds=0.0,
        ),
        probes={
            "postgres": _ok_probe,
            "neo4j": failing,
        },
    )

    ready = await client.get("/health/ready")
    live = await client.get("/health/live")

    assert ready.status_code == 503
    assert ready.headers["content-type"].startswith("application/problem+json")
    body = ready.json()
    assert body["type"] == "urn:flint-graph:error:dependency-unavailable"
    assert "neo4j" in body["detail"]
    assert body["dependencies"]["neo4j"]["required"] is True
    assert body["dependencies"]["postgres"]["status"] == "ok"
    # Liveness stays green so the platform does not restart a healthy process.
    assert live.status_code == 200

    app.dependency_overrides.pop(get_readiness_checker, None)


async def _ok_probe(_session: object, _settings: Settings) -> str | None:
    return None


@pytest.mark.parametrize("group_by", ["day", "operation", "model"])
async def test_usage_endpoint_returns_a_summary_for_each_grouping(
    client, group_by: str
) -> None:
    workspace = (
        await client.post("/v1/workspaces", json={"name": "Usage"})
    ).json()

    response = await client.get(
        "/v1/usage",
        headers={"X-Tenant-ID": workspace["id"]},
        params={"group_by": group_by},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["group_by"] == group_by
    assert body["currency"] == "USD"
    assert body["rows"] == []
    assert body["totals"]["event_count"] == 0
    assert body["totals"]["estimated_cost_micros"] is None


async def test_usage_endpoint_requires_admin_access(client, oidc_auth) -> None:
    owner_token = oidc_auth("owner-1")
    viewer_token = oidc_auth("viewer-1")
    workspace = (
        await client.post(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Usage"},
        )
    ).json()
    await client.post(
        f"/v1/workspaces/{workspace['id']}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "oidc_subject": "viewer-1",
            "email": "viewer-1@example.com",
            "display_name": "Viewer One",
            "role": "viewer",
        },
    )

    viewer = await client.get(
        "/v1/usage",
        headers={
            "Authorization": f"Bearer {viewer_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )
    owner = await client.get(
        "/v1/usage",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "X-Tenant-ID": workspace["id"],
        },
    )

    assert viewer.status_code == 403
    assert owner.status_code == 200
