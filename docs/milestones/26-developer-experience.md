# Milestone 26: Developer experience and reproducible environments

Status: planned; implementation issues are delivered independently.
Track: developer experience.
Epic: [#36](https://github.com/mohripan/flint-graph/issues/36).
Design: [ADR 15](../adr/0015-reproducible-developer-experience.md).

## Issue queue

| Issue | Scope | State |
| --- | --- | --- |
| [#48](https://github.com/mohripan/flint-graph/issues/48) | Add a read-only developer doctor command with actionable readiness diagnostics | planned |
| [#49](https://github.com/mohripan/flint-graph/issues/49) | Add reproducible offline and local-real bootstrap profiles | planned |
| [#50](https://github.com/mohripan/flint-graph/issues/50) | Pin service images and modernize CI runtimes with reviewed upgrade policy | planned |
| [#51](https://github.com/mohripan/flint-graph/issues/51) | Validate observability assets with native tools in CI | planned |
| [#52](https://github.com/mohripan/flint-graph/issues/52) | Improve query and ingestion debugging handoff from the product UI | planned |

## Acceptance and boundaries

A new developer runs explicit offline/local-real profiles, obtains doctor diagnostics, uploads/queries a small corpus and inspects traces. CI validates infrastructure assets and versions; tooling is Windows/Unix friendly and never deletes existing data.

Coordinate M15/M16/M24. Tests/doctor are offline-safe; bootstrap is opt-in and never destroys existing data.

