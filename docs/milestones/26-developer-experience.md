# Milestone 26: Developer experience and reproducible environments

Status: in progress; implementation issues are delivered independently.
Track: developer experience.
Epic: [#36](https://github.com/mohripan/flint-graph/issues/36).
Design: [ADR 15](../adr/0015-reproducible-developer-experience.md).

## Issue queue

| Issue | Scope | State |
| --- | --- | --- |
| [#48](https://github.com/mohripan/flint-graph/issues/48) | Add a read-only developer doctor command with actionable readiness diagnostics | implemented |
| [#49](https://github.com/mohripan/flint-graph/issues/49) | Add reproducible offline and local-real bootstrap profiles | implemented |
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
The read-only `flint-graph-doctor` command reports approved effective config,
local tooling, configured service checks, model inventories and recent workspace
index coverage. Its offline mode makes no network calls; live mode uses public
GET APIs and preserves viewer membership authorization. The model-readiness
endpoint checks installed Ollama tags without running or downloading models;
hosted availability remains explicitly unverified. See the
[doctor runbook](../runbooks/developer-doctor.md) for flags, safe next steps,
exit codes and limitations. Bootstrap/runtime upgrades remain separately tracked.
The [doctor delivery report](../reports/2026-10-10-developer-doctor-delivery.md)
records exact checks and the live smoke's deployment boundary.

Explicit offline/local-real Compose overlays and `flint-graph-dev` now extend the
existing public-API preparation flow. Setup checks provider config and model
inventory before mutation; local-real requires a reviewed SHA-256 model lock.
Guarded bootstrap refuses to replace an incompatible active index under the
workspace lock. Optional tiny-corpus preparation is repeatable and preserves
document/version/job identities for unchanged input. The real offline ingestion
smoke and ten fresh query captures are recorded in the
[profile delivery report](../reports/2026-10-10-developer-profiles-delivery.md).
Local-real positive end-to-end hardware/model verification remains unavailable
without a separately installed embedding model; this is not claimed as proven.
See the [profile runbook](../runbooks/developer-profiles.md).

## Milestone-wide target (not yet achieved)

A new developer runs explicit offline/local-real profiles, obtains doctor
diagnostics, uploads/queries a small corpus and inspects traces. CI validates
infrastructure assets and versions; tooling is Windows/Unix friendly and never
deletes existing data.

Coordinate M15/M16/M24. Tests/doctor are offline-safe; bootstrap is opt-in and never destroys existing data.

