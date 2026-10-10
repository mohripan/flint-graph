# ADR 0013: Layered platform observability

- Status: accepted for incremental implementation; production rollout pending
- Date: 2026-10-10
- Track: platform; Milestone 24; epic [#34](https://github.com/mohripan/flint-graph/issues/34)
- Extends ADR 0012; preserves its no-payload and bounded-metric rules

## Context and alternatives

M14 already provides custom OpenTelemetry spans/metrics, structured stdout logs,
a local grafana/otel-lgtm backend (Tempo, Loki, Prometheus and Grafana), dashboard
JSON and alert rules. It does not provision the application dashboard, deliver
alerts to Alertmanager, or provide Phoenix. Application document search already
uses OpenSearch; this is not an operational log collector.

1. Replace LGTM with ELK and Phoenix: introduces backend migration and duplicated
   storage before measuring needs.
2. Keep the existing OpenTelemetry interface, add Phoenix for AI traces,
   provision Grafana and connect Alertmanager: recommended incremental path.
3. Add every backend and auto-instrumentation package immediately: greater
   memory/storage burden, conflicting span ownership and payload leakage risk.

## Decision

One application SDK/export endpoint and one provider-call span owner. Optional
OpenTelemetry gateway fans traces to LGTM and Phoenix; metrics and logs go to
LGTM only. OpenInference kind/model/provider metadata makes AI spans usable
without exporting prompts, retrieved text, answers, embedding vectors or tokens
as credentials. Errors record bounded exception types, not exception messages
or stack traces. Span privacy is tested against the exported span boundary.
No automatic OpenLLMetry installation: its default content capture conflicts
with our policy. Evaluate only selective instrumentation with
TRACELOOP_TRACE_CONTENT=false, duplicate-span checks and verified redaction.

Grafana assets are provisioned reproducibly and separate rate, latency and
backlog units. Fleet metrics contain no workspace/user/document identifiers.
Prometheus rules forward to a loopback-only, opt-in Alertmanager with grouped
alerts and durable silences. Its default receiver sends nothing. Operator email
or webhook routing requires an explicitly supplied destination, secrets outside
Git, SMTP TLS and a controlled test; no guessed personal email.

ELK remains an explicit evaluated implementation issue, not silently rejected.
Compare Elasticsearch/Logstash/Kibana or Elastic OTLP ingestion, OpenSearch/Data
Prepper/Dashboards and current Loki for volume, retention, access control,
correlation, cost and restore. Select one primary log pipeline. Log storage and
access are separate from tenant corpus indexes; a log backend does not itself
accelerate RAG retrieval. Do not run a second search cluster by default.

## Rollout and verification

Deliver #40 privacy-safe spans, #37 local alert wiring, #38 provisioned dashboard,
then #39 Phoenix fan-out. Check native amtool/promtool/collector validation and
real trace arrival. All new operator ports bind loopback. Local SQLite Phoenix
and LGTM are developer tools, not production deployments. Production requires
auth/TLS, protected UIs, retention/erasure, sampling/storage/queue budgets,
delivery-failure monitoring and restore rehearsals (#43). Telemetry remains
non-authoritative: query provenance, audit and usage stay in PostgreSQL.

## Sources

- [Phoenix Docker and persistence](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
- [OpenInference semantics](https://arize-ai.github.io/openinference/spec/semantic_conventions.html)
- [OpenLLMetry content defaults and disabling capture](https://www.traceloop.com/docs/openllmetry/privacy/traces)
- [OpenTelemetry Collector configuration](https://opentelemetry.io/docs/collector/configuration/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Elastic log observability](https://www.elastic.co/docs/solutions/observability/logs)
- [OpenSearch observability](https://docs.opensearch.org/latest/observing-your-data/)

