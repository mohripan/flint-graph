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
  The standalone bounded USTAR/ZIP codec is now implemented:49 focused tests,
  1296 full-suite passes/48 skips, clean Ruff/mypy and an actual constrained Docker
  transport receipt. Review caught/fixed short-read memory amplification.
  [Codec scope/evidence](../reports/2026-10-30-narrative-release-codec.md).
  This is not yet an engine, deadline, publication or download delivery.
  The next slice qualifies an explicitly prepared Linux Godot image and trusted
  child:13 offline cases and3 actual container cases, including export/tamper
  rejection and a182.219-second absent-supervisor watchdog exit. Full offline suite:
  1309 passed/50 skipped. [Child scope/evidence](../reports/2026-10-30-narrative-build-child.md).
  Host runner/fence integration, storage/publication/downloads, Temporal and UI
  remain pending; the issue stays open.
  Claim/non-success finalization and private immutable input loading are now
  persisted with release/job fences and actual queued PostgreSQL recoveries.
  Combined native database/API matrix:41 passed/5 backend skips; full suite:
  1315 passed/52 skipped. [Execution scope/evidence](../reports/2026-10-30-narrative-release-execution.md).
  Successful completion remains exclusive to future verified publication; host
  runner, store/downloads, Temporal and Releases UI remain open.
  The standalone host runner is now qualified too: effective settings are checked
  before start, source/output hashes are verified, web licenses/notices included,
  and repeated cancellation safely joins pipes/processes and preserves sibling
  files.58 focused passes;1324 full-suite passes/54 skips;2 actual image cases.
  [Runner scope/evidence](../reports/2026-10-30-narrative-build-runner.md).
  Activity integration, startup recovery, store/publication/downloads, Temporal
  and Releases UI/end-to-end acceptance remain open.

Text authoring needs no model or searchable corpus. Hosted assets and AI assistance
have separate later boundaries. Existing GraphRAG data and #109 work remain preserved.
