"""Opt-in real OTLP fan-out/privacy check; no model calls or corpus mutations."""

from __future__ import annotations

import asyncio
import os
import time

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.infrastructure.provider_telemetry import provider_call

pytestmark = pytest.mark.skipif(
    os.environ.get("FLINT_GRAPH_AI_OBSERVABILITY_INTEGRATION") != "1",
    reason="requires the explicitly started local AI observability profile",
)


@pytest.mark.anyio
async def test_real_gateway_exports_provider_trace_to_phoenix_and_tempo_without_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "PRIVATE-OBSERVABILITY-SMOKE-CONTENT"
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": "flint-graph-local-smoke", "private.resource": sentinel}
        )
    )
    provider.add_span_processor(
        SimpleSpanProcessor(
            OTLPSpanExporter(endpoint="http://127.0.0.1:14317", insecure=True, timeout=10)
        )
    )
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    try:
        with provider.get_tracer("local-smoke").start_as_current_span(
            "telemetry.local-smoke",
            attributes={"input.value": sentinel, "authorization": sentinel},
        ) as parent:
            trace_id = f"{parent.get_span_context().trace_id:032x}"
            parent.add_event("untrusted-payload", {"content": sentinel})
            # No provider request is made; only its real telemetry wrapper runs.
            with pytest.raises(ConnectionError):
                async with provider_call(
                    provider="local-smoke",
                    model="smoke-no-inference",
                    operation=ProviderUsageOperation.ANSWER,
                ):
                    raise ConnectionError(sentinel)
        provider.force_flush()
        deadline = time.monotonic() + 45
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            while True:
                phoenix = await client.get("http://127.0.0.1:6006/v1/projects/flint-graph/spans")
                tempo = await client.get(
                    "http://127.0.0.1:3000/api/datasources/proxy/uid/tempo/api/traces/"
                    + trace_id
                )
                if phoenix.status_code == 200 and tempo.status_code == 200:
                    spans = phoenix.json()["data"]
                    matched = [
                        span for span in spans if span["context"]["trace_id"] == trace_id
                    ]
                    if len(matched) == 2:
                        break
                assert time.monotonic() < deadline, "Trace did not arrive in both backends"
                await asyncio.sleep(0.5)
        assert sentinel not in phoenix.text
        assert sentinel not in tempo.text
        llm_span = next(span for span in matched if span["name"] == "provider.answer")
        assert llm_span["span_kind"] == "LLM"
        assert llm_span["status_code"] == "ERROR"
        assert not llm_span["status_message"]
        assert llm_span["attributes"]["llm.model_name"] == "smoke-no-inference"
    finally:
        provider.shutdown()
