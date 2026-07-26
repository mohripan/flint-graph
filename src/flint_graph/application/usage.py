"""Provider usage value objects and cost derivation.

Adapters report what a call consumed; this module turns that into a priced
record. Pricing is configuration, so an unknown provider/model yields a null cost
and a counter increment rather than an invented number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flint_graph.domain.enums import ProviderUsageOperation

MICROS_PER_UNIT = 1_000_000
TOKENS_PER_PRICING_UNIT = 1_000_000

UNKNOWN_PROVIDER = "unknown"
UNKNOWN_MODEL = "unknown"


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """One provider call's consumption, provider-neutral."""

    operation: ProviderUsageOperation
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    embedded_item_count: int = 0
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def usage_from_metadata(
    metadata: dict[str, Any] | None,
    *,
    operation: ProviderUsageOperation,
    duration_ms: int = 0,
    embedded_item_count: int = 0,
) -> ProviderUsage:
    """Build a usage record from an adapter result's metadata.

    Adapters already carry ``provider`` and ``model`` in metadata for provenance;
    Milestone 14 adds an optional ``usage`` sub-mapping with token counts. A
    result without token counts still produces a usage row: a deterministic or
    offline provider consuming zero tokens is a fact worth recording, and a
    missing row would be indistinguishable from a missing call.
    """
    source = metadata or {}
    usage = source.get("usage")
    usage_map: dict[str, Any] = usage if isinstance(usage, dict) else {}
    return ProviderUsage(
        operation=operation,
        provider=_text(source.get("provider"), UNKNOWN_PROVIDER),
        model=_text(source.get("model") or source.get("response_model"), UNKNOWN_MODEL),
        input_tokens=_non_negative_int(usage_map.get("input_tokens")),
        output_tokens=_non_negative_int(usage_map.get("output_tokens")),
        embedded_item_count=embedded_item_count
        or _non_negative_int(usage_map.get("embedded_item_count")),
        duration_ms=duration_ms or _non_negative_int(usage_map.get("duration_ms")),
    )


def pricing_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def estimate_cost_micros(
    usage: ProviderUsage,
    pricing: dict[str, dict[str, float]],
) -> int | None:
    """Derive cost in micros, or None when the provider/model is unpriced.

    A ``<provider>:*`` entry acts as a fallback so an operator does not have to
    enumerate every model of a provider they price uniformly.
    """
    rates = pricing.get(pricing_key(usage.provider, usage.model)) or pricing.get(
        pricing_key(usage.provider, "*")
    )
    if not rates:
        return None
    input_rate = rates.get("input_per_million", 0.0)
    output_rate = rates.get("output_per_million", 0.0)
    cost_units = (
        usage.input_tokens * input_rate + usage.output_tokens * output_rate
    ) / TOKENS_PER_PRICING_UNIT
    return round(cost_units * MICROS_PER_UNIT)


def _text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:200]
    return fallback


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(0, int(value))
