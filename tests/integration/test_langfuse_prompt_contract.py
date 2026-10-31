"""Opt-in qualification of the pinned vendor SDK, not FlintGraph integration.

Run in an isolated environment containing langfuse==4.15.0. The real SDK uses a
synthetic HTTP transport; no Langfuse server, model, credentials or tenant data.
"""

import importlib.metadata
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from opentelemetry import trace

pytestmark = pytest.mark.skipif(
    os.getenv("FLINT_GRAPH_LANGFUSE_SDK_PROBE") != "1",
    reason="requires explicit isolated Langfuse SDK 4.15.0 environment",
)


@pytest.fixture
def sdk():
    from langfuse import Langfuse

    assert importlib.metadata.version("langfuse") == "4.15.0"
    clients = []

    def create(handler):
        transport = httpx.Client(transport=httpx.MockTransport(handler))
        client = Langfuse(
            public_key=f"pk-lf-synthetic-{uuid4()}",
            secret_key="sk-lf-synthetic-never-a-real-key",
            base_url="http://langfuse.invalid",
            httpx_client=transport,
            tracing_enabled=False,
        )
        clients.append((client, transport))
        return client

    yield create
    for client, transport in clients:
        client.shutdown()
        transport.close()


def response(request, *, config=None):
    return httpx.Response(
        200,
        request=request,
        json={
            "name": "synthetic",
            "version": 7,
            "type": "text",
            "prompt": "Hello {{name}}",
            "config": config or {"temperature": 0},
            "labels": ["production"],
            "tags": [],
        },
    )


def test_prompt_fetch_works_with_tracing_disabled_and_does_not_replace_app_provider(sdk):
    provider = trace.get_tracer_provider()
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return response(request)

    client = sdk(handler)
    prompt = client.get_prompt("synthetic", label="production", max_retries=0)
    assert prompt.version == 7 and prompt.compile(name="Ren") == "Hello Ren"
    cached = client.get_prompt("synthetic", label="production", max_retries=0)
    assert cached is prompt, "fresh SDK cache returns the same prompt without another GET"
    with client.start_as_current_observation(name="synthetic"):
        pass
    client.flush()
    assert trace.get_tracer_provider() is provider
    assert client._resources.tracer_provider is None
    assert len(calls) == 1 and calls[0][0] == "GET" and "prompts" in calls[0][1]


def test_cold_sdk_cache_blocks_before_fallback_so_it_cannot_be_the_request_path(sdk):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def unavailable(request):
        calls.append(request.url.path)
        entered.set()
        assert release.wait(5)
        return httpx.Response(503, request=request, json={"message": "synthetic outage"})

    client = sdk(unavailable)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.get_prompt, "synthetic", version=7, max_retries=0, fallback="locked fallback"
        )
        try:
            assert entered.wait(5)
            assert not future.done(), "SDK fallback still waits for the cold network fetch"
        finally:
            release.set()
        fallback = future.result(timeout=5)
    assert fallback.is_fallback and fallback.prompt == "locked fallback"
    assert fallback.config == {}, "bare SDK fallback does not retain locked config identity"
    assert len(calls) == 3, "high-level max_retries=0 does not disable generated-client retries"


def test_generated_prompt_api_can_disable_its_internal_retries(sdk):
    from langfuse.api.core.api_error import ApiError

    calls = []

    def unavailable(request):
        calls.append(request.url.path)
        return httpx.Response(503, request=request, json={"message": "synthetic outage"})

    client = sdk(unavailable)
    with pytest.raises(ApiError) as failure:
        client.api.prompts.get(
            "synthetic", version=7, request_options={"max_retries": 0, "timeout_in_seconds": 2}
        )
    assert failure.value.status_code == 503
    assert len(calls) == 1


def test_sdk_compilation_is_permissive_so_typed_rendering_needs_its_own_validation(sdk):
    client = sdk(response)
    prompt = client.get_prompt("synthetic", version=7, max_retries=0)
    assert prompt.compile() == "Hello {{name}}", "missing variables remain unresolved"
    assert prompt.compile(name="Ren", undeclared="ignored") == "Hello Ren"
    assert prompt.compile(name="{{other}}") == "Hello {{other}}", (
        "injected values are not re-rendered"
    )
