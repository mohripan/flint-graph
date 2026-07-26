"""Declarative registry of every FlintGraph metric.

The registry is the stability contract described in
``docs/architecture/observability-contract.md``. Dashboards and alert rules are
written against these names, so instruments are declared in one place rather
than created ad hoc at call sites.

Attribute keys are declared alongside each instrument and enforced at record
time, which is what keeps metric cardinality bounded. Tenant and user
identifiers are deliberately absent: per-workspace breakdown belongs to the
``provider_usage_events`` and ``audit_events`` tables, not to metric labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class InstrumentKind(StrEnum):
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    name: str
    kind: InstrumentKind
    unit: str
    description: str
    attribute_keys: frozenset[str] = field(default_factory=frozenset)


def _spec(
    name: str,
    kind: InstrumentKind,
    unit: str,
    description: str,
    *attribute_keys: str,
) -> InstrumentSpec:
    return InstrumentSpec(
        name=name,
        kind=kind,
        unit=unit,
        description=description,
        attribute_keys=frozenset(attribute_keys),
    )


# --- API boundary -----------------------------------------------------------

HTTP_REQUEST_DURATION = _spec(
    "flint_graph.http.server.request.duration",
    InstrumentKind.HISTOGRAM,
    "ms",
    "Duration of HTTP requests handled by the API.",
    "http.route",
    "http.request.method",
    "http.response.status_class",
)
HTTP_REQUESTS_IN_FLIGHT = _spec(
    "flint_graph.http.server.active_requests",
    InstrumentKind.GAUGE,
    "{request}",
    "HTTP requests currently being handled by the API.",
)
HTTP_RATE_LIMIT_REJECTIONS = _spec(
    "flint_graph.http.server.rate_limit.rejections",
    InstrumentKind.COUNTER,
    "{rejection}",
    "Requests rejected by the API rate limiter.",
    "http.route",
)
HTTP_REQUEST_SIZE_REJECTIONS = _spec(
    "flint_graph.http.server.request_size.rejections",
    InstrumentKind.COUNTER,
    "{rejection}",
    "Requests rejected for exceeding the configured body size limit.",
    "http.route",
)

# --- Ingestion and lifecycle ------------------------------------------------

INGESTION_JOB_TRANSITIONS = _spec(
    "flint_graph.ingestion.job.transitions",
    InstrumentKind.COUNTER,
    "{transition}",
    "Ingestion job status transitions.",
    "flint_graph.job.status",
)
INGESTION_STAGE_DURATION = _spec(
    "flint_graph.ingestion.stage.duration",
    InstrumentKind.HISTOGRAM,
    "ms",
    "Duration of an ingestion pipeline stage.",
    "flint_graph.stage",
    "flint_graph.outcome",
)
PROJECTION_CLEANUP_BACKLOG = _spec(
    "flint_graph.lifecycle.projection_cleanup.backlog",
    InstrumentKind.GAUGE,
    "{cleanup}",
    "Document projection cleanups not yet completed.",
    "flint_graph.cleanup.status",
)
INDEX_BACKFILL_PROGRESS = _spec(
    "flint_graph.index_backfill.documents",
    InstrumentKind.COUNTER,
    "{document}",
    "Documents processed by index backfill jobs.",
    "flint_graph.outcome",
)

# --- Outbox -----------------------------------------------------------------

OUTBOX_PENDING_MESSAGES = _spec(
    "flint_graph.outbox.pending_messages",
    InstrumentKind.GAUGE,
    "{message}",
    "Outbox messages awaiting publication.",
)
OUTBOX_OLDEST_PENDING_AGE = _spec(
    "flint_graph.outbox.oldest_pending_age",
    InstrumentKind.GAUGE,
    "s",
    "Age of the oldest unpublished outbox message.",
)
OUTBOX_RELAY_MESSAGES = _spec(
    "flint_graph.outbox.relay.messages",
    InstrumentKind.COUNTER,
    "{message}",
    "Outbox messages handled by the relay.",
    "flint_graph.outcome",
)

# --- Query ------------------------------------------------------------------

QUERY_STAGE_DURATION = _spec(
    "flint_graph.query.stage.duration",
    InstrumentKind.HISTOGRAM,
    "ms",
    "Duration of a query orchestration stage.",
    "flint_graph.stage",
    "flint_graph.outcome",
)
QUERY_RUN_TERMINAL_STATES = _spec(
    "flint_graph.query.runs.terminal",
    InstrumentKind.COUNTER,
    "{run}",
    "Query runs reaching a terminal state.",
    "flint_graph.query.status",
)
QUERY_ABSTENTIONS = _spec(
    "flint_graph.query.abstentions",
    InstrumentKind.COUNTER,
    "{answer}",
    "Answers withheld because the faithfulness policy was not met.",
    "flint_graph.abstain.reason",
)
QUERY_CLAIMS = _spec(
    "flint_graph.query.answer.claims",
    InstrumentKind.COUNTER,
    "{claim}",
    "Answer claims by support status.",
    "flint_graph.support.status",
)

# --- Providers and usage ----------------------------------------------------

PROVIDER_CALL_DURATION = _spec(
    "flint_graph.provider.call.duration",
    InstrumentKind.HISTOGRAM,
    "ms",
    "Duration of a model provider call.",
    "flint_graph.provider",
    "flint_graph.model",
    "flint_graph.operation",
)
PROVIDER_CALL_ERRORS = _spec(
    "flint_graph.provider.call.errors",
    InstrumentKind.COUNTER,
    "{error}",
    "Failed model provider calls.",
    "flint_graph.provider",
    "flint_graph.operation",
)
PROVIDER_TOKENS = _spec(
    "flint_graph.provider.tokens",
    InstrumentKind.COUNTER,
    "{token}",
    "Tokens consumed by model provider calls.",
    "flint_graph.provider",
    "flint_graph.model",
    "flint_graph.operation",
    "flint_graph.token.direction",
)
UNPRICED_USAGE_EVENTS = _spec(
    "flint_graph.usage.unpriced_events",
    InstrumentKind.COUNTER,
    "{event}",
    "Usage events recorded without a cost because no pricing was configured.",
    "flint_graph.provider",
    "flint_graph.model",
)

# --- Audit ------------------------------------------------------------------

AUDIT_EVENTS = _spec(
    "flint_graph.audit.events",
    InstrumentKind.COUNTER,
    "{event}",
    "Audit events appended to the ledger.",
    "flint_graph.audit.action",
    "flint_graph.audit.outcome",
)

# --- Readiness --------------------------------------------------------------

READINESS_PROBE_DURATION = _spec(
    "flint_graph.readiness.probe.duration",
    InstrumentKind.HISTOGRAM,
    "ms",
    "Duration of a readiness dependency probe.",
    "flint_graph.dependency",
    "flint_graph.dependency.status",
)


ALL_INSTRUMENTS: tuple[InstrumentSpec, ...] = (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_IN_FLIGHT,
    HTTP_RATE_LIMIT_REJECTIONS,
    HTTP_REQUEST_SIZE_REJECTIONS,
    INGESTION_JOB_TRANSITIONS,
    INGESTION_STAGE_DURATION,
    PROJECTION_CLEANUP_BACKLOG,
    INDEX_BACKFILL_PROGRESS,
    OUTBOX_PENDING_MESSAGES,
    OUTBOX_OLDEST_PENDING_AGE,
    OUTBOX_RELAY_MESSAGES,
    QUERY_STAGE_DURATION,
    QUERY_RUN_TERMINAL_STATES,
    QUERY_ABSTENTIONS,
    QUERY_CLAIMS,
    PROVIDER_CALL_DURATION,
    PROVIDER_CALL_ERRORS,
    PROVIDER_TOKENS,
    UNPRICED_USAGE_EVENTS,
    AUDIT_EVENTS,
    READINESS_PROBE_DURATION,
)

INSTRUMENTS_BY_NAME: dict[str, InstrumentSpec] = {
    instrument.name: instrument for instrument in ALL_INSTRUMENTS
}
