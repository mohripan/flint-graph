# Milestone 31: authored narrative studio

Status: in progress, 2026-10-30. [Tracking issue #113](https://github.com/mohripan/flint-graph/issues/113).
Two of three focused issues are complete. The remaining release issue #124 has a
qualified backend/recovery path; Releases UI and final browser acceptance remain.

## Available now

- **#122 complete:** workspace-authorized projects, immutable text revisions,
  explicit base concurrency, recoverable conflicts and archive/restore.
  [Contract](../architecture/narrative-project-contract.md),
  [qualification](../reports/2026-10-27-narrative-projects.md).
- **#123 complete:** manual scene/choice editor, story map, revision history,
  conflict handling and isolated local Godot browser preview. Real engine/browser,
  CI and container smoke passed. [Qualification](../reports/2026-10-30-narrative-studio.md).
- **#124 in progress:** release/job ledger, cancellation/retry/history, execution
  fences, bounded codecs, pinned isolated Godot engine/host runner/watchdog,
  immutable objects, atomic publication and authorized source/web/manifest
  downloads. The separate relay/workflow/activities now pass an actual
  Temporal→PostgreSQL→Godot→MinIO→API download proof. Real-server tests also cover
  duplicate/closed dispatch, bounded retries and shielded cancellation.
  Separate worker/relay processes and periodic recovery are now qualified too:
  actual process kill/restart, active engine cancellation/retry and natural expired
  cleanup passed. [Current scope](../reports/2026-10-30-narrative-build-recovery.md).

## Required to finish #124 and this milestone

1. Studio Releases UI: request a saved revision, reload server state, inspect jobs,
   cancel/retry and download authorized attachments.
2. Real browser author→save→background build→download→play proof and equivalent
   authored routes, followed by reviewed documentation and green CI.

Release admission on the ordinary local API stays disabled during the Releases UI
delivery. Manual authoring and isolated preview remain available.
Text authoring needs no model or searchable corpus. AI assistance, asset authoring
and package-v2 presentation are later milestones.

## Earlier release qualification

[Ledger](../reports/2026-10-30-narrative-release-ledger.md),
[lifecycle](../reports/2026-10-30-narrative-release-lifecycle.md),
[execution](../reports/2026-10-30-narrative-release-execution.md),
[codec](../reports/2026-10-30-narrative-release-codec.md),
[trusted child](../reports/2026-10-30-narrative-build-child.md),
[host runner](../reports/2026-10-30-narrative-build-runner.md),
[publication](../reports/2026-10-30-narrative-release-publication.md),
[workflow ownership](../reports/2026-10-30-narrative-workflow-ownership.md).
These reports preserve each earlier checkpoint's exact scope and evidence.
Existing GraphRAG data and unrelated #109 work remain preserved.
