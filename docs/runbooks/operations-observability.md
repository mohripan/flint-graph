# Operations: Observability, Audit, and Usage

How to tell what FlintGraph is doing, and what to do first when an alert fires.

Companion documents: `docs/architecture/observability-contract.md` for the metric,
audit, and usage schemas; `docs/runbooks/deployment-hardening.md` for the exposure
boundary; `docs/runbooks/backup-restore.md` for recovery.

## What is emitted

| Signal | Where it goes | Enabled by |
| --- | --- | --- |
| Structured logs | stdout, JSON outside local | always |
| Traces | OTLP exporter | `FLINT_GRAPH_OTEL_ENABLED=true` |
| Metrics | OTLP exporter, and optionally a Prometheus scrape endpoint | `FLINT_GRAPH_OTEL_ENABLED=true` / `FLINT_GRAPH_METRICS_ENABLED=true` |
| Audit events | `audit_events` in PostgreSQL | always |
| Provider usage | `provider_usage_events` in PostgreSQL | always |

Every process configures all of this through one call
(`configure_observability`), so the API, the Temporal worker, the outbox relay,
and the maintenance processes are instrumented identically. Each reports a
distinct `service.name` derived from its role.

### Local

`docker compose up -d` already runs an `observability` service
(`grafana/otel-lgtm`) that receives OTLP on 4317 and serves Grafana on
<http://localhost:3000>. The API and the durable processes push to it by default,
so a document upload produces one trace spanning the API request, the outbox
publish, and the Temporal activities.

To rehearse a pull-based deployment instead:

```powershell
$env:FLINT_GRAPH_METRICS_ENABLED = "true"
$env:FLINT_GRAPH_METRICS_TOKEN = "local-scrape-token"
docker compose --profile metrics up -d
# Prometheus: http://localhost:9090
```

The FlintGraph operations dashboard now provisions automatically in the
FlintGraph folder at <http://localhost:3000/d/flint-graph-operations>. Its default
`FlintGraph metrics` datasource reads LGTM's internal Prometheus, including
worker/relay OTLP metrics. It does not point at the separate API-only scrape
profile on host port 9090. Existing LGTM datasources/dashboards remain intact.
Latency, rate and backlog panels have separate units; absent samples show
`No samples` rather than being treated as zero or healthy.

Dashboard assets are mounted read-only and reloaded every 30 seconds. Initial
provisioning mounts require `docker compose up -d --no-deps observability`;
this recreates the telemetry container but preserves its existing data volume.
For another Grafana deployment, import the JSON or install the provisioning
files and point the datasource at that deployment's Prometheus. Provisioning
paths are specific to the pinned local LGTM image, not production defaults.

### Alert delivery rehearsal

The `metrics` profile forwards the checked-in rules to Alertmanager on
<http://127.0.0.1:9093>. Prometheus is at <http://127.0.0.1:9090>. Both new
operator endpoints bind loopback. Alertmanager groups by alert name/service,
inhibits ticket-severity duplicates when a matching page is active, and retains
silences/notification state in its own volume. **The default receiver sends
nothing**, even when an alert fires. This is not a production HA deployment.

Validate configs using the actual pinned tools:

```powershell
docker compose --profile metrics run --rm --no-deps --entrypoint amtool alertmanager check-config /etc/alertmanager/alertmanager.yml
docker compose --profile metrics run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
```

Start only Alertmanager without changing existing application containers:

```powershell
docker compose --profile metrics up -d --no-deps alertmanager
```

A synthetic local alert can be POSTed to `/api/v2/alerts` with labels
`alertname=FlintGraphLocalRehearsal`, `service=flint-graph`, `severity=ticket`,
a summary and explicit `startsAt`/`endsAt` timestamps. Confirm it appears via
`GET /api/v2/alerts`, then resolve it by POSTing the same labels with `endsAt`
in the past. This rehearses lifecycle without touching model services or sending
mail. It does not prove that every production rule will fire under load.

