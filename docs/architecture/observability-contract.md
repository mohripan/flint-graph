# Observability Contract

The stable surface of FlintGraph's telemetry: metric names, audit actions, and
usage event fields. Dashboards, alert rules, and audit queries are written against
these, so they change deliberately.

Decisions behind this contract: `docs/adr/0012-operational-telemetry-and-audit-model.md`.
Operating instructions: `docs/runbooks/operations-observability.md`.

## Enforcement

| Rule | Enforced by |
| --- | --- |
| Instruments have a name, unit, description, and declared attributes | `tests/unit/test_metrics_registry.py` |
| No identifier attributes on metrics | `tests/unit/test_metrics_registry.py` |
| Attribute sets are validated at record time | `observability/metrics.py`, same test |
| Declared instruments are actually recorded | `tests/integration/test_metrics_recording.py`, `tests/integration/test_pipeline_metrics.py` |
| Alerts and dashboards reference real series | `tests/unit/test_ops_observability_assets.py` |
| Migration matches the audit and usage models | `tests/unit/test_operational_telemetry_migration.py` |
| Payloads and secrets never reach logs | `tests/unit/test_log_redaction.py` |

## Metrics

Instruments are declared in `src/flint_graph/observability/instruments.py`.
Recorded names use dots; the Prometheus exporter renders them with underscores and
appends the unit (`ms` becomes `_milliseconds`, `s` becomes `_seconds`) plus
`_total` for counters. Both forms appear below because alerts use the exported
form.

### API

| Instrument | Kind | Attributes |
| --- | --- | --- |
| `flint_graph.http.server.request.duration` | histogram (ms) | `http.route`, `http.request.method`, `http.response.status_class` |
| `flint_graph.http.server.active_requests` | gauge | — |
| `flint_graph.http.server.rate_limit.rejections` | counter | `http.route` |
| `flint_graph.http.server.request_size.rejections` | counter | `http.route` |

`http.route` is the route template (`/v1/documents/{document_id}`), or
`unmatched` for requests that never reached a route. Middleware that runs before
routing attributes rejections to the configured path prefix instead.
`http.response.status_class` is bucketed (`2xx`, `4xx`, `5xx`).

### Ingestion and lifecycle

| Instrument | Kind | Attributes |
| --- | --- | --- |
| `flint_graph.ingestion.job.transitions` | counter | `flint_graph.job.status` |
| `flint_graph.ingestion.stage.duration` | histogram (ms) | `flint_graph.stage`, `flint_graph.outcome` |
| `flint_graph.lifecycle.projection_cleanup.backlog` | gauge | `flint_graph.cleanup.status` |
| `flint_graph.index_backfill.documents` | counter | `flint_graph.outcome` |

Ingestion stages: `fetch_raw`, `parse`, `persist_artifacts`, `extract`,
`generate_candidates`.

### Outbox

| Instrument | Kind | Attributes |
| --- | --- | --- |
| `flint_graph.outbox.pending_messages` | gauge | — |
| `flint_graph.outbox.oldest_pending_age` | gauge (s) | — |
| `flint_graph.outbox.relay.messages` | counter | `flint_graph.outcome` |

Lag matters more than depth: a small pending count with a very old head means the
relay is stuck on one message.

### Query and answers

| Instrument | Kind | Attributes |
| --- | --- | --- |
| `flint_graph.query.stage.duration` | histogram (ms) | `flint_graph.stage`, `flint_graph.outcome` |
| `flint_graph.query.runs.terminal` | counter | `flint_graph.query.status` |
| `flint_graph.query.abstentions` | counter | `flint_graph.abstain.reason` |
| `flint_graph.query.answer.claims` | counter | `flint_graph.support.status` |

Query stages match the orchestration graph nodes: `initialize_run`,
`classify_query`, `link_entities`, `plan_retrieval`, `retrieve_parallel`,
`fuse_candidates`, `rerank_candidates`, `pack_context`, `generate_answer`.

Abstain reasons are a closed set: `insufficient_context`, `no_answer_claims`,
`all_citations_dropped`, `supported_claim_ratio_below_threshold`,
`context_relevance_below_threshold`.

### Providers, usage, audit, readiness

| Instrument | Kind | Attributes |
| --- | --- | --- |
| `flint_graph.provider.call.duration` | histogram (ms) | `flint_graph.provider`, `flint_graph.model`, `flint_graph.operation` |
| `flint_graph.provider.call.errors` | counter | `flint_graph.provider`, `flint_graph.model`, `flint_graph.operation` |
| `flint_graph.provider.tokens` | counter | `flint_graph.provider`, `flint_graph.model`, `flint_graph.operation`, `flint_graph.token.direction` |
| `flint_graph.usage.unpriced_events` | counter | `flint_graph.provider`, `flint_graph.model` |
| `flint_graph.audit.events` | counter | `flint_graph.audit.action`, `flint_graph.audit.outcome` |
| `flint_graph.readiness.probe.duration` | histogram (ms) | `flint_graph.dependency`, `flint_graph.dependency.status` |

Dependency statuses: `ok`, `unavailable`, `timeout`, `unknown`. `unknown` means the
dependency has no cheap health surface (a hosted LLM API) or has no registered
probe. An optional `unknown` does not degrade the overall verdict; a required one
fails readiness.

## Traces

Span names and the attributes that make them useful:

