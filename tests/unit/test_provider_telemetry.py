from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.infrastructure.provider_telemetry import provider_call


@pytest.mark.anyio
async def test_error_telemetry_preserves_the_original_provider_failure() -> None:
    failure = ConnectionError("provider unavailable")
    with pytest.raises(ConnectionError) as raised:
        async with provider_call(
            provider="ollama", model="test-model", operation=ProviderUsageOperation.ANSWER
        ):
            raise failure
    assert raised.value is failure


@pytest.fixture
def provider_spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Replace the external OTel tracer boundary, not application collaborators.
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    yield exporter
    provider.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("operation", "kind", "model_key"),
    [
        (ProviderUsageOperation.ANSWER, "LLM", "llm.model_name"),
        (ProviderUsageOperation.FAITHFULNESS, "LLM", "llm.model_name"),
        (ProviderUsageOperation.EXTRACTION, "LLM", "llm.model_name"),
        (ProviderUsageOperation.EMBEDDING, "EMBEDDING", "embedding.model_name"),
        (ProviderUsageOperation.RERANK, "RERANKER", "reranker.model_name"),
    ],
)
async def test_exported_provider_span_has_payload_free_openinference_metadata(
    provider_spans: InMemorySpanExporter,
    operation: ProviderUsageOperation,
    kind: str,
    model_key: str,
) -> None:
    async with provider_call(provider="ollama", model="local-model", operation=operation):
        pass
    spans = provider_spans.get_finished_spans()
    assert len(spans) == 1
    assert dict(spans[0].attributes or {}) == {
        "flint_graph.provider": "ollama",
        "flint_graph.model": "local-model",
        "flint_graph.operation": operation.value,
        "openinference.span.kind": kind,
        model_key: "local-model",
        **({"llm.provider": "ollama"} if kind == "LLM" else {}),
    }


@pytest.mark.anyio
async def test_exported_provider_failure_does_not_leak_message_or_stack(
    provider_spans: InMemorySpanExporter,
) -> None:
    failure = ConnectionError("secret-key PRIVATE DOCUMENT provider response")
    with pytest.raises(ConnectionError) as raised:
        async with provider_call(
            provider="ollama", model="local-model", operation=ProviderUsageOperation.ANSWER
        ):
            raise failure
    assert raised.value is failure
    (exported,) = provider_spans.get_finished_spans()
    assert exported.status.status_code is StatusCode.ERROR
    assert exported.status.description is None
    assert exported.attributes["error.type"] == "ConnectionError"
    assert exported.events == ()
    assert "PRIVATE DOCUMENT" not in exported.to_json()
