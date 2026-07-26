"""The instrument registry is a stability contract.

Dashboards and alert rules in ``ops/observability`` are written against these
names and attribute keys, so the registry is asserted rather than trusted.
"""

from __future__ import annotations

import pytest

from flint_graph.config import Settings
from flint_graph.observability import metrics
from flint_graph.observability.instruments import (
    ALL_INSTRUMENTS,
    HTTP_REQUEST_DURATION,
    INSTRUMENTS_BY_NAME,
    InstrumentKind,
)

_FORBIDDEN_ATTRIBUTE_FRAGMENTS = ("tenant", "user", "workspace", "query_run", "document")


def test_every_instrument_has_a_stable_name_unit_and_description() -> None:
    for instrument in ALL_INSTRUMENTS:
        assert instrument.name.startswith("flint_graph."), instrument.name
        assert instrument.unit, instrument.name
        assert instrument.description.endswith("."), instrument.name
        assert instrument.kind in set(InstrumentKind)


def test_instrument_names_are_unique() -> None:
    assert len(INSTRUMENTS_BY_NAME) == len(ALL_INSTRUMENTS)


def test_no_instrument_carries_unbounded_identity_attributes() -> None:
    """Per-workspace breakdown belongs to the usage and audit tables.

    Identifiers as metric labels are the standard way to melt a metrics backend,
    so the registry forbids them by test rather than by convention.
    """
    for instrument in ALL_INSTRUMENTS:
        for key in instrument.attribute_keys:
            lowered = key.casefold()
            assert not any(
                fragment in lowered for fragment in _FORBIDDEN_ATTRIBUTE_FRAGMENTS
            ), f"{instrument.name} declares identity attribute {key}"


def test_recording_rejects_unexpected_attributes() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        metrics.record(
            HTTP_REQUEST_DURATION,
            1.0,
            **{
                "http.route": "/v1/documents",
                "http.request.method": "GET",
                "http.response.status_class": "2xx",
                "tenant.id": "leaky",
            },
        )


def test_recording_rejects_missing_attributes() -> None:
    with pytest.raises(ValueError, match="missing"):
        metrics.record(HTTP_REQUEST_DURATION, 1.0, **{"http.route": "/v1/documents"})


def test_recording_is_inert_when_metrics_are_disabled() -> None:
    settings = Settings(env="test", metrics_enabled=False, otel_enabled=False)
    assert metrics.configure_metrics(settings) is False
    assert metrics.metrics_active() is False
    # Attribute validation still runs, so a bad call site fails in tests even
    # though nothing is exported.
    metrics.record_http_request(
        route="/v1/documents", method="GET", status_code=200, duration_ms=1.0
    )


def test_status_class_buckets_status_codes() -> None:
    assert metrics.status_class(200) == "2xx"
    assert metrics.status_class(404) == "4xx"
    assert metrics.status_class(503) == "5xx"
