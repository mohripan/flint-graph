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

from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.observability import metrics
from flint_graph.observability.instruments import (
    PROVIDER_CALL_DURATION,
    PROVIDER_CALL_ERRORS,
)
from flint_graph.observability.tracing import async_span


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
    async with async_span(
        f"provider.{operation.value}",
        **{
            "flint_graph.provider": provider,
            "flint_graph.model": model,
            "flint_graph.operation": operation.value,
        },
    ):
        try:
            yield call
        except Exception:
            metrics.add(
                PROVIDER_CALL_ERRORS,
                **{
                    "flint_graph.provider": provider,
                    "flint_graph.model": model,
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
