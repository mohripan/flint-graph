# ADR 0015: Reproducible developer experience

- Status: accepted; doctor and native observability validation implemented, remaining tools planned
- Date: 2026-10-10
- Track: developer experience; Milestone 26; epic [#36](https://github.com/mohripan/flint-graph/issues/36)

## Decision

Provide a read-only doctor command before expanding bootstrap automation.
Report nonsecret effective configuration, service/model readiness, active tenant
index and coverage using authorized public APIs. Distinguish offline fixture
checks from live readiness; no implicit paid calls, downloads or mutations.

Keep explicit offline and local-real profiles. Guard bootstrap using the public
API and immutable ingestion/index contracts; never reset volumes, delete existing
workspaces or silently switch embedding dimensions. Document Windows and Unix
commands and an opt-in tiny corpus path. Reuse M16 preparation/capture rather than
inventing a second test harness.

Version-pin services and CI runtime choices with reviewed upgrades. Validate
Prometheus, Alertmanager and Collector configs with native tools, not YAML alone.
Keep the deterministic PR quality gate offline and baselines manually reviewed.
Debug bundles/links are role-authorized, redact secrets/payloads and preserve
correlation with trace, query and job identifiers. Operator tools must not become
an alternate route around the workspace access boundary.

## Delivery

[#48 doctor](https://github.com/mohripan/flint-graph/issues/48),
[#49 profiles](https://github.com/mohripan/flint-graph/issues/49),
[#50 pins and CI](https://github.com/mohripan/flint-graph/issues/50),
[#51 native observability validation](https://github.com/mohripan/flint-graph/issues/51),
[#52 debugging handoff](https://github.com/mohripan/flint-graph/issues/52).
The read-only doctor and native observability validation are implemented.
See the [doctor runbook](../runbooks/developer-doctor.md) and
[Milestone 26](../milestones/26-developer-experience.md) for delivered behavior;
profiles, version upgrades and product debugging handoff remain separate issues.

