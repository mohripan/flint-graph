# Committed cleanup outcome logging

Tracking: [issue #69](https://github.com/mohripan/flint-graph/issues/69).

The process previously logged `document_projection_cleanup.completed` for any
returned row, including a persisted failed attempt. It now selects completed,
failed or incomplete events and severity from committed status. Logs include only
opaque cleanup ID, enum status, attempt count and fixed warning codes. Arbitrary
provider/persisted error text and unexpected iteration exception payloads are not
logged. Return count retains its meaning of processed attempts, not successful
deletions; failed records still require explicit retry.

Tests were added first for all four statuses and iteration failure. Five new
assertions failed before the logging seam existed. Persisted failure/retry tests
check the outcome after commit, not merely an in-memory return value.

The first full-suite run exposed a cached structured-logger capture interaction
after observability configuration changed, although focused tests passed. Outcome
helpers now acquire their logger at emission time. This follows the documented
[structlog testing caveat](https://www.structlog.org/en/stable/testing.html) about
cached loggers not following capture-time configuration. The complete suite was
rerun rather than treating the narrow pass as sufficient.

## Live check

A real `cleanup_once` ran against a freshly generated PostgreSQL schema and live
Neo4j/OpenSearch. The only substituted boundary was its database connection
factory, backed by the actual isolated fixture engine; services and clients were
not mocked. Deleting from a deliberately absent UUID-named synthetic index failed
and committed FAILED, producing a warning and no completion event. Creating that
empty test index and requesting retry then committed COMPLETED, attempt count 2,
and produced the completion event. No model calls or corpus documents were used.
The temporary index and fixture schema were removed; user indexes/raw objects
were untouched.

## Gates

- Five unit outcome/privacy cases and persisted lifecycle failure/retry checks pass.
- PostgreSQL-enabled lifecycle/process suite: 57 passed, 10 conditional skips.
- Opt-in live process test: 1 passed, 1 SQLite skip.
- `uv run pytest -q` final rerun: 757 passed, 13 conditional skips.
- Final opt-in live lifecycle/process checks: 3 passed, 3 SQLite skips, including
  the process failure/retry and both partial cleanup lifecycle outcomes.
- Ruff, mypy (153 source files), lock consistency, exact deterministic eval gate,
  Alembic SQL (1,026 lines), Compose and diff checks passed.
- Frontend gates skipped: no UI changes; the previous #60 frontend/browser gates
  passed and Vite remains running on port 5173.
- Cleanup service rebuilt with inspected provider settings preserved. API, worker,
  models, raw objects, volumes and Phoenix/telemetry services were not restarted
  or removed for this slice.

Limits: the authorized ledger still retains diagnostic errors; this logging
guarantee is scoped to the cleanup process, not every third-party HTTP/SQL log.
Target counts remain attempted identities, not measured physical deletion counts.
