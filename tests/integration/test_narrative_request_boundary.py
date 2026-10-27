"""Exercise actual HTTP middleware before narrative body parsing or persistence."""

import asyncio
import tracemalloc

import httpx
import pytest
from fastapi import Request

from flint_graph.api.narrative_body_limit import NarrativeBodyLimitMiddleware
from flint_graph.config import Settings
from flint_graph.main import create_app


@pytest.mark.anyio
async def test_chunked_narrative_request_is_bounded_before_parsing() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            env="test",
            max_upload_bytes=128,
            max_url_intake_bytes=128,
            otel_enabled=False,
        )
    )
    consumed = []

    async def chunks():
        for index in range(10):
            consumed.append(index)
            yield b"x" * 80

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/narrative/projects", content=chunks(), headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 413
    assert consumed == [0, 1]  # Oversized streams aren't drained or parsed.
    assert response.json()["type"] == "urn:flint-graph:error:payload-too-large"


@pytest.mark.anyio
async def test_small_chunked_narrative_body_reaches_json_parser_unchanged() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            env="test",
            max_upload_bytes=128,
            max_url_intake_bytes=128,
            otel_enabled=False,
        )
    )

    @app.post("/v1/narrative/qualification-echo")
    async def echo(request: Request):
        return await request.json()

    async def chunks():
        yield b'{"text":'
        yield b'"original '
        yield b'prose"}'

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/narrative/qualification-echo", content=chunks())

    assert response.status_code == 200
    assert response.json() == {"text": "original prose"}


@pytest.mark.anyio
async def test_false_small_content_length_does_not_bypass_stream_limit() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            env="test",
            max_upload_bytes=128,
            max_url_intake_bytes=128,
            otel_enabled=False,
        )
    )

    async def chunks():
        yield b"x" * 80
        yield b"x" * 80

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/narrative/projects", content=chunks(), headers={"Content-Length": "1"}
        )

    assert response.status_code == 413


@pytest.mark.anyio
async def test_narrative_rate_limit_cannot_be_evaded_by_project_path_or_dev_header() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        auth_mode="oidc",
        oidc_issuer="https://identity.example/realm",
        oidc_audience="studio",
        rate_limit_enabled=True,
        rate_limit_requests=1,
        otel_enabled=False,
    )
    app = create_app(settings)

    @app.post("/v1/narrative/qualification-rate/{project_id}")
    async def middleware_probe(project_id: str):
        return {"project_id": project_id}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/v1/narrative/qualification-rate/one",
            headers={"Authorization": "Bearer invalid-fixture", "X-Dev-User": "one"},
            json={},
        )
        second = await client.post(
            "/v1/narrative/qualification-rate/two",
            headers={"Authorization": "Bearer invalid-fixture", "X-Dev-User": "two"},
            json={},
        )

    assert first.status_code != 429
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0


@pytest.mark.anyio
async def test_rate_buckets_use_the_same_token_and_workspace_normalization_as_auth() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        auth_mode="oidc",
        oidc_issuer="https://identity.example/realm",
        oidc_audience="studio",
        rate_limit_enabled=True,
        rate_limit_requests=1,
        otel_enabled=False,
    )
    app = create_app(settings)

    @app.post("/v1/narrative/qualification-normalization")
    async def probe():
        return {"accepted": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/v1/narrative/qualification-normalization",
            json={},
            headers={
                "Authorization": "Bearer fixture-credential",
                "X-Tenant-ID": "abcd1234-1234-1234-1234-abcd1234abcd",
            },
        )
        equivalent = await client.post(
            "/v1/narrative/qualification-normalization",
            json={},
            headers={
                "Authorization": "Bearer    fixture-credential  ",
                "X-Tenant-ID": "ABCD1234123412341234ABCD1234ABCD",
            },
        )
    assert first.status_code == 200
    assert equivalent.status_code == 429


@pytest.mark.anyio
async def test_narrative_rate_state_is_bounded_without_evicting_active_credentials() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        auth_mode="oidc",
        oidc_issuer="https://identity.example/realm",
        oidc_audience="studio",
        rate_limit_enabled=True,
        rate_limit_requests=10,
        rate_limit_window_seconds=1,
        narrative_rate_limit_max_buckets=2,
        otel_enabled=False,
    )
    app = create_app(settings)

    @app.post("/v1/narrative/qualification-capacity")
    async def probe():
        return {"accepted": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def send(token):
            return await client.post(
                "/v1/narrative/qualification-capacity",
                json={},
                headers={"Authorization": "Bearer " + token},
            )

        assert (await send("first")).status_code == 200
        assert (await send("second")).status_code == 200
        assert (await send("third")).status_code == 429
        assert (await send("first")).status_code == 200
        await asyncio.sleep(1.05)
        assert (await send("third")).status_code == 200


@pytest.mark.anyio
async def test_empty_asgi_frames_cannot_amplify_bounded_request_memory() -> None:
    # ASGI servers choose fragmentation, including empty/tiny frames. Wire bytes
    # alone must not permit unbounded retained Python message dictionaries.
    frames = 0
    seen = bytearray()

    async def receive():
        nonlocal frames
        frames += 1
        if frames <= 50000:
            return {"type": "http.request", "body": b"", "more_body": True}
        return {"type": "http.request", "body": b'{"text":"original"}', "more_body": False}

    async def downstream(_scope, replay, _send):
        while True:
            message = await replay()
            seen.extend(message.get("body", b""))
            if not message.get("more_body", False):
                return

    async def send(_message):
        raise AssertionError("A valid small body should reach the downstream app")

    middleware = NarrativeBodyLimitMiddleware(
        downstream,
        settings=Settings(
            _env_file=None, env="test", max_upload_bytes=128, max_url_intake_bytes=128
        ),
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/narrative/projects",
        "headers": [],
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
    }
    already_tracing = tracemalloc.is_tracing()
    if not already_tracing:
        tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    tracemalloc.reset_peak()
    try:
        await middleware(scope, receive, send)
        peak = tracemalloc.get_traced_memory()[1] - baseline
    finally:
        if not already_tracing:
            tracemalloc.stop()
    assert seen == b'{"text":"original"}'
    assert peak < 1024 * 1024, "Empty frames must not create retained per-frame storage"
