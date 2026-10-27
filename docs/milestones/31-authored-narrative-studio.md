# Milestone 31: authored narrative studio

Status: in progress, 2026-10-27.
[Tracking issue #113](https://github.com/mohripan/flint-graph/issues/113).
M30's package, reference player, Godot source/player and browser qualification
are complete; the studio builds on that authored runtime.

## Delivered slice

- #122: authorized projects, immutable text revisions, explicit base concurrency,
  committed recoverable conflicts, scoped metadata lists and archive/restore.
  Actual PostgreSQL constraints/queued writers and a real HTTP workflow passed.
  Final remote CI/issue closure pending.
  [Design](../superpowers/specs/2026-10-27-narrative-project-revisions-design.md),
  [contract](../architecture/narrative-project-contract.md),
  [evidence](../reports/2026-10-27-narrative-projects.md).

## Next work

- #123: focused editor/preview design, manual scene/choice editing, visible save
  and conflict recovery, isolated browser preview using the trusted shared runtime.
- #124: immutable releases, durable isolated build jobs and authorized artifacts.

Text authoring needs no model or searchable corpus. Hosted assets and AI assistance
have separate later boundaries. Existing GraphRAG data and #109 work remain preserved.
