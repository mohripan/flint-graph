"""Opt-in real gateway checks: synthetic data only, never a provider request."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Status, StatusCode

from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.infrastructure.provider_telemetry import provider_call

pytestmark = pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_JAEGER_GATEWAY_INTEGRATION") != "1",
    reason="requires explicitly started local Jaeger gateway profile",
)
PHOENIX = os.environ.get("FLINT_GRAPH_JAEGER_GATEWAY_MODE") == "jaeger-phoenix"
SENTINELS = {
    key: f"PRIVATE-GATEWAY-{key.upper()}-SENTINEL"
    for key in ("prompt", "answer", "evidence", "vector", "credential", "exception", "event")
}


def hex_id(value):
    if not value:
        return ""
    if all(char in "0123456789abcdefABCDEF" for char in value):
        return value.lower()
    return base64.b64decode(value, validate=True).hex()


async def emit(monkeypatch):
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "flint-graph-gateway-verification",
                "private.resource": SENTINELS["credential"],
            }
        )
    )
    provider.add_span_processor(
        SimpleSpanProcessor(
            OTLPSpanExporter(
                endpoint="http://127.0.0.1:14317",
                insecure=True,
                timeout=5,
            )
        )
    )
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    try:
        with provider.get_tracer("gateway-verification").start_as_current_span(
            "gateway.synthetic-parent",
            attributes={
                "input.value": SENTINELS["prompt"],
                "output.value": SENTINELS["answer"],
                "retrieval.documents": SENTINELS["evidence"],
                "embedding.vector": SENTINELS["vector"],
                "authorization": SENTINELS["credential"],
                "exception.message": SENTINELS["exception"],
                "exception.stacktrace": SENTINELS["exception"],
            },
        ) as parent:
            expected = {
                "trace_id": f"{parent.get_span_context().trace_id:032x}",
                "parent_id": f"{parent.get_span_context().span_id:016x}",
            }
            parent.add_event("synthetic-event", {"payload": SENTINELS["event"]})
            parent.set_status(Status(StatusCode.ERROR, SENTINELS["exception"]))
            with pytest.raises(ConnectionError):
                async with provider_call(
                    provider="synthetic",
                    model="no-inference",
                    operation=ProviderUsageOperation.ANSWER,
                ):
                    expected["child_id"] = (
                        f"{trace.get_current_span().get_span_context().span_id:016x}"
                    )
                    raise ConnectionError(SENTINELS["exception"])
        assert provider.force_flush()
        return expected
    finally:
        provider.shutdown()


def otlp_spans(document):
    spans = []
    # Tempo uses batches; Jaeger v3 uses resourceSpans.
    for resource in document.get("batches", document.get("resourceSpans", [])):
        for scope in resource.get("scopeSpans", resource.get("instrumentationLibrarySpans", [])):
            spans.extend(scope.get("spans", []))
    return spans


def check_otlp(spans, expected):
    assert len(spans) == 2
    root = next(span for span in spans if span["name"] == "gateway.synthetic-parent")
    child = next(span for span in spans if span["name"] == "provider.answer")
    assert {hex_id(span["traceId"]) for span in spans} == {expected["trace_id"]}
    assert hex_id(root["spanId"]) == expected["parent_id"]
    assert hex_id(child["spanId"]) == expected["child_id"]
    assert hex_id(child["parentSpanId"]) == expected["parent_id"]
    assert hex_id(root.get("parentSpanId")) in {"", "0" * 16}
    assert not any(span.get("events") for span in spans)
    assert not any(span.get("status", {}).get("message") for span in spans)


async def destinations(client, expected, *, jaeger=True, wait_seconds=30):
    deadline = time.monotonic() + wait_seconds
    while True:
        tempo = await client.get(
            "http://127.0.0.1:3000/api/datasources/proxy/uid/tempo/api/traces/"
            + expected["trace_id"]
        )
        responses = [tempo]
        ready = tempo.status_code == 200 and len(otlp_spans(tempo.json())) == 2
        if jaeger:
            response = await client.get(
                "http://127.0.0.1:16686/api/v3/traces/" + expected["trace_id"],
                params={"raw_traces": "true"},
            )
            responses.append(response)
            ready = ready and response.status_code == 200
            if response.status_code == 200:
                spans = [
                    span
                    for line in response.text.splitlines()
                    for span in otlp_spans(json.loads(line)["result"])
                ]
                ready = ready and len(spans) == 2
        matched = []
        if PHOENIX:
            phoenix = await client.get("http://127.0.0.1:6006/v1/projects/flint-graph/spans")
            responses.append(phoenix)
            if phoenix.status_code == 200:
                matched = [
                    span
                    for span in phoenix.json()["data"]
                    if span["context"]["trace_id"] == expected["trace_id"]
                ]
            ready = ready and len(matched) == 2
        if ready:
            break
        assert time.monotonic() < deadline, "Synthetic trace did not reach selected destinations"
        await asyncio.sleep(0.25)
    check_otlp(otlp_spans(tempo.json()), expected)
    if jaeger:
        check_otlp(spans, expected)
    for response in responses:
        assert all(sentinel not in response.text for sentinel in SENTINELS.values())
    if PHOENIX:
        root = next(span for span in matched if span["name"] == "gateway.synthetic-parent")
        child = next(span for span in matched if span["name"] == "provider.answer")
        assert root["context"]["span_id"] == expected["parent_id"]
        assert child["context"]["span_id"] == expected["child_id"]
        assert child["parent_id"] == expected["parent_id"]
        assert root["parent_id"] in {None, "", "0" * 16}
        assert child["span_kind"] == "LLM"
        assert child["attributes"]["llm.model_name"] == "no-inference"
        assert not child["status_message"]


async def command(*args):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    assert process.returncode == 0, stderr.decode()
    return stdout.decode().strip()


def metric(text, name):
    return sum(
        float(line.rsplit(" ", 1)[1])
        for line in text.splitlines()
        if re.match(rf"{name}(?:_total)?\{{", line) and 'exporter="otlp/jaeger"' in line
    )


@pytest.mark.anyio
async def test_real_gateway_destinations_privacy_structure_and_grafana(monkeypatch):
    expected = await emit(monkeypatch)
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        await destinations(client, expected)
        datasource = await client.get(
            "http://127.0.0.1:3000/api/datasources/uid/flint-graph-jaeger"
        )
        assert datasource.status_code == 200
        config = datasource.json()
        assert config["type"] == "jaeger" and config["url"] == "http://jaeger:16686"
        assert config["readOnly"] and not config["isDefault"]
        proxied = await client.get(
            "http://127.0.0.1:3000/api/datasources/proxy/uid/"
            "flint-graph-jaeger/api/v3/traces/" + expected["trace_id"],
            params={"raw_traces": "true"},
        )
        assert proxied.status_code == 200
        check_otlp(
            [
                span
                for line in proxied.text.splitlines()
                for span in otlp_spans(json.loads(line)["result"])
            ],
            expected,
        )
        assert all(value not in proxied.text for value in SENTINELS.values())
    print(
        json.dumps(
            {
                "status": "passed",
                "trace": expected,
                "phoenix": PHOENIX,
                "privacy": True,
                "grafana_proxy": True,
            }
        )
    )


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_JAEGER_DATASOURCE_ROLLBACK") != "1",
    reason="requires explicit base-only Grafana provisioning rollback",
)
async def test_optional_datasource_rollback_preserves_tempo_and_operations():
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        removed = await client.get("http://127.0.0.1:3000/api/datasources/uid/flint-graph-jaeger")
        assert removed.status_code == 404, "Optional datasource must be pruned on rollback"
        tempo = await client.get("http://127.0.0.1:3000/api/datasources/uid/tempo")
        metrics = await client.get("http://127.0.0.1:3000/api/datasources/uid/flint-graph-metrics")
        assert tempo.status_code == metrics.status_code == 200
        assert tempo.json()["type"] == "tempo"
        assert metrics.json()["type"] == "prometheus"


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_JAEGER_PAUSE_REHEARSAL") != "1",
    reason="explicit opt-in briefly pauses only the owned Jaeger backend",
)
async def test_stalled_jaeger_does_not_block_other_destinations_and_recovers(monkeypatch):
    container = await command(
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.jaeger.yaml",
        "--profile",
        "jaeger",
        "ps",
        "-q",
        "jaeger",
    )
    assert container and "\n" not in container
    inspected = json.loads(await command("docker", "inspect", container))[0]
    assert inspected["Config"]["Labels"]["com.docker.compose.service"] == "jaeger"
    assert inspected["Config"]["Labels"]["com.docker.compose.project"] == "flint-graph"
    assert not inspected["State"]["Paused"] and inspected["State"]["Running"]
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        before = (await client.get("http://127.0.0.1:18888/metrics")).text
        assert metric(before, "otelcol_exporter_queue_capacity") == 64
        await command("docker", "pause", container)
        try:
            started = time.monotonic()
            expected = await emit(monkeypatch)
            await destinations(client, expected, jaeger=False, wait_seconds=10)
            delivery_seconds = time.monotonic() - started
            deadline = time.monotonic() + 30
            while True:
                metrics = (await client.get("http://127.0.0.1:18888/metrics")).text
                failed = metric(metrics, "otelcol_exporter_send_failed_spans")
                queue = metric(metrics, "otelcol_exporter_queue_size")
                in_flight = metric(metrics, "otelcol_exporter_in_flight_requests")
                assert metric(metrics, "otelcol_exporter_queue_capacity") == 64
                if (
                    failed >= metric(before, "otelcol_exporter_send_failed_spans") + 2
                    and queue == 0
                    and in_flight == 0
                ):
                    break
                assert time.monotonic() < deadline, "Expected expired Jaeger export/drop metrics"
                assert queue <= 64
                await asyncio.sleep(0.25)
        finally:
            await command("docker", "unpause", container)
        # Expired export is deliberately lost at this destination, not replayed.
        lost = await client.get("http://127.0.0.1:16686/api/v3/traces/" + expected["trace_id"])
        assert lost.status_code == 404
        fresh = await emit(monkeypatch)
        await destinations(client, fresh)
    print(
        json.dumps(
            {
                "status": "passed",
                "stalled_trace": expected["trace_id"],
                "other_delivery_seconds": delivery_seconds,
                "failed_spans": failed,
                "queue_after_expiry": queue,
                "fresh_trace": fresh["trace_id"],
            }
        )
    )
