# ADR 0012: Operational telemetry and audit model

- Status: accepted
- Date: 2026-07-26
- Milestone: 14

## Context

Milestone 12 gave FlintGraph an identity boundary and Milestone 13 gave it a safe
public edge. Neither made the running system legible. Before Milestone 14:

- `/health/ready` executed `SELECT 1` and nothing else, so Neo4j, OpenSearch,
  MinIO, and Temporal could all be down while readiness reported `ready`.
- Tracing was API-only and opt-in. No worker process configured it, and the
  traceparent the outbox recorded was never read, so the trace ended at the API.
- There were no metrics of any kind.
- Nothing recorded who deleted a document, changed a membership, or started a
  backfill.
- Real providers had been the default since Milestone 09, but nothing recorded
  what they consumed, so the system could not answer what it cost to run.

We need decisions that survive a first controlled deployment without committing
to a vendor or building an analytics platform.

## Decision

**1. OpenTelemetry for traces and metrics; one entry point for every process.**

`configure_observability(settings, role=...)` configures logging, tracing, and
metrics identically in the API, the Temporal worker, the outbox relay, and the
maintenance processes. Each reports a distinct `service.name` derived from its
role. Telemetry is opt-in by environment variable and completely inert when off.

**2. Metrics are declared in a registry, not created at call sites.**

`observability/instruments.py` declares every instrument with its unit,
description, and permitted attribute keys. `observability/metrics.py` validates
attributes at record time. Application code never imports OpenTelemetry.

Rejected: creating meters at call sites. It is shorter, but it makes the metric
surface undiscoverable and lets any call site introduce unbounded cardinality.

**3. No identifiers as metric attributes.**

Workspace, user, document, and query-run identifiers are forbidden in metric
attributes and enforced by test. Per-workspace numbers come from the usage and
audit tables, which are indexed for exactly that question. Metrics answer "is the
system healthy"; the tables answer "what did this workspace do".

**4. Audit lives in PostgreSQL, in the mutation's transaction.**

`audit_events` is append-only and written with `session.flush()` inside the
caller's transaction, so an audited action cannot commit without its record and a
rolled back action leaves none. There is no update or delete path in application
code. Denied privileged attempts are recorded with `outcome=denied`.

Rejected: emitting audit events to a log stream or the outbox. Logs can be lost
and are not queryable per workspace; the outbox would decouple the record from
the transaction that must not commit without it. PostgreSQL is already the
authoritative store (ADR 0004), so audit belongs there.

Rate-limit rejections stay in metrics rather than the audit table: they are
cheap for an attacker to generate, and an audit write per rejection is a write
amplification vector.

**5. Usage accounting in PostgreSQL, priced from configuration.**

`provider_usage_events` records one row per provider call, with token counts,
duration, and a cost in micros. Adapters report usage in result metadata; a
`UsageRecorder` in the service layer persists it. Adapters never write to the
database.

Pricing is configuration (`FLINT_GRAPH_USAGE_PRICING`). An unknown
provider/model produces a null cost plus an `unpriced_events` counter increment.

Rejected: hardcoding prices in the codebase. Prices change without releases, and
a stale hardcoded rate produces a confident wrong number, which is worse than a
null. Also rejected: floating point money. Costs are integer micros.

**6. Rollups are denormalized onto `query_runs`.**

Per-run token, duration, and cost totals live on the run row so query history is
a single read. `context_token_count` (a packing estimate) and
`provider_input_tokens` (provider-reported) are deliberately separate columns
and must not be conflated.

**7. Readiness distinguishes required from optional dependencies.**

`/health/ready` probes each configured dependency with a timeout and a short
result cache, returns 503 `application/problem+json` naming failed required
dependencies, and returns 200 `degraded` when only optional ones are unhealthy.
`/health/live` stays dependency-free. Deployed environments require PostgreSQL,
the object store, Temporal, Neo4j, and OpenSearch; model providers are optional,
because removing capacity that still serves reads makes a provider outage worse.

**8. Redaction is a processor, not a convention.**

A structlog processor strips prompts, answers, document text, and credentials
before emission. `log_payloads=true` is rejected in staging and production.
Span attributes follow the same rule.

## Consequences

- Operators get RED metrics, pipeline metrics, end-to-end traces across the
  durable hop, dependency-aware readiness, an audit trail, and per-workspace cost
  without a vendor commitment.
- Two new tables grow with traffic. Retention is not implemented; audit and usage
  pruning is deferred (see Non-Goals in `notes/milestone-14/00-plan.md`).
- The instrument registry is a contract. Renaming an instrument breaks dashboards
  and alerts, so changes go through
  `docs/architecture/observability-contract.md` and its tests.
- Worker metrics are export-only (no HTTP surface), so a pull-based deployment
  needs a collector for them even if it scrapes the API directly.