| Span | Emitted by | Key attributes |
| --- | --- | --- |
| HTTP server spans | FastAPI instrumentation | standard HTTP semantics |
| `outbox.publish` | outbox relay | `flint_graph.outbox.topic`, `.message_id`, `.attempt` |
| `query.<stage>` | query orchestration | `flint_graph.stage` |
| `<ingestion stage>` | ingestion activities | `flint_graph.stage` |
| `provider.<operation>` | provider adapters | `flint_graph.provider`, `.model`, `.operation` |
| Temporal workflow/activity spans | Temporal tracing interceptor | Temporal semantics |

Continuity across the durable hop: the API writes a traceparent into the outbox
row, and the relay continues that trace when it publishes. Verified by
`tests/integration/test_trace_propagation.py`.

Span attributes never contain prompts, answers, or document text.

Provider-call spans also carry OpenInference metadata: `LLM` with
`llm.model_name`/`llm.provider` for answer/extraction/support, `EMBEDDING` with
`embedding.model_name`, and `RERANKER` with `reranker.model_name`. One shared
provider span owns these attributes; no auto-instrumentation dependency is added.
Provider exceptions emit only ERROR status and a bounded `error.type`; automatic
message/stack events are disabled. Other instrumentation must be reviewed before
production trace export (M24 #43).

## Audit events

Table `audit_events`. Append-only; written in the mutation's transaction.

| Field | Notes |
| --- | --- |
| `tenant_id` | Nullable: workspace creation and user provisioning precede membership |
| `actor_user_id`, `actor_issuer`, `actor_subject` | Identity denormalized so the ledger stays readable after a user row is removed |
| `action` | Closed vocabulary, below |
| `outcome` | `allowed`, `denied`, `failed` |
| `resource_type`, `resource_id` | Free-form type name plus stringified id |
| `request_id` | Correlates with logs and the `X-Request-ID` response header |
| `client_ip` | Socket peer, never a forwarded header; a forgeable value must not be recorded as fact |
| `user_agent`, `metadata` | Bounded context; never payload text |
| `created_at` | Server default |

Actions: `user.provisioned`, `workspace.created`, `workspace.member_upserted`,
`document.created`, `document.intake_created`, `document.deleted`,
`ingestion_job.created`, `ingestion_job.cancelled`,
`projection_cleanup.retried`, `retrieval_index.bootstrapped`,
`index_backfill.started`, `entity.merged`, `entity.unmerged`,
`merge_review.decided`.

Adding an action requires a migration: the enum values are constrained in the
database, and `tests/unit/test_operational_telemetry_migration.py` fails if an
enum member is missing from migration 0015 or its successors.

Read API: `GET /v1/audit-events` (admin/owner, workspace-scoped), filterable by
`action`, `outcome`, `actor_user_id`, `created_after`, `created_before`.

## Provider usage events

Table `provider_usage_events`. One row per provider call.

| Field | Notes |
| --- | --- |
| `operation` | `answer`, `embedding`, `extraction`, `rerank`, `faithfulness` |
| `provider`, `model` | As reported by the adapter; `unknown` when absent |
| `input_tokens`, `output_tokens` | Non-negative, check-constrained |
| `embedded_item_count` | Items in an embedding batch |
| `duration_ms` | Measured around the provider call |
| `estimated_cost_micros` | Nullable. Null means unpriced, never zero-by-default |
| `currency` | From `FLINT_GRAPH_USAGE_CURRENCY` |
| `query_run_id`, `ingestion_job_id`, `document_version_id` | Nullable links |
| `request_id`, `workflow_id`, `metadata` | Correlation |

Query invocations additionally carry server-owned `accounting_version`,
`execution_attempt_id`, zero-based `clause_index` (embedding only), `status` and
`usage_known` in metadata. The row UUID is the invocation ID. Started rows commit
before dispatch independently of retrieval readers and survive caller rollback.
See [ADR 0024](../adr/0024-durable-query-invocation-accounting.md).

Rollups on `query_runs`: `provider_input_tokens`, `provider_output_tokens`,
`provider_duration_ms`, `provider_cost_micros`. Distinct from
`context_token_count`, which is a pre-generation packing estimate.

Read API: `GET /v1/usage?group_by=day|operation|model` (admin/owner,
workspace-scoped). Responses include `unpriced_event_count` so a total is never
mistaken for complete.
They also include `unknown_event_count`; legacy rows without a usage attestation
remain unknown. Query GET/history return nullable `provider_usage_complete`.
Tenant-authorized `GET /v1/query-runs/{id}/usage` provides whitelisted invocation
details without prompts, vectors or arbitrary provider metadata.

### Adapter contract

An adapter reports usage by placing a `usage` mapping in its result metadata
alongside `provider` and `model`:

```python
metadata = {
    "provider": "anthropic",
    "model": "claude-opus-4-8",
    "usage": {"input_tokens": 2000, "output_tokens": 400, "duration_ms": 1234},
}
```

Numeric token columns are known lower bounds, not proof of complete accounting.
Only explicitly deterministic calls have known zero usage without reported
counts. Missing real-provider counts set `usage_known=false`, cannot be priced,
and make query completeness false. Embeddings require reported input counts;
generated output tokens are not applicable. Successful real generation/support
calls require both input and output counts. Failed/cancelled calls retain unknown
usage even if a later retry succeeds. Cost completeness is separate from token
completeness: null price is not a free call.

## Logs

Every request binds `request_id`, `tenant_id`, `http_method`, `http_path`.
Renderer is JSON outside local. Redaction covers prompt, answer, document, chunk,
and claim text plus credential-shaped keys, and cannot be disabled outside local.

## Not covered

Retention and pruning of audit and usage rows, long-term metric storage, SIEM
export, and cryptographic audit chaining are out of scope for Milestone 14.
