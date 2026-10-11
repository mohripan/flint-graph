"""Opt-in owned local Jaeger qualification; no application or model requests."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_JAEGER_INTEGRATION") != "1",
    reason="requires an explicitly started disposable local Jaeger profile and sender image",
)

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "compose.yaml",
    "-f",
    "compose.jaeger.yaml",
    "--profile",
    "jaeger",
]

SENDER = """
import json
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
provider = TracerProvider(resource=Resource.create(
    {'service.name': 'flint-graph-jaeger-verification'}))
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(
    endpoint='http://jaeger:4317', insecure=True, timeout=5)))
try:
    tracer = provider.get_tracer('jaeger-backend-verification')
    with tracer.start_as_current_span('jaeger.synthetic-parent') as parent:
        with tracer.start_as_current_span('jaeger.synthetic-child') as child:
            result = {'trace_id': f'{parent.get_span_context().trace_id:032x}',
                      'parent_id': f'{parent.get_span_context().span_id:016x}',
                      'child_id': f'{child.get_span_context().span_id:016x}'}
    provider.force_flush()
    print(json.dumps(result))
finally:
    provider.shutdown()
"""


async def command(*args):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        async with asyncio.timeout(45):
            stdout, stderr = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    assert process.returncode == 0, stderr.decode()
    return stdout.decode().strip()


async def emit():
    image = os.environ.get("FLINT_GRAPH_JAEGER_SENDER_IMAGE")
    assert image, "Set FLINT_GRAPH_JAEGER_SENDER_IMAGE to a known locally built app image"
    container = await command(*COMPOSE, "ps", "-q", "jaeger")
    assert container, "Start only the owned Jaeger service before enabling this test"
    networks = json.loads(
        await command(
            "docker", "inspect", container, "--format", "{{json .NetworkSettings.Networks}}"
        )
    )
    assert len(networks) == 1
    network = next(iter(networks))
    return json.loads(
        await command(
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "--entrypoint",
            "/app/.venv/bin/python",
            image,
            "-c",
            SENDER,
        )
    )


def hexadecimal(value):
    # v3 uses OTLP protobuf-JSON bytes; IDs may be base64 rather than hex.
    if len(value) in {16, 32} and all(char in "0123456789abcdefABCDEF" for char in value):
        return value.lower()
    return base64.b64decode(value, validate=True).hex()


def returned_spans(response):
    spans = []
    for line in response.text.splitlines():
        document = json.loads(line)
        assert "error" not in document, document
        for resource in document["result"].get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                spans.extend(scope.get("spans", []))
    return spans


async def get_trace(client, expected):
    deadline = time.monotonic() + 20
    while True:
        response = await client.get(
            f"http://127.0.0.1:16686/api/v3/traces/{expected['trace_id']}",
            params={"raw_traces": "true"},
        )
        if response.status_code == 200:
            spans = returned_spans(response)
            if len(spans) == 2:
                break
        assert time.monotonic() < deadline, "Expected trace not retrievable from v3 API"
        await asyncio.sleep(0.25)
    parent = next(span for span in spans if span["name"] == "jaeger.synthetic-parent")
    child = next(span for span in spans if span["name"] == "jaeger.synthetic-child")
    assert {hexadecimal(span["traceId"]) for span in spans} == {expected["trace_id"]}
    assert hexadecimal(parent["spanId"]) == expected["parent_id"]
    assert hexadecimal(child["spanId"]) == expected["child_id"]
    assert hexadecimal(child["parentSpanId"]) == expected["parent_id"]
    assert not parent.get("parentSpanId") or hexadecimal(parent["parentSpanId"]) == "0" * 16
    return response


@pytest.mark.anyio
async def test_real_jaeger_backend_receives_otlp_parent_child_and_disables_unused_ai_surface():
    expected = await emit()
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        await get_trace(client, expected)
        mcp = await client.post(
            "http://127.0.0.1:16686/api/ai/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "owned-surface-check", "version": "1"},
                },
            },
        )
        assert mcp.status_code in {404, 405}, "Bundled MCP must not be exposed by custom config"
        proxy = await client.post(
            "http://127.0.0.1:16686/api/otlp/v1/traces", json={"resourceSpans": []}
        )
        assert proxy.status_code in {404, 405}, "Query UI must not proxy unfiltered trace ingestion"
    print(
        json.dumps(
            {
                "status": "passed",
                "trace_id": expected["trace_id"],
                "span_count": 2,
                "parent_child": True,
                "mcp_status": mcp.status_code,
            }
        )
    )


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_JAEGER_RESTART_REHEARSAL") != "1",
    reason="explicit opt-in clears ALL traces in the owned ephemeral backend",
)
async def test_owned_ephemeral_jaeger_restart_loses_old_trace_and_accepts_a_new_one():
    expected = await emit()
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        await get_trace(client, expected)
        await command(*COMPOSE, "restart", "jaeger")
        await command(*COMPOSE, "up", "-d", "--no-deps", "--wait", "--wait-timeout", "30", "jaeger")
        lost = await client.get(f"http://127.0.0.1:16686/api/v3/traces/{expected['trace_id']}")
        assert lost.status_code == 404
        fresh = await emit()
        await get_trace(client, fresh)
    print(
        json.dumps(
            {
                "status": "passed",
                "old_trace": expected["trace_id"],
                "old_status": 404,
                "fresh_trace": fresh["trace_id"],
                "fresh_span_count": 2,
            }
        )
    )
