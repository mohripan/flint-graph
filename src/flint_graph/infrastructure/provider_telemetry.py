"""Shared instrumentation for model provider calls.

Every provider adapter wraps its network call in :func:`provider_call` so latency,
errors, and spans look the same whichever provider is configured. Adapters report
usage; they never write to the database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any

from opentelemetry.trace import StatusCode

from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.observability import metrics
from flint_graph.observability.instruments import (
    PROVIDER_CALL_DURATION,
    PROVIDER_CALL_ERRORS,
)
from flint_graph.observability.tracing import tracer


class ProviderCall:
    """Timing handle for one provider call."""

    def __init__(self) -> None:
        self._started = monotonic()
        self.duration_ms: int = 0

    def stop(self) -> int:
        self.duration_ms = int((monotonic() - self._started) * 1000)
        return self.duration_ms


@asynccontextmanager
async def provider_call(
    *,
    provider: str,
    model: str,
    operation: ProviderUsageOperation,
) -> AsyncIterator[ProviderCall]:
    call = ProviderCall()
    attributes = {
        "flint_graph.provider": provider,
        "flint_graph.model": model,
        "flint_graph.operation": operation.value,
    }
    if operation is ProviderUsageOperation.EMBEDDING:
        attributes.update(
            {"openinference.span.kind": "EMBEDDING", "embedding.model_name": model}
        )
    elif operation is ProviderUsageOperation.RERANK:
        attributes.update(
            {"openinference.span.kind": "RERANKER", "reranker.model_name": model}
        )
    else:
        attributes.update(
            {"openinference.span.kind": "LLM", "llm.model_name": model, "llm.provider": provider}
        )
    # OTel's automatic exception recording includes the raw message and stack.
    # Provider errors may echo credentials, prompts or private response text.
    with tracer().start_as_current_span(
        f"provider.{operation.value}",
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        try:
            yield call
        except Exception as error:
            current.set_status(StatusCode.ERROR)
            current.set_attribute("error.type", type(error).__name__[:128])
            metrics.add(
                PROVIDER_CALL_ERRORS,
                **{
                    "flint_graph.provider": provider,
                    "flint_graph.operation": operation.value,
                },
            )
            raise
        finally:
            metrics.record(
                PROVIDER_CALL_DURATION,
                call.stop(),
                **{
                    "flint_graph.provider": provider,
                    "flint_graph.model": model,
                    "flint_graph.operation": operation.value,
                },
            )


def usage_metadata(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: int,
    embedded_item_count: int | None = None,
) -> dict[str, Any]:
    """Build the ``usage`` sub-mapping adapters attach to result metadata."""
    usage: dict[str, Any] = {"duration_ms": duration_ms}
    if input_tokens is not None:
        usage["input_tokens"] = int(input_tokens)
    if output_tokens is not None:
        usage["output_tokens"] = int(output_tokens)
    if embedded_item_count is not None:
        usage["embedded_item_count"] = int(embedded_item_count)
    return usage
