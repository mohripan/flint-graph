# Narrative build process recovery qualification

M31 #124 backend continuation of the [connected worker report](2026-10-30-narrative-temporal-worker.md).
Separate opt-in worker/relay processes, periodic exact closed-run recovery and
expired owned child/scratch cleanup are now implemented and live qualified.
Releases UI and the complete browser author/download/play acceptance remain open.

## Delivered and reviewed

Worker/relay own engines/factories from their configured database, connect an
untraced SDK client to the separate task queue and reject disabled startup before
connecting. Worker concurrency is 1. Periodic closed-run recovery verifies the
exact original workflow, snapshots ownership, releases locks for cleanup and
compares the same snapshot before finalization. Running/unknown/manual/foreign
ownership is left untouched; run0 recovery works without a first claim or image.

New first-party scratch receipts expire after 240 seconds. Metadata/owner reads are
bounded, regular-file/symlink/root checks precede use, and removal verifies exact
token/image/expiry plus immutable container ID. Scan progress and small pending
queues avoid starving later entries. Sweeps back off after failure and have soft
between-operation budgets; DB run inspection has its own observation/pass budget
and fair cursor. Independent maintenance loops keep a held Docker sweep from
blocking database recovery. Legacy/unknown/unexpired data and creator exports are
retained. Object-store orphan retention remains separate.

The sole reviewer found and rechecked two liveness fixes: retained entries hiding
expired work after the first 1000 files, and sequential maintenance blocking DB
recovery during long Docker/Temporal failures. No material blocker remained.

## Actual qualification

Only the existing owned PostgreSQL/MinIO/Temporal fixtures and explicitly prepared
Godot 4.7.2 image were used. No user project/head, financial corpus, provider key,
paid model or default Docker service was changed. Temporary projects used a
separate qualification principal and were archived after verification.

The real HTTP process proof:

1. Created an original text-only three-ending fixture and requested a release via
   the API. Separate production relay/worker processes accepted and ran it.
2. Observed its actual Godot child running. Verified the exact owned worker PID,
   executable and bootstrap command, then hard-stopped only that process.
3. Restarted the same worker role/root/queue. Activity attempt 2 on the same
   workflow run completed; all 3 source/web/manifest downloads matched their
   persisted hashes. Only the replacement's artifact namespace was published.
4. Checked the actual workflow history: the synthetic private source canary and
   old execution token were absent. The canary was present in downloaded source.
5. Waited for the original unmodified 240-second expiry. Periodic cleanup removed
   both leftover child and scratch naturally, preserving an owned sibling sentinel.

[Sanitized process receipt](evidence/narrative-build-recovery-2026-10-30/process-proof.json).
This is an actual worker-process kill/restart proof, distinct from earlier task-
cancellation and test-Worker probes. The independent 180-second absent-supervisor
watchdog was qualified separately in the trusted-child report.

A second real HTTP proof cancelled another observed active Godot build. Its child
and scratch disappeared; cancelled downloads returned 404 and no artifact metadata
was published. Explicit user retry created a different job for the same immutable
package, completed with exactly 3 verified artifacts and replayed the retry key to
that same job. The cancelled old job remained terminal without a fence.
[Sanitized cancel/retry receipt](evidence/narrative-build-recovery-2026-10-30/cancellation-proof.json).

## Checks

- `uv run pytest -q --tb=short`: 1393 passed, 71 explicit skips, 217.50s.
- Explicit native builder/connected-worker matrix: 6 passed, 3 SQLite skips, 39.14s.
  Includes actual expired-container cleanup preserving an unexpired sibling and
  exact terminated-run recovery against Temporal/PostgreSQL.
- SQLite/actual PostgreSQL focused recovery matrix: 8 passed. Includes cleanup
  without locks, stale snapshot rejection, blocked inspection budget and held
  sweep not blocking DB recovery. Sole reviewer independently reproduced 12 focused
  passes across sweep/maintenance/recovery/settings.
- Runner unit seam: 14 passed, including deterministic scan past 1000 retained siblings.
- `uv run ruff check .`, `uv run mypy` (195 source files), `uv lock --check`,
  deterministic acme-smoke eval, test-configured offline migration SQL,
  `docker compose config --quiet`, `git diff --check`: passed.

Frontend source is unchanged in this backend checkpoint; browser release
acceptance is deliberately not claimed. The ordinary local API still has release
admission disabled during UI delivery. Existing manual editor/API/preview remain
available. Unrelated #109 WIP is unchanged. [Operator runbook](../runbooks/narrative-build-worker.md).
