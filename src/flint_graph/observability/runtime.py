"""Single observability entry point for every FlintGraph process.

The API, the Temporal worker, the outbox relay, and the maintenance processes all
call :func:`configure_observability` so logs, traces, and metrics are set up the
same way everywhere. Before Milestone 14 only the API configured tracing, which
meant the durable half of the system produced no spans at all.
"""

from __future__ import annotations

import threading
from typing import Any

from flint_graph.config import Settings
from flint_graph.logging import configure_logging
from flint_graph.observability.metrics import configure_metrics

# Roles are used for ``service.name``, so they are stable identifiers rather than
# free text: a renamed role looks like a new service in the telemetry backend.
API_ROLE = "api"
INGESTION_WORKER_ROLE = "ingestion-worker"
OUTBOX_RELAY_ROLE = "outbox-relay"
PROJECTION_CLEANUP_ROLE = "projection-cleanup"
GRAPH_RECONCILE_ROLE = "graph-reconcile"
INDEX_RECONCILE_ROLE = "index-reconcile"
MIGRATION_ROLE = "migration"

_lock = threading.Lock()
_configured_role: str | None = None


def service_name_for_role(settings: Settings, role: str) -> str:
    if role == API_ROLE:
        return settings.service_name
    return f"flint-graph-{role}"


def configure_observability(
    settings: Settings,
    *,
    role: str,
    app: Any | None = None,
    extra_metric_readers: list[Any] | None = None,
) -> None:
    """Configure logging, tracing, and metrics for the current process.

    Idempotent per process. Unlike the Milestone 13 tracing guard, this does not
    silently swallow a second call from a different role: that indicates two
    services sharing a process, which would produce mislabelled telemetry.
    """
    global _configured_role
    configure_logging(settings)
    # Metrics setup is idempotent on its own and must run even when a second app
    # instance is created in the same process (as tests do), otherwise the meter
    # provider depends on which app was built first.
    configure_metrics(settings, extra_readers=extra_metric_readers)
    with _lock:
        if _configured_role is not None:
            if _configured_role != role:
                raise RuntimeError(
                    f"observability already configured for role '{_configured_role}'; "
                    f"refusing to reconfigure as '{role}'"
                )
            if app is not None:
                _instrument_app(settings, app)
            return
        _configured_role = role

    configure_tracing(settings, role=role, app=app)


def reset_observability() -> None:
    """Forget the configured role. Intended for tests."""
    global _configured_role
    with _lock:
        _configured_role = None


def configure_tracing(settings: Settings, *, role: str, app: Any | None = None) -> None:
    if not settings.otel_enabled:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    from flint_graph.infrastructure.db.session import engine

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name_for_role(settings, role),
                "service.version": settings.service_version,
                "deployment.environment.name": settings.env,
                "flint_graph.service.role": role,
            }
        ),
        sampler=ParentBased(TraceIdRatioBased(settings.otel_trace_sample_ratio)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=settings.otel_exporter_otlp_insecure,
            )
        )
    )
    trace.set_tracer_provider(provider)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    if app is not None:
        _instrument_app(settings, app)


def _instrument_app(settings: Settings, app: Any) -> None:
    if not settings.otel_enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    # Liveness and the scrape endpoint are polled continuously by the platform;
    # tracing them buries real traffic.
    excluded = f"health/live,{settings.metrics_path.lstrip('/')}"
    FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded)
