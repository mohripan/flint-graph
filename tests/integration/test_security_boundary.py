from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from flint_graph.api.dependencies import get_session
from flint_graph.config import Settings
from flint_graph.infrastructure.db.base import Base
from flint_graph.main import create_app


async def _client_for_settings(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_override=settings)
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

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.example") as client:
        yield client
    await engine.dispose()


@pytest.mark.anyio
async def test_cors_allows_configured_origin_and_rejects_other_origins() -> None:
    settings = Settings(
        env="test",
        allowed_origins=["https://app.example"],
        trusted_hosts=["api.example"],
    )
    async for client in _client_for_settings(settings):
        allowed = await client.options(
            "/health/live",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        rejected = await client.options(
            "/health/live",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://app.example"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


@pytest.mark.anyio
async def test_trusted_host_rejects_unexpected_host() -> None:
    settings = Settings(
        env="test",
        allowed_origins=["https://app.example"],
        trusted_hosts=["api.example"],
    )
    async for client in _client_for_settings(settings):
        response = await client.get("/health/live", headers={"Host": "evil.example"})

    assert response.status_code == 400


@pytest.mark.anyio
async def test_request_size_limit_returns_problem_json() -> None:
    settings = Settings(
        env="test",
        allowed_origins=["https://app.example"],
        trusted_hosts=["api.example"],
        max_upload_bytes=8,
    )
    async for client in _client_for_settings(settings):
        response = await client.post(
            "/v1/documents/uploads",
            content=b"x" * 9,
            headers={"Content-Type": "application/octet-stream"},
        )

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.anyio
async def test_rate_limit_is_keyed_by_user_and_workspace() -> None:
    settings = Settings(
        env="test",
        allowed_origins=["https://app.example"],
        trusted_hosts=["api.example"],
        rate_limit_enabled=True,
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
    )
    async for client in _client_for_settings(settings):
        first = await client.post(
            "/v1/query-runs",
            json={"query": "one"},
            headers={"X-Dev-User": "user-a", "X-Tenant-ID": "11111111-1111-4111-8111-111111111111"},
        )
        second = await client.post(
            "/v1/query-runs",
            json={"query": "two"},
            headers={"X-Dev-User": "user-a", "X-Tenant-ID": "11111111-1111-4111-8111-111111111111"},
        )
        isolated = await client.post(
            "/v1/query-runs",
            json={"query": "three"},
            headers={"X-Dev-User": "user-a", "X-Tenant-ID": "22222222-2222-4222-8222-222222222222"},
        )

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.headers["content-type"].startswith("application/problem+json")
    assert isolated.status_code != 429
