# Milestone 24: Platform observability and incident response

Status: planned; implementation issues are delivered independently.
Track: platform.
Epic: [#34](https://github.com/mohripan/flint-graph/issues/34).
Design: [ADR 13](../adr/0013-layered-platform-observability.md).

## Issue queue

| Issue | Scope | State |
| --- | --- | --- |
| [#37](https://github.com/mohripan/flint-graph/issues/37) | Wire Prometheus rules to a local Alertmanager profile | planned |
| [#38](https://github.com/mohripan/flint-graph/issues/38) | Provision Grafana operations dashboards and split misleading mixed-unit panels | planned |
| [#39](https://github.com/mohripan/flint-graph/issues/39) | Add an opt-in Phoenix and OpenTelemetry collector fan-out profile | planned |
| [#40](https://github.com/mohripan/flint-graph/issues/40) | Emit privacy-safe OpenInference metadata and suppress provider exception payloads | planned |
| [#41](https://github.com/mohripan/flint-graph/issues/41) | Configure operator-owned Alertmanager email or webhook delivery | planned |
| [#42](https://github.com/mohripan/flint-graph/issues/42) | Select and implement an ELK or OpenSearch structured-log pipeline | planned |
| [#43](https://github.com/mohripan/flint-graph/issues/43) | Harden production telemetry with authentication, retention and delivery budgets | planned |

## Acceptance and boundaries

Phoenix receives privacy-safe AI traces; Grafana dashboards provision automatically; alerts reach Alertmanager; a log-backend ADR and production retention/auth boundaries are recorded. SMTP is separately operator-configured, never enabled by guessing an email.

Deliver privacy-safe spans first, then alert delivery and dashboard provisioning, then Phoenix. ELK and email remain explicit follow-ups. Local Compose tools are not production-ready merely because they start.

