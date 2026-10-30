# Milestone 31: authored narrative studio

Status: complete, 2026-10-30. [Tracking issue #113](https://github.com/mohripan/flint-graph/issues/113).
All three focused issues are delivered with real engine, browser, database and
job qualification.

## Available now

- **#122 complete:** workspace-authorized projects, immutable text revisions,
  explicit base concurrency, recoverable conflicts and archive/restore.
  [Contract](../architecture/narrative-project-contract.md),
  [qualification](../reports/2026-10-27-narrative-projects.md).
- **#123 complete:** manual scene/choice editor, story map, revision history,
  conflict handling and isolated local Godot browser preview. Real engine/browser,
  CI and container smoke passed. [Qualification](../reports/2026-10-30-narrative-studio.md).
- **#124 complete:** immutable releases of saved revisions, built by separate
  opt-in relay/worker processes in a pinned, network-none Godot 4.7.2 container,
  with cancellation, retry, recovery, atomic publication and authorized
  source/web/manifest downloads. The Studio **Releases** dialog requests builds,
  follows server state across reloads, cancels/retries for members and verifies
  downloads in the browser. A live author → save → build → download → play proof
  matched four authored routes across the Studio preview, the release web build
  and a web export of the downloaded editable source.
  [Releases UI and end-to-end report](../reports/2026-10-30-narrative-releases-ui.md),
  [recovery](../reports/2026-10-30-narrative-build-recovery.md).

The live proof found and fixed an export defect: browser builds published before
the fix contain an empty `project.binary` and do not boot. Build a new release of
the same saved revision to replace one.

Text authoring needs no model or searchable corpus. Building needs the explicit
operator setup in the [worker runbook](../runbooks/narrative-build-worker.md).
AI assistance, asset authoring and package-v2 presentation are later milestones;
this is not yet a complete AI production product.

## Earlier release qualification

[Ledger](../reports/2026-10-30-narrative-release-ledger.md),
[lifecycle](../reports/2026-10-30-narrative-release-lifecycle.md),
[execution](../reports/2026-10-30-narrative-release-execution.md),
[codec](../reports/2026-10-30-narrative-release-codec.md),
[trusted child](../reports/2026-10-30-narrative-build-child.md),
[host runner](../reports/2026-10-30-narrative-build-runner.md),
[publication](../reports/2026-10-30-narrative-release-publication.md),
[workflow ownership](../reports/2026-10-30-narrative-workflow-ownership.md),
[connected worker](../reports/2026-10-30-narrative-temporal-worker.md).
These reports preserve each earlier checkpoint's exact scope and evidence.
Existing GraphRAG data and unrelated #109 work remain preserved.
