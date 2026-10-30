# Narrative workflow ownership checkpoint

Delivered under #124: migration0019 binds a release job to one accepted Temporal
run and its activity attempt. Registration starts at attempt0 independently of
worker polling. A missing queued registration is retryable; an older attempt,
different run or unknown/manual owner cannot take over that bound job. Ordinary
cleanup requires its original execution token. Supervisor cleanup additionally
checks the run, attempt, token and latest user job; it cannot undo publication.

Registered work that exhausts retries before its first claim can be finalized
without launching an engine. Run registration and ownership are internal metadata,
never public DTO fields. Compact workflow contracts accept only version1 and three
canonical UUIDs; unknown fields, private text and malformed identities are rejected.

Verification:

- `uv run pytest -q --tb=short`:1364 passed,59 explicit skips,205.40s.
- Owner/contract focused tests:18 passed,1 explicit PostgreSQL skip.
- Explicit owned PostgreSQL execution/publication matrix:42 passed,2 explicit
  skips; fresh isolated schemas applied all migrations and were removed afterward.
- `uv run ruff check .` and `uv run mypy`: passed at this ownership checkpoint
  (188 source files before the subsequent relay/adapter files).
- `uv run alembic upgrade head --sql` with test settings: passed through0019,
  1218 SQL lines. This proves generation, not a production migration.
- The sole review agent independently reproduced18 passes/1 skip and reported
  no material ownership/contract blocker.

ADR0037 describes required SDK authority. This checkpoint does not implement a
worker/workflow or qualify automatic recovery. The subsequent relay adapter and
its own real-server tests are separate work. #124/M31 stay open; release creation
on the ordinary local API remains disabled until that complete path is ready.
