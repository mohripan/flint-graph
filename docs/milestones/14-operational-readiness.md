# Milestone 14: Operational Readiness

Milestone 13 made FlintGraph safe to expose. Milestone 14 makes it possible to
operate: to see what it is doing, to answer for who did what, and to know what it
costs.

Implemented behavior:

- One entry point configures logging, tracing, and metrics for every process.
  `configure_observability(settings, role=...)` runs in the API, the Temporal
  worker, the outbox relay, and the projection-cleanup, graph-reconcile,
  index-reconcile, and Neo4j-migration processes. Before this, only the API
  configured tracing, so the durable half of the system emitted no spans.
- Traces are continuous across the durable hop. The Temporal client and worker use
  the OTel tracing interceptor, and the relay continues the trace whose
  traceparent the API wrote into the outbox row, so one request produces one trace
  spanning API, outbox publish, workflow, and activities.
- Metrics are declared in an instrument registry
  (`src/flint_graph/observability/instruments.py`) with units, descriptions, and
  permitted attribute keys, validated at record time. Coverage: API request
  duration and concurrency, boundary rejections, ingestion transitions and stage
  latency, outbox depth and lag, projection-cleanup backlog, backfill outcomes,
  query stage latency and terminal states, abstentions and claim support, provider
  latency/errors/tokens, unpriced usage, audit events, and readiness probes.
- Metric attributes never carry workspace, user, or document identifiers, enforced
  by test. Per-workspace numbers come from the audit and usage tables.
- A Prometheus scrape endpoint is available at `FLINT_GRAPH_METRICS_PATH`
  (default `/metrics`) when `FLINT_GRAPH_METRICS_ENABLED=true`. It is registered
  only when enabled, excluded from the OpenAPI schema, outside `/v1`, not rate
  limited, and requires a bearer token whenever one is configured. Staging and
  production refuse to enable it without `FLINT_GRAPH_METRICS_TOKEN`.
- `/health/ready` probes every configured dependency (PostgreSQL, object store,
  Temporal, Neo4j, OpenSearch, embedding and answer providers) with a timeout and
  a short result cache. It returns 503 `application/problem+json` naming failed
  required dependencies, or 200 with `status: degraded` when only optional
  dependencies are unhealthy. `/health/live` remains dependency-free.
- Deployed environments require PostgreSQL, the object store, Temporal, Neo4j, and
  OpenSearch; model providers are optional so a provider outage alerts instead of
  removing capacity that still serves reads. Local and test require PostgreSQL
  only, so a developer without the full compose stack still gets a ready API.
- `audit_events` records who performed security-relevant actions: user
  provisioning, workspace creation, membership changes, document create/delete,
  intake, ingestion job create/cancel, projection cleanup retry, retrieval index
  bootstrap, backfill start, and graph merge/unmerge/review decisions. Rows are
  written in the mutation's transaction, so an audited action cannot commit
  without its record and a rolled back action leaves none. Denied privileged
  attempts are recorded with `outcome=denied`. There is no update or delete path.
- `GET /v1/audit-events` is workspace-scoped and admin/owner-only, filterable by
  action, outcome, actor, and date range.
- `provider_usage_events` records tokens, duration, and cost per provider call,
  linked to the query run, ingestion job, or document version that caused it.
  Answer generation and support checking are recorded separately because they can
  run on different models.
- Cost is derived from `FLINT_GRAPH_USAGE_PRICING` and stored as integer micros.
  An unpriced provider/model yields a null cost plus an `unpriced_events` counter
  increment, never a fabricated number. Deterministic offline runs still record
  usage rows, so the default test and eval paths exercise accounting.
- `query_runs` carries denormalized rollups (`provider_input_tokens`,
  `provider_output_tokens`, `provider_duration_ms`, `provider_cost_micros`), kept
  distinct from `context_token_count`, which remains a packing estimate.
- `GET /v1/usage?group_by=day|operation|model` is workspace-scoped and
  admin/owner-only, and reports `unpriced_event_count` alongside totals.
- Structured logs bind `request_id`, `tenant_id`, `http_method`, and `http_path`.
  A redaction processor strips prompts, answers, document/chunk/claim text, and
  credential-shaped keys before emission. `FLINT_GRAPH_LOG_PAYLOADS=true` is
  rejected in staging and production. JSON renderer outside local.
- Ops artifacts under `ops/observability/`: Prometheus scrape config, alert rules
  mapped to runbook sections, and an importable Grafana dashboard. A test asserts
  every alert and panel query references a series the exporter actually produces.
- Local compose now enables tracing for the durable processes as well as the API,
  so the existing `observability` service (Grafana/OTLP) shows complete traces. An
  opt-in `metrics` profile adds Prometheus for rehearsing a pull-based deployment.
- Migration `0015_operational_telemetry` adds both tables and the query-run
  rollups. Existing rows backfill to zero tokens and a null cost.

Configuration added:

```
FLINT_GRAPH_METRICS_ENABLED / FLINT_GRAPH_METRICS_PATH / FLINT_GRAPH_METRICS_TOKEN
FLINT_GRAPH_OTEL_METRIC_EXPORT_INTERVAL_MILLIS
FLINT_GRAPH_LOG_PAYLOADS / FLINT_GRAPH_LOG_RENDERER
FLINT_GRAPH_READINESS_REQUIRED_DEPENDENCIES
FLINT_GRAPH_READINESS_OPTIONAL_DEPENDENCIES
FLINT_GRAPH_READINESS_PROBE_TIMEOUT_SECONDS / FLINT_GRAPH_READINESS_CACHE_SECONDS
FLINT_GRAPH_USAGE_PRICING / FLINT_GRAPH_USAGE_CURRENCY
```

Operational notes:

- Worker processes have no HTTP surface, so their metrics are OTLP-export only. A
  pull-based deployment still needs a collector for them even if it scrapes the
  API directly.
- Retention and pruning of `audit_events` and `provider_usage_events` are not
  implemented; both tables grow with traffic.
- Provider readiness probes exist for Ollama and for deterministic providers.
  Hosted APIs have no cheap health surface, so their probe reports `unknown`
  rather than assuming health.
- Extraction records provider latency and errors but not token usage: the
  extraction contract has no metadata channel to carry it yet.
- Distributed rate limiting and multi-replica scale-out remain deferred (see
  Milestone 13's operational notes). They are easier to do safely now that
  metrics and traces exist to show whether extra replicas behave.
