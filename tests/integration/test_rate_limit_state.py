"""Bounded fixed-window admission through the public HTTP middleware seam."""

import httpx
import pytest

from flint_graph.config import Settings
from flint_graph.main import create_app


def app_with_limits(**overrides):
    options = dict(
        _env_file=None,
        env="test",
        auth_mode="oidc",
        oidc_issuer="https://identity.example/realm",
        oidc_audience="studio",
        rate_limit_enabled=True,
        rate_limit_requests=2,
        rate_limit_window_seconds=10,
        rate_limit_max_buckets=2,
        otel_enabled=False,
    )
    app = create_app(Settings(**(options | overrides)))

    @app.post("/v1/search/lexical/qualification/{route}")
    async def probe(route: str):
        return {"route": route}

    return app


async def test_general_bucket_capacity_preserves_active_limits_and_recovers_after_expiry(
    monkeypatch,
):
    now = 0.0
    monkeypatch.setattr("flint_graph.api.middleware.monotonic", lambda: now)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_with_limits()), base_url="http://test"
    ) as client:

        async def send(token):
            return await client.post(
                "/v1/search/lexical/qualification/one",
                headers={"Authorization": "Bearer " + token},
            )

        assert (await send("first")).status_code == 200
        assert (await send("second")).status_code == 200
        saturated = await send("third")
        assert saturated.status_code == 429
        assert "capacity" in saturated.json()["detail"].lower()
        assert int(saturated.headers["Retry-After"]) > 0
        assert (await send("first")).status_code == 200
        assert (await send("first")).status_code == 429
        now = 10.0
        assert (await send("third")).status_code == 200
        assert (await send("first")).status_code == 200


async def test_general_oidc_quota_ignores_spoofed_dev_headers_and_route_ids():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=app_with_limits(rate_limit_requests=1, rate_limit_max_buckets=10)
        ),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/v1/search/lexical/qualification/one",
            headers={
                "Authorization": "Bearer fixture-token",
                "X-Dev-User": "one",
                "X-Tenant-ID": "abcd1234-1234-1234-1234-abcd1234abcd",
            },
        )
        equivalent = await client.post(
            "/v1/search/lexical/qualification/two",
            headers={
                "Authorization": "Bearer    fixture-token  ",
                "X-Dev-User": "two",
                "X-Tenant-ID": "ABCD1234123412341234ABCD1234ABCD",
            },
        )
        other_token = await client.post(
            "/v1/search/lexical/qualification/two",
            headers={
                "Authorization": "Bearer other-fixture-token",
                "X-Tenant-ID": "abcd1234-1234-1234-1234-abcd1234abcd",
            },
        )
        other_workspace = await client.post(
            "/v1/search/lexical/qualification/one",
            headers={
                "Authorization": "Bearer fixture-token",
                "X-Tenant-ID": "11111111-1111-4111-8111-111111111111",
            },
        )
    assert first.status_code == 200
    assert equivalent.status_code == 429
    assert other_token.status_code == other_workspace.status_code == 200


async def test_recent_hits_do_not_extend_old_windows_or_discard_newer_quotas(monkeypatch):
    now = 0.0
    monkeypatch.setattr("flint_graph.api.middleware.monotonic", lambda: now)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_with_limits()), base_url="http://test"
    ) as client:

        async def send(token):
            return await client.post(
                "/v1/search/lexical/qualification/one", headers={"Authorization": "Bearer " + token}
            )

        assert (await send("old")).status_code == 200
        now = 1.0
        assert (await send("newer")).status_code == 200
        now = 9.0
        assert (await send("old")).status_code == 200
        now = 10.0
        assert (await send("replacement")).status_code == 200
        assert (await send("newer")).status_code == 200
        assert (await send("newer")).status_code == 429
        now = 11.0
        assert (await send("third")).status_code == 200


async def test_separate_application_instances_do_not_share_rate_limits():
    # This explicitly documents the deployed scope: another replica gets its own quota.
    clients = [
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_limits(rate_limit_requests=1)),
            base_url="http://test",
        )
        for _ in range(2)
    ]
    try:
        for client in clients:
            assert (await client.post("/v1/search/lexical/qualification/one")).status_code == 200
        for client in clients:
            assert (await client.post("/v1/search/lexical/qualification/one")).status_code == 429
    finally:
        for client in clients:
            await client.aclose()


@pytest.mark.parametrize("window", [1, 10])
async def test_general_and_narrative_pools_have_independent_capacity(monkeypatch, window):
    now = 0.0
    monkeypatch.setattr("flint_graph.api.middleware.monotonic", lambda: now)
    app = app_with_limits(narrative_rate_limit_max_buckets=1, rate_limit_window_seconds=window)

    @app.post("/v1/narrative/qualification-capacity")
    async def narrative_probe():
        return {"accepted": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def send(path, token):
            return await client.post(path, headers={"Authorization": "Bearer " + token})

        general, narrative = (
            "/v1/search/lexical/qualification/one",
            "/v1/narrative/qualification-capacity",
        )
        assert (await send(narrative, "n1")).status_code == 200
        assert (await send(narrative, "n2")).status_code == 429
        assert (await send(general, "g1")).status_code == 200
        assert (await send(general, "g2")).status_code == 200
        assert (await send(general, "g3")).status_code == 429
        now = float(window)
        assert (await send(narrative, "n2")).status_code == 200
        assert (await send(general, "g3")).status_code == 200
