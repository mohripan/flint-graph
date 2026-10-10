# Partial retrieval projection cleanup delivery

Tracking: [issue #67](https://github.com/mohripan/flint-graph/issues/67).
Depends on [bulk validation #68](https://github.com/mohripan/flint-graph/issues/68).

Eight new lifecycle regressions failed before implementation: incomplete coverage
did not create cleanup work, and direct replay accepted stale sources. Cleanup now
schedules all recorded coverage identities, cancels running attempts on deletion
and supersession, and targets all persisted chunk identities regardless of batch
counters. Scoped records and retries remain idempotent. Reconciliation uses the
Document-first lock through both external writes and refuses stale versions;
completed-coverage scanners select only active/non-deleted sources.

## Verification

- `uv run pytest -q`: 723 passed, 12 conditional skips.
- PostgreSQL-enabled lifecycle/indexing/retrieval suite: 67 passed, 8 conditional
  skips; includes actual concurrent stale-session replay checks.
- Opt-in live partial-projection tests: 2 passed, 2 SQLite skips. Both deletion and
  supersession removed one physically present chunk while a second target was
  already missing and counters were zero. Other-tenant lexical/vector records and
  other-index vector records survived. Subsequent direct replay was refused and
  could not recreate removed records.
- First live run failed during fixture teardown because rollback expired an ORM
  index-name field; assertions had run but it was not counted as a passing test.
  Teardown now retains an immutable physical name, and the rerun passed. Both
  temporary indexes left by the first run were explicitly removed after read-only
  identification. All fixture schemas and UUID-scoped synthetic nodes were removed.
  Project indexes, user documents and raw objects were untouched.
- Ruff, mypy (151 source files), lock consistency, deterministic evaluation gate,
  Alembic SQL (1,026 lines), Compose and diff checks passed.
- Frontend gates skipped: backend-only change; previously verified Vite UI remains
  running at `http://127.0.0.1:5173`.
- API and ingestion worker rebuilt with their inspected model settings preserved;
  API answer/support remain Ollama. The cleanup service had no running container
  and was built/started using the worker's offline-safe provider configuration.
  API readiness and the Vite endpoint were checked after recreation. No volume
  reset or removal of Phoenix/telemetry services was performed.

No model calls or corpus-quality claims were made. Counts are cleanup targets, not
measured physical deletions. Historical already-stale attempts are not automatically
rescheduled. Missing authoritative coverage and hard erasure remain out of scope.
Document locks can include external IO, so publication/deletion latency is not
hard-bounded; see ADR 0020 and the scoped repair runbook.
