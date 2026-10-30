# Release ledger and initial command qualification

Scope: initial #124 control plane, not complete release/build delivery. #123 remains
delivered; #124 stays open for retry/cancel persistence, runner, Temporal dispatch,
artifact publication/download and UI. See the
[implemented contract](../architecture/narrative-release-contract.md).

## Behavior and actual proof

Added migration 0018's scoped release/job/event/artifact records, immutable identity,
initial create/list APIs, configuration-independent original-attempt replay,
workspace admission bounds, atomic ID-only queue intent and safe audit. A shared
owned-schema fixture now serves both narrative project and release contract suites.
Existing project/revision tests pass unchanged in behavior.

Actual PostgreSQL 17.10 was explicitly selected through the ignored owned-DB metadata.
Fresh unique schemas migrated through 0018 and were cleaned afterward. The public
schema of that disposable qualification database also upgraded from 0017 to 0018.
No user/default database, existing corpus or provider was used.

Real queued-writer tests held a project lock, observed a release waiting in
`pg_stat_activity`, then saved/archived through the application service. Reverting
the admission lock to `FOR UPDATE` reproduced 503 in both cases; restoring
`FOR NO KEY UPDATE` passed both. Two independent signed OIDC authors were also
observed in the same lock wait graph, then produced 202/429 under a workspace cap 1.
The test accounts for indirect/soft queue blockers and awaits all pending requests
before schema teardown. An earlier test-harness wait assumed direct blockers;
that failure was fixed and its one owned leftover schema explicitly removed.

The native matrix also demonstrated immutable release updates rejecting with
PostgreSQL SQLSTATE 55000, cross-project/workspace revision FK rejection, signed
viewer/member/archive/foreign-resource boundaries, rollback privacy, one durable
outbox intent after retry, original creation-job replay after a newer attempt,
and pagination without repeated equal-timestamp cursors. The pagination regression
failed before the SQL timestamp comparison fix and passed afterward.

An actual Uvicorn API on owned loopback 8102 made nine HTTP calls to create an
original fixture workspace/project, request/list/replay one queued release, reject
different key intent and cap overflow, and preserve project head. The API was
stopped/restarted with builder disabled under the same fixture identity. Three
more calls replayed the original 202, refused a fresh request with 503 and listed
the same single intent. This is persisted API recovery; no engine/worker/S3
execution claim follows from synthetic builder identifiers. The qualification API
was stopped afterward; the user-facing frontend/API/preview remain running.

[Sanitized HTTP proof](evidence/narrative-release-ledger-2026-10-30/http-proof.json)
contains fixture IDs/statuses and synthetic build identity, with no token, database
password, source text or object-store secret. Its queued fixture is retained for
later cancellation qualification before enabling a real narrative worker.

## Verification

- Actual owned PostgreSQL + SQLite project/release matrix before the final
  pagination regression: **41 passed, 7 skipped**, 24 existing Alembic path warnings.
- Final release matrix with actual PostgreSQL: **16 passed, 4 skipped**, 10 existing
  Alembic path warnings. Skips are PostgreSQL-only tests in the SQLite parameter.
- Fenced transition tests: **6 passed**. Reviewer's independently unconfigured
  focused run: **11 passed, 4 explicit PostgreSQL skips**; no remaining initial-slice
  blocker after the lock and creation-attempt replay corrections.
- Final full suite after the pagination correction: **1241 passed, 48 skipped**,
  174.58s. The preceding run was 1240/48 before the additional regression test.
- Ruff, mypy (181 source files), lock check, deterministic Acme evaluation,
  offline Alembic SQL (1212 lines), Compose config and diff whitespace checks pass.
- Frontend was unchanged by this slice; #123's 28 tests/typecheck/build and actual
  browser/engine proof remain applicable. The main owned API was restarted with
  building disabled, and the browser reloaded the saved studio story successfully.

Complete release acceptance remains open. An outbox row is not a running workflow;
artifact metadata schema is not published artifacts. No paid model, actual engine
child, external object store or provider key was used by this initial qualification.
