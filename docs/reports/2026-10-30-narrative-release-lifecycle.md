# Release attempt cancellation, retry and history qualification

Scope: second #124 control-plane slice, after `f72d061` delivered initial queue
intent with [green CI 41001402769](https://github.com/mohripan/flint-graph/actions/runs/41001402769).
Build children, Temporal dispatch, object publication/download and Releases UI
remain pending. #124/M31 remain open. No actual engine execution is claimed here.

## Implemented and qualified behavior

Added scoped release item, attempts and events reads, member cancellation and
idempotent explicit retries. Queued cancellation is terminal; running cancellation
retains the fenced owner and records a request rather than claiming the process
has stopped. Repeated cancellation adds no event/outbox/audit duplicate. Completed
jobs remain completed. Cancellation stays available for archived projects.

Retry uses a new UUID/attempt number and the original release/runtime/package.
Accepted retry keys resolve their original attempt after builder disable/change
or project archive. Fresh retries reject active/completed work, archived projects,
existing artifact metadata and mismatched/unavailable pinned builders. Creation
keys still replay their original attempt, while item/list views show latest state.
All writes use the existing transaction/privacy boundary and consistent lock order.

Signed OIDC viewer mutation denial, foreign release/job/cursor combinations,
archive flags, subsequent membership revocation and header-only authentication
denial passed. Attempt/event lists are bounded; a reviewer found the event cursor
needed an int32 upper bound before asyncpg binding. The new regression failed
before the bound and passed on SQLite and actual PostgreSQL afterward. Execution
tokens/internal object keys are excluded from responses.

The same reviewer found no remaining lifecycle blocker after this correction.
Its independently unconfigured focused run passed 16 tests with 4 PostgreSQL skips;
the main run explicitly exercised the real database.

## Real HTTP and database evidence

Used only the previously owned PostgreSQL 17.10 qualification container and a
loopback Uvicorn instance on 8102 with a separate dev fixture identity. The initial
retained queued fixture was cancelled, duplicate-cancelled and inspected, then
retried into attempt 2. Creation replay still returned attempt 1; retry replay returned
attempt 2. History/item reads and bounded event replay worked. Attempt2 was also
cancelled, leaving both fixture attempts terminal before any real worker activation.

Stopped/restarted the API with builder disabled. The accepted retry key still
returned its original cancelled attempt, a fresh retry returned 503, and the same
two cancelled jobs were listed. **15 real HTTP calls passed**, including the event
cursor 422 check. The qualification API was then stopped. The main frontend/API/
isolated playtest stayed available; no creator document or provider was touched.

[HTTP proof](evidence/narrative-release-lifecycle-2026-10-30/http-proof.json)
records fixture IDs/statuses and the restart/cancel outcomes, with no token, source,
database password, raw engine log or object-store secret. Synthetic builder identity
is control-plane configuration only. Worker acknowledgement of running cancellation
and child process cleanup still require the later real-engine/Temporal proof.

## Verification

- Release API matrix with explicitly owned PostgreSQL + SQLite: **28 passed,
  4 skipped**, 16 existing Alembic path warnings; targeted final archive/scope
  additions: **4 passed**, 28 deselected, 2 existing warnings.
- Final full suite: **1247 passed, 48 skipped**, 187.64s.
- Ruff, mypy (181 source files), lock check, Compose configuration and diff checks
  passed. No migration/dependency/frontend change in this slice; the initial
  migration SQL/evaluation gates remain applicable and are recorded in its report.
- Tests arrange external worker terminal/running state for the API contract only;
  these arrangements do not claim actual engine, runner or artifact publication.

Remaining: persist claim/finish fences and artifact publication, bounded trusted
runner/transport, actual relay/Temporal/recovery, authorized downloads and UI.
