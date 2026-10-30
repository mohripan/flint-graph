# Milestone 31: authored narrative studio

Status: in progress, 2026-10-27.
[Tracking issue #113](https://github.com/mohripan/flint-graph/issues/113).
M30's package, reference player, Godot source/player and browser qualification
are complete; the studio builds on that authored runtime.

## Delivered slices

- #122: authorized projects, immutable text revisions, explicit base concurrency,
  committed recoverable conflicts, scoped metadata lists and archive/restore.
  Actual PostgreSQL constraints/queued writers and a real HTTP workflow passed.
  CI and real container smoke passed; the issue is closed.
  [Design](../superpowers/specs/2026-10-27-narrative-project-revisions-design.md),
  [contract](../architecture/narrative-project-contract.md),
  [evidence](../reports/2026-10-27-narrative-projects.md).

- #123: editor and isolated local Godot preview implemented and live qualified;
  CI and real container smoke passed; issue closed. [Report](../reports/2026-10-30-narrative-studio.md).

## Next work

- #124: immutable releases, durable isolated build jobs and authorized artifacts.
  [Focused design](../superpowers/specs/2026-10-30-narrative-releases-design.md)
  and [implementation plan](../superpowers/plans/2026-10-30-narrative-releases.md)
  are committed after the same reviewer checked fencing, replay and transport
  bounds. Implementation started with a pure fenced-attempt transition boundary:
  queued cancellation, active execution replacement, stale cleanup/publication,
  completion-before-cancel and recovery cleanup have six passing unit tests.
  Ruff and mypy (177 source files) pass. These tests establish transition behavior;
  the actual engine jobs and artifact downloads are still pending. The initial
  ledger/create/list API is now implemented with actual PostgreSQL and 12 real HTTP
  calls, including process restart/disabled-builder replay. Default building stays
  disabled. Final full suite: 1241 passed/48 skipped. [Initial ledger contract](../architecture/narrative-release-contract.md)
  and [qualified scope](../reports/2026-10-30-narrative-release-ledger.md).
  Retry/cancel/history persistence is now qualified with 15 more actual HTTP calls,
  including disabled-builder restart replay; both synthetic fixture attempts are
  cancelled. Final lifecycle suite: 1247 passed/48 skipped, and actual PostgreSQL
  release API matrix: 28 passed/4 parameter skips. [Lifecycle scope/evidence](../reports/2026-10-30-narrative-release-lifecycle.md).
  Claim/finish integration, relay/Temporal, runner, publication/download and release
  UI remain open. The existing studio/API/preview remain running.

Text authoring needs no model or searchable corpus. Hosted assets and AI assistance
have separate later boundaries. Existing GraphRAG data and #109 work remain preserved.
