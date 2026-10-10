# Milestone 26: Developer experience and reproducible environments

Status: in progress; implementation issues are delivered independently.
Track: developer experience.
Epic: [#36](https://github.com/mohripan/flint-graph/issues/36).
Design: [ADR 15](../adr/0015-reproducible-developer-experience.md).

## Issue queue

| Issue | Scope | State |
| --- | --- | --- |
| [#48](https://github.com/mohripan/flint-graph/issues/48) | Add a read-only developer doctor command with actionable readiness diagnostics | planned |
| [#49](https://github.com/mohripan/flint-graph/issues/49) | Add reproducible offline and local-real bootstrap profiles | planned |
| [#50](https://github.com/mohripan/flint-graph/issues/50) | Pin service images and modernize CI runtimes with reviewed upgrade policy | planned |
| [#51](https://github.com/mohripan/flint-graph/issues/51) | Validate observability assets with native tools in CI | implemented |
| [#52](https://github.com/mohripan/flint-graph/issues/52) | Improve query and ingestion debugging handoff from the product UI | planned |

## Acceptance and boundaries

CI now has a bounded 15-minute observability job on Ubuntu 24.04. It validates
the pinned promtool/amtool/Collector configs, rejects semantic-invalid YAML
fixtures with each native tool, starts only isolated telemetry backends, and
checks real OTLP fan-out/privacy without model/SMTP calls. The existing offline
job checks all four base/metrics/AI/combined Compose combinations. Local native
positive and negative validations passed; see the
[AI observability runbook](../runbooks/ai-observability.md) for the same smoke.
Provider/doctor/bootstrap/runtime upgrades remain separately tracked.

## Milestone-wide target (not yet achieved)

A new developer runs explicit offline/local-real profiles, obtains doctor
diagnostics, uploads/queries a small corpus and inspects traces. CI validates
infrastructure assets and versions; tooling is Windows/Unix friendly and never
deletes existing data.

Coordinate M15/M16/M24. Tests/doctor are offline-safe; bootstrap is opt-in and never destroys existing data.

