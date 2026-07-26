"""Metric recording facade.

Application and infrastructure code records through the functions here and never
imports OpenTelemetry directly. That keeps three properties true:

* every metric is declared in :mod:`flint_graph.observability.instruments`;
* attribute keys are validated at record time, so cardinality stays bounded;
* with metrics disabled the whole layer is inert and allocates nothing.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any

from flint_graph.config import Settings
from flint_graph.observability.instruments import (
    ALL_INSTRUMENTS,
    HTTP_RATE_LIMIT_REJECTIONS,
    HTTP_REQUEST_DURATION,
    HTTP_REQUEST_SIZE_REJECTIONS,
    HTTP_REQUESTS_IN_FLIGHT,
    InstrumentKind,
    InstrumentSpec,
)
from flint_graph.observability.tracing import async_span

_METER_NAME = "flint-graph"

_lock = threading.Lock()
_state: _MetricsState | None = None


class _MetricsState:
    """Holds the process-wide meter provider and its instantiated instruments."""

    def __init__(self, provider: Any, readers: list[Any], owns_prometheus: bool) -> None:
        self.provider = provider
        self.readers = readers
        self.owns_prometheus = owns_prometheus
        meter = provider.get_meter(_METER_NAME)
        self.instruments: dict[str, Any] = {
            spec.name: _create_instrument(meter, spec) for spec in ALL_INSTRUMENTS
        }


def _create_instrument(meter: Any, spec: InstrumentSpec) -> Any:
    match spec.kind:
        case InstrumentKind.COUNTER:
            return meter.create_counter(
                spec.name, unit=spec.unit, description=spec.description
            )
        case InstrumentKind.HISTOGRAM:
            return meter.create_histogram(
                spec.name, unit=spec.unit, description=spec.description
            )
        case InstrumentKind.GAUGE:
            return meter.create_gauge(
                spec.name, unit=spec.unit, description=spec.description
            )


def configure_metrics(
    settings: Settings,
    *,
    extra_readers: list[Any] | None = None,
) -> bool:
    """Install the process meter provider. Returns True when metrics are active.

    Safe to call from every process entry point; the second call in a process is a
    no-op. ``extra_readers`` lets tests attach an in-memory reader.
    """
    global _state
    readers: list[Any] = list(extra_readers or [])
    owns_prometheus = False

    with _lock:
        if _state is not None:
            return True

        if settings.otel_enabled:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            readers.append(
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(
                        endpoint=settings.otel_exporter_otlp_endpoint,
                        insecure=settings.otel_exporter_otlp_insecure,
                    ),
                    export_interval_millis=settings.otel_metric_export_interval_millis,
                )
            )
        if settings.metrics_enabled:
            from opentelemetry.exporter.prometheus import PrometheusMetricReader

            readers.append(PrometheusMetricReader())
            owns_prometheus = True

        if not readers:
            return False

        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource

        provider = MeterProvider(
            resource=Resource.create(
                {
                    "service.name": settings.service_name,
                    "service.version": settings.service_version,
                    "deployment.environment.name": settings.env,
                }
            ),
            metric_readers=readers,
        )
        _state = _MetricsState(provider, readers, owns_prometheus)
        return True


def reset_metrics() -> None:
    """Tear down the meter provider. Intended for tests and process shutdown."""
    global _state
    with _lock:
        state = _state
        _state = None
    if state is None:
        return
    # Shut the provider down first: its readers unregister their own collectors,
    # and unregistering ahead of that makes the reader's shutdown raise.
    with_shutdown = getattr(state.provider, "shutdown", None)
    if with_shutdown is not None:
        with_shutdown()
    if state.owns_prometheus:
        # Anything the reader did not clean up must still go, or the next
        # configure_metrics() fails with a duplicate registration error.
        try:
            from prometheus_client import REGISTRY

            for reader in state.readers:
                collector = getattr(reader, "_collector", None)
                if collector is not None:
                    REGISTRY.unregister(collector)
        except (ImportError, KeyError):
            pass


def metrics_active() -> bool:
    return _state is not None


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Render the current metric values in Prometheus text exposition format."""
    from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def _attributes(spec: InstrumentSpec, attributes: dict[str, Any]) -> dict[str, Any]:
    provided = set(attributes)
    if provided != set(spec.attribute_keys):
        missing = sorted(spec.attribute_keys - provided)
        unexpected = sorted(provided - spec.attribute_keys)
        raise ValueError(
            f"instrument '{spec.name}' expects attributes "
            f"{sorted(spec.attribute_keys)}"
            + (f"; missing {missing}" if missing else "")
            + (f"; unexpected {unexpected}" if unexpected else "")
        )
    return {key: str(value) for key, value in attributes.items()}


def add(spec: InstrumentSpec, value: int | float = 1, /, **attributes: Any) -> None:
    """Increment a counter.

    ``spec`` and ``value`` are positional-only so an attribute named ``value`` or
    ``spec`` cannot silently bind to them.
    """
    resolved = _attributes(spec, attributes)
    state = _state
    if state is None:
        return
    state.instruments[spec.name].add(value, resolved)


def record(spec: InstrumentSpec, value: int | float, /, **attributes: Any) -> None:
    """Record a histogram observation."""
    resolved = _attributes(spec, attributes)
    state = _state
    if state is None:
        return
    state.instruments[spec.name].record(value, resolved)


def set_gauge(spec: InstrumentSpec, value: int | float, /, **attributes: Any) -> None:
    """Set a gauge to an absolute value."""
    resolved = _attributes(spec, attributes)
    state = _state
    if state is None:
        return
    state.instruments[spec.name].set(value, resolved)


def status_class(status_code: int) -> str:
    """Bucket a status code so response-status attributes stay low cardinality."""
    return f"{status_code // 100}xx"


def record_http_request(
    *,
    route: str,
    method: str,
    status_code: int,
    duration_ms: float,
) -> None:
    record(
        HTTP_REQUEST_DURATION,
        duration_ms,
        **{
            "http.route": route,
            "http.request.method": method,
            "http.response.status_class": status_class(status_code),
        },
    )


def set_http_requests_in_flight(value: int) -> None:
    set_gauge(HTTP_REQUESTS_IN_FLIGHT, value)


def record_rate_limit_rejection(*, route: str) -> None:
    add(HTTP_RATE_LIMIT_REJECTIONS, **{"http.route": route})


def record_request_size_rejection(*, route: str) -> None:
    add(HTTP_REQUEST_SIZE_REJECTIONS, **{"http.route": route})


@asynccontextmanager
async def timed_stage(spec: InstrumentSpec, stage: str) -> AsyncIterator[None]:
    """Time a pipeline stage and record its outcome.

    Used by ingestion and query stages so latency is attributable to a stage
    rather than to the whole pipeline, which is what makes it actionable.
    """
    started = monotonic()
    outcome = "success"
    try:
        async with async_span(f"{stage}", **{"flint_graph.stage": stage}):
            yield
    except Exception:
        outcome = "error"
        raise
    finally:
        record(
            spec,
            (monotonic() - started) * 1000,
            **{"flint_graph.stage": stage, "flint_graph.outcome": outcome},
        )
