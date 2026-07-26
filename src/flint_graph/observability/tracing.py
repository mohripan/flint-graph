"""Span helpers.

Provider setup lives in :mod:`flint_graph.observability.runtime`; this module is
what call sites use to open spans. Span attributes carry identifiers, model
names, and sizes only. Prompts, answers, and document text never become span
attributes: traces travel to the same backends as logs and are subject to the
same rule.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.trace import Tracer

_TRACER_NAME = "flint-graph"


def tracer() -> Tracer:
    return trace.get_tracer(_TRACER_NAME)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(name, attributes=_clean(attributes)) as current:
        yield current


@asynccontextmanager
async def async_span(name: str, **attributes: Any) -> AsyncIterator[trace.Span]:
    with tracer().start_as_current_span(name, attributes=_clean(attributes)) as current:
        yield current


@contextmanager
def span_from_carrier(
    name: str,
    carrier: dict[str, Any] | None,
    **attributes: Any,
) -> Iterator[trace.Span]:
    """Continue a trace whose context was carried through a durable hop.

    The outbox stores a traceparent alongside each message; this is how the relay
    rejoins the trace that produced it instead of starting an orphan.
    """
    context = extract(_string_carrier(carrier or {}))
    with tracer().start_as_current_span(
        name,
        context=context,
        attributes=_clean(attributes),
    ) as current:
        yield current


def _string_carrier(carrier: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in carrier.items()
        if isinstance(value, str | int | float)
    }


def _clean(attributes: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attributes.items() if value is not None}