For email/webhook delivery, [issue #41](https://github.com/mohripan/flint-graph/issues/41)
requires an operator-owned recipient/relay configuration, TLS and external
secret files. Never place SMTP passwords in this file or guess a personal email.
Mount a separate deployment config, validate it with amtool, and test only an
approved mailbox. Actual notifications are not implemented by this rehearsal.

### Deployed

- Set `FLINT_GRAPH_OTEL_ENABLED=true` and an OTLP endpoint for every process.
- `FLINT_GRAPH_METRICS_ENABLED=true` requires `FLINT_GRAPH_METRICS_TOKEN` in
  staging and production; configuration validation refuses otherwise. The
  endpoint is not part of the tenant API and is excluded from the OpenAPI schema.
- Never set `FLINT_GRAPH_LOG_PAYLOADS=true` outside local; staging and production
  reject it.

## Service level objectives

Starting objectives, measured over a rolling 30 days. They are deliberately
modest for a first controlled deployment; tighten them once there is history.

| SLO | Target | Measured by |
| --- | --- | --- |
| API availability | 99.5% of requests non-5xx | `flint_graph_http_server_request_duration_milliseconds_count` by status class |
| API latency | p95 < 2000 ms | same histogram |
| Query first token | p95 < 10 s | `flint_graph_query_stage_duration_milliseconds` for `generate_answer` |
| Ingestion success | > 95% of jobs reach completed | `flint_graph_ingestion_job_transitions_total` |
| Outbox lag | oldest pending < 60 s | `flint_graph_outbox_oldest_pending_age_seconds` |
| Projection freshness | cleanup backlog drains < 30 min | `flint_graph_lifecycle_projection_cleanup_backlog` |

## Health endpoints

- `GET /health/live` — process only, no dependencies. Use for liveness probes. A
  database outage must not restart every replica.
- `GET /health/ready` — probes each configured dependency with a timeout and a
  short result cache. Returns 200 `ready`, 200 `degraded` (an optional
  dependency is down), or 503 `application/problem+json` naming the failed
  required dependencies. Use for readiness probes and load balancer checks.
- `GET /v1/system-readiness` — product readiness for a workspace (providers,
  embedding configuration, searchable content). Different question: whether this
  workspace can answer questions, not whether the process should take traffic.

A dependency with no cheap health surface (a hosted LLM API) reports `unknown`
rather than being assumed healthy. When it is optional, that does not make the
instance `degraded`: otherwise `degraded` would be the permanent steady state and
would stop meaning anything. A *required* dependency reporting `unknown` still
fails readiness, because unverifiable is not ready.

Required and optional dependency sets are configuration
(`FLINT_GRAPH_READINESS_REQUIRED_DEPENDENCIES`,
`FLINT_GRAPH_READINESS_OPTIONAL_DEPENDENCIES`). Deployed environments require
PostgreSQL, the object store, Temporal, Neo4j, and OpenSearch, and treat the
model providers as optional so a provider outage alerts instead of removing
capacity that still serves reads.

## Alert responses

Rules live in `ops/observability/alerts.yml`. Each maps to one section below.

### API error rate

Over 5% of requests are 5xx.

1. `GET /health/ready` on an affected replica; a required dependency is the usual
   cause and the response names it.
2. Filter logs by `http_path` and `request_id`; the request ID is returned in
   `X-Request-ID` and echoed in every problem response.
3. If one route dominates, check the dashboard's slowest-routes panel for a
   correlated latency change.

### API latency

p95 above the 2 s objective.

1. Compare the query and ingestion stage panels: a provider slowdown shows up as
   `generate_answer` latency, not as an API-wide change.
2. Check `flint_graph_provider_call_duration_milliseconds` by provider and model.
3. Check the in-flight gauge for saturation; a single replica with in-flight
   requests pinned high is a capacity problem, not a dependency problem.

### Outbox lag

The oldest unpublished message is older than five minutes.

1. Is the relay running? `docker compose ps outbox-relay`, or the deployment's
   equivalent.
2. Look for the message's `last_error`:
   `SELECT topic, attempt_count, last_error FROM outbox_messages WHERE status = 'pending' ORDER BY created_at LIMIT 5;`
3. A stuck head with a small depth usually means Temporal is unreachable; verify
   with `GET /health/ready`, which probes it.
4. The relay retries with backoff and never drops a message. Do not delete rows;
   fix the downstream cause and the backlog drains.

### Ingestion failures

More than 10% of ingestion jobs are failing.

1. `GET /v1/ingestion-jobs/{id}/events` for a failing job gives the stage and
   error code.
2. Group failures by stage using
   `flint_graph_ingestion_stage_duration_milliseconds` with
   `flint_graph_outcome="error"`.
3. Parser and extraction failures are usually input-shaped; object store and
   Neo4j failures are usually infrastructure. `GET /health/ready` distinguishes.

### Projection cleanup

Cleanups are not draining after 30 minutes.

1. `GET /v1/documents/{id}/projection-cleanups` shows the pending records and
   their errors.
2. Verify Neo4j and OpenSearch are reachable, then
   `POST /v1/documents/{id}/projection-cleanups/retry` (admin, audited).
3. Neo4j and OpenSearch are rebuildable projections; if they are far behind, a
   reconcile is safe: `python -m flint_graph.processes.retrieval_index_reconcile`.

### Provider errors

A model provider is failing calls.

1. Confirm scope with `flint_graph_provider_call_errors_total` by provider: one
   provider or all of them.
2. Check the provider's own status, then credentials and quota. Provider probes
   appear in `/health/ready` as optional dependencies.
3. Answers degrade to abstention rather than fabrication, so this is a quality
   incident, not a correctness one. It does not require failing over reads.

### Abstention rate

More than half of answers are being withheld.

1. Abstention reasons are labelled: `insufficient_context`,
   `no_answer_claims`, `all_citations_dropped`,
   `supported_claim_ratio_below_threshold`, `context_relevance_below_threshold`.
2. `insufficient_context` dominating points at retrieval or indexing: check
   `GET /v1/search-readiness` and index coverage for the workspace.
3. `supported_claim_ratio_below_threshold` dominating points at the generation or
   support model; compare against the evaluation baselines before changing
   thresholds.

### Unpriced usage

Usage is being recorded with no configured price.

1. Find the models: `flint_graph_usage_unpriced_events_total` is labelled by
   provider and model.
2. Add rates to `FLINT_GRAPH_USAGE_PRICING`, keyed `"<provider>:<model>"` (or
   `"<provider>:*"`), with `input_per_million` and `output_per_million`.
3. Cost is never fabricated: unpriced rows carry a null cost, and the usage
   endpoint reports `unpriced_event_count` so a total is never mistaken for
   complete.

## Audit queries

`GET /v1/audit-events` is workspace-scoped and admin-only, filterable by
`action`, `outcome`, `actor_user_id`, `created_after`, and `created_before`.

Common questions:

- Who deleted this document?
  `?action=document.deleted&limit=50`, then match `resource_id`.
- What did this user do?
  `?actor_user_id=<uuid>`
- Was anything refused?
  `?outcome=denied`

Audit rows are written in the same transaction as the mutation they describe, so
an audited action cannot commit without its record, and a rolled back action
leaves none. There is no update or delete path in the application.

## Usage and cost

`GET /v1/usage?group_by=day|operation|model` is workspace-scoped and admin-only.
Costs are integers in micros of `currency` to avoid floating point drift.

Per-run figures are denormalized onto `query_runs`
(`provider_input_tokens`, `provider_output_tokens`, `provider_duration_ms`,
`provider_cost_micros`). These are provider-reported; `context_token_count` is a
packing estimate and the two are deliberately separate numbers.

## Log fields

Every request binds `request_id`, `tenant_id`, `http_method`, and `http_path`.
Worker paths bind job and workflow identifiers where available.

Prompts, answers, document text, chunk text, and credentials are redacted by a
structlog processor before emission — not by call site discipline. If a log line
shows `[redacted] (N chars)`, that is the redactor working, not a bug.
