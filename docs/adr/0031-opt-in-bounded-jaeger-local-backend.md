# ADR 0031: Opt-in bounded Jaeger v2 local backend

Date: 2026-10-11. Status: accepted for local incremental qualification only.
Milestone 24, #105 under #72; extends ADR 0013. #106/#107/#43 remain open.

## Decision

Jaeger is an additional operator-facing distributed-trace investigation tool,
not a replacement for Tempo, Phoenix or PostgreSQL provenance. Add an opt-in
backend-only Compose overlay first; do not reconfigure application exporters or
models until the sanitized gateway and rollout matrix are qualified separately.
One application SDK/export endpoint remains the target. Extra trace copies cost
memory, ingestion and storage; adding a trace backend does not speed document
search or improve answer quality.

Use official Jaeger 2.22.0, pinned to its reviewed multiarch manifest digest.
Use our explicit configuration rather than the bundled all-in-one defaults:
only OTLP/gRPC trace ingestion, memory storage, query UI and readiness extension.
No legacy receivers, remote sampling, debug/profiling extension, AI/MCP surface
or query-UI OTLP proxy. UI binds host loopback port 16686; ingestion is internal
port 4317, with no host mapping or collision with LGTM/gateway ports. Query gRPC,
health and self-metrics bind container loopback. No new Elasticsearch/OpenSearch.

Local limits: 512 MiB container memory, one CPU, 128 PIDs, dropped capabilities,
no-new-privileges, 384 MiB memory limiter/96 MiB spike, four MiB OTLP message,
512-item max batch, 128-request storage queue/two consumers, no storage retries,
and 10,000 retained traces. Trace count is not a per-trace byte quota or proven
capacity target. Overload/eviction/restart can lose data; no lossless delivery or
retention-duration promise. RAM traces are lost when the process exits. No trace
data volume is added, and no application volume/schema is modified.

Readiness uses the pinned image's actual wget and an explicitly configured v2
status path, considering reported permanent/recoverable component errors after
a ten-second recovery window. It is not proof of end-to-end delivery. Jaeger's
storage exporter and health extension are upstream development-stability
components in this release; native local verification does not upgrade that
stability or qualify production.

## Alternatives

Retaining only existing Tempo/Phoenix is lowest cost, but does not address the
requested Jaeger investigation path. Replacing those backends would add a
migration not requested here. Persistent Jaeger or another search cluster would
require access/retention/capacity/restore choices before local value is measured.
Bounded ephemeral storage is deliberately a reversible rehearsal first.

## Gates and evidence

Public deployment-contract tests, native positive/negative validation, real
OTLP parent/child retrieval through documented v3 JSON APIs, negative AI/proxy
routes, owned ephemeral restart/re-delivery and browser inspection are recorded
in the [delivery report](../reports/2026-10-11-jaeger-local-backend.md).

Application traces are not sent to this raw backend yet. #106 must preserve
fail-closed privacy before three-way fan-out, prove actual failure isolation and
provide fixed Grafana lookup. #107 qualifies cross-service propagation and safe
application profile transitions/rollback with preserved models/index/data.
Only then can #72 close. Production #43 additionally requires protected UIs,
authenticated/TLS OTLP, restricted networks, sampling/access/retention/restore
and independent operator acceptance. No public exposure, model calls or email.

## Primary references

Reviewed 2026-10-11:
[Jaeger 2.22 configuration](https://www.jaegertracing.io/docs/2.22/deployment/configuration/),
[memory storage](https://www.jaegertracing.io/docs/2.22/storage/memory/),
[stable trace APIs](https://www.jaegertracing.io/docs/2.22/architecture/apis/),
[pinned bundled config](https://github.com/jaegertracing/jaeger/blob/v2.22.0/cmd/jaeger/internal/all-in-one.yaml),
and [healthcheck v2](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.162.0/extension/healthcheckv2extension/README.md).
Registry digest and native binary identify v2.22.0, git
`462bb49fcff9af4be9556bf0206d07f5171bd8d7`, build 2026-10-06. Docs updated
2026-10-08; do not confuse documentation update with release/build date.
