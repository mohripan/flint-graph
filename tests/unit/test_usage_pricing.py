"""Cost derivation must be honest: unpriced usage has no cost, not a guess."""

from __future__ import annotations

import pytest

from flint_graph.application.usage import (
    ProviderUsage,
    estimate_cost_micros,
    usage_from_metadata,
)
from flint_graph.config import Settings
from flint_graph.domain.enums import ProviderUsageOperation

_PRICING = {
    "anthropic:claude-opus-4-8": {
        "input_per_million": 15.0,
        "output_per_million": 75.0,
    },
    "ollama:*": {"input_per_million": 0.0, "output_per_million": 0.0},
}


def test_cost_is_derived_from_configured_rates() -> None:
    usage = ProviderUsage(
        operation=ProviderUsageOperation.ANSWER,
        provider="anthropic",
        model="claude-opus-4-8",
        input_tokens=1_000_000,
        output_tokens=200_000,
    )

    # 1M input at $15/M plus 0.2M output at $75/M = $30.00 = 30_000_000 micros.
    assert estimate_cost_micros(usage, _PRICING) == 30_000_000


def test_provider_wildcard_prices_every_model_of_that_provider() -> None:
    usage = ProviderUsage(
        operation=ProviderUsageOperation.ANSWER,
        provider="ollama",
        model="llama3.2",
        input_tokens=5_000,
        output_tokens=1_000,
    )

    assert estimate_cost_micros(usage, _PRICING) == 0


def test_unpriced_model_yields_no_cost_rather_than_a_fabricated_one() -> None:
    usage = ProviderUsage(
        operation=ProviderUsageOperation.ANSWER,
        provider="anthropic",
        model="some-unreleased-model",
        input_tokens=1_000,
        output_tokens=500,
    )

    assert estimate_cost_micros(usage, _PRICING) is None


def test_usage_is_read_from_adapter_metadata() -> None:
    usage = usage_from_metadata(
        {
            "provider": "anthropic",
            "model": "claude-opus-4-8",
            "usage": {"input_tokens": 120, "output_tokens": 34, "duration_ms": 987},
        },
        operation=ProviderUsageOperation.ANSWER,
    )

    assert usage.provider == "anthropic"
    assert usage.model == "claude-opus-4-8"
    assert usage.input_tokens == 120
    assert usage.output_tokens == 34
    assert usage.duration_ms == 987


def test_metadata_without_token_counts_still_produces_a_usage_record() -> None:
    """A deterministic provider consuming zero tokens is a fact worth recording.

    Dropping the row instead would make "ran offline" indistinguishable from
    "never called a model".
    """
    usage = usage_from_metadata(
        {"provider": "deterministic", "model": "deterministic"},
        operation=ProviderUsageOperation.ANSWER,
    )

    assert usage.provider == "deterministic"
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert estimate_cost_micros(usage, _PRICING) is None


def test_missing_metadata_falls_back_to_unknown_identity() -> None:
    usage = usage_from_metadata(None, operation=ProviderUsageOperation.EMBEDDING)

    assert usage.provider == "unknown"
    assert usage.model == "unknown"


def test_missing_real_provider_usage_cannot_be_priced_as_zero() -> None:
    usage = usage_from_metadata(
        {"provider": "ollama", "model": "local-embedder"},
        operation=ProviderUsageOperation.EMBEDDING,
        embedded_item_count=1,
    )

    assert usage.usage_known is False
    assert estimate_cost_micros(usage, _PRICING) is None


@pytest.mark.parametrize("reported", [None, True, -1, 2.5, "12", float("inf"), float("nan"), 2**40])
def test_invalid_embedding_token_usage_is_explicitly_unknown(reported: object) -> None:
    usage = usage_from_metadata(
        {"provider": "ollama", "model": "embed", "usage": {"input_tokens": reported}},
        operation=ProviderUsageOperation.EMBEDDING,
    )
    assert usage.usage_known is False
    assert estimate_cost_micros(usage, _PRICING) is None
    assert usage.input_tokens == 0


def test_embedding_reported_input_has_no_generated_output_tokens() -> None:
    usage = usage_from_metadata(
        {"provider": "ollama", "model": "embed", "usage": {"input_tokens": 42}},
        operation=ProviderUsageOperation.EMBEDDING,
    )
    assert usage.usage_known is True
    assert usage.input_tokens == 42
    assert usage.output_tokens == 0
    assert estimate_cost_micros(usage, _PRICING) == 0


def test_garbage_token_counts_are_ignored_rather_than_trusted() -> None:
    usage = usage_from_metadata(
        {
            "provider": "ollama",
            "model": "llama3.2",
            "usage": {"input_tokens": "lots", "output_tokens": -5},
        },
        operation=ProviderUsageOperation.ANSWER,
    )

    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_pricing_configuration_rejects_malformed_entries() -> None:
    with pytest.raises(ValueError, match="must use '<provider>:<model>' form"):
        Settings(env="test", usage_pricing={"anthropic": {"input_per_million": 1.0}})

    with pytest.raises(ValueError, match="unsupported rate"):
        Settings(env="test", usage_pricing={"anthropic:*": {"per_token": 1.0}})

    with pytest.raises(ValueError, match="must not be negative"):
        Settings(env="test", usage_pricing={"anthropic:*": {"input_per_million": -1.0}})
