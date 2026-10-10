# Milestone 24: Platform observability and incident response

Status: in progress; implementation issues are delivered independently.
Track: platform.
Epic: [#34](https://github.com/mohripan/flint-graph/issues/34).
Design: [ADR 13](../adr/0013-layered-platform-observability.md).

## Issue queue

| Issue | Scope | State |
| --- | --- | --- |
| [#37](https://github.com/mohripan/flint-graph/issues/37) | Wire Prometheus rules to a local Alertmanager profile | implemented |
| [#38](https://github.com/mohripan/flint-graph/issues/38) | Provision Grafana operations dashboards and split misleading mixed-unit panels | implemented |
| [#39](https://github.com/mohripan/flint-graph/issues/39) | Add an opt-in Phoenix and OpenTelemetry collector fan-out profile | implemented locally |
| [#40](https://github.com/mohripan/flint-graph/issues/40) | Emit privacy-safe OpenInference metadata and suppress provider exception payloads | implemented |
| [#41](https://github.com/mohripan/flint-graph/issues/41) | Configure operator-owned Alertmanager email or webhook delivery | planned |
| [#42](https://github.com/mohripan/flint-graph/issues/42) | Select and implement an ELK or OpenSearch structured-log pipeline | planned |
| [#43](https://github.com/mohripan/flint-graph/issues/43) | Harden production telemetry with authentication, retention and delivery budgets | planned |

## Acceptance and boundaries

An explicit two-file Compose overlay adds pinned Phoenix and Collector services
with loopback ingress, retained Phoenix data and bounded gateway memory/queues/
retries. Resource/span keys are allowlisted, status messages cleared and events
removed before trace fan-out. Native Collector validation and a real OTLP
fan-out/privacy test passed: the same provider-error trace arrived in Phoenix and
Tempo without the private sentinel. No model request was made. The existing
application containers were not silently reconfigured; the
[AI observability runbook](../runbooks/ai-observability.md) explains opting in,
preserving model settings and rollback. Authentication/retention remain open.

The metrics profile has a version-pinned loopback Alertmanager, grouped routes,
ticket inhibition, persistent silences/state and no external receiver. Native
amtool validation passed; native promtool checked the configuration and all nine
rules. A synthetic alert became active and was resolved via the local API without
sending mail. Rule forwarding is configured; production alert/failure drills and
operator notification delivery remain open.

Local LGTM automatically provisions a 24-panel operations dashboard and dedicated
datasource without replacing its defaults. Mixed rate/latency/count panels are
split and absent samples are explicit. Grafana's API confirmed provisioning and
the browser loaded the real dashboard. Asset tests validate real exported metric
names, units, provisioning mounts and Alertmanager routing. See
[operations runbook](../runbooks/operations-observability.md) for commands.

Provider-call spans now emit OpenInference kind/model metadata without model
content and use ERROR status plus bounded exception type, never automatic raw
exception messages/stacks. The application still receives its original exception.
Exported-span tests cover all five operation kinds and failures. This is a
provider-span guarantee, not a claim that every third-party HTTP/SQL/framework
instrumentation is fully sanitized; production telemetry hardening remains #43.

Phoenix receives privacy-safe AI traces; Grafana dashboards provision automatically; alerts reach Alertmanager; a log-backend ADR and production retention/auth boundaries are recorded. SMTP is separately operator-configured, never enabled by guessing an email.

Deliver privacy-safe spans first, then alert delivery and dashboard provisioning, then Phoenix. ELK and email remain explicit follow-ups. Local Compose tools are not production-ready merely because they start.

