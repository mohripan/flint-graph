# Release execution ownership and private source qualification

Scope: #124's internal persisted claim/failure/cancellation/source boundary. There
is no new public command endpoint, engine dispatch or successful-publication path.
The image/child delivery in58c1733 has green CI41027750848 and container smoke
41027750792; this slice connects ownership to PostgreSQL without launching it.

An execution claim locks the scoped release then job, checks the latest attempt
and persists a fresh ownership token plus a monotonic event. Replacing a running
execution fences its former owner. A same-token replay, terminal job or superseded
user attempt cannot acquire again. Public metadata/events expose no execution
token or source. First start time is retained across recovery.

Failure/cancellation finalization accepts only the current running owner of the
latest attempt. API cancellation wins over a later engine failure, terminal
transitions revoke the token, repeated/stale cleanup has no effects, and older
cleanup cannot affect an explicitly retried job. Error codes are a closed safe
set. Completion is deliberately absent here: later verified atomic artifact
publication must be its sole path.

The private loader re-locks and checks active ownership, then cancellation, then
the exact configured compiler/runtime/Godot/toolchain/image identity. It loads the
release's scoped immutable revision, validates the text package and checks its
canonical hash against both revision and release records. Unicode/validation
failures are controlled codes. It returns an activity-local immutable package,
never a public DTO or Temporal input/result/heartbeat. The caller must commit/drop
locks before engine work and recheck ownership/cancellation at later boundaries.

Claiming precedes builder resolution, so an unavailable original builder can
produce an owned `runtime_unavailable` failure. It cannot strand accepted jobs in
queued state or prevent cancellation recovery. A claim alone authorizes no engine
launch or publication.

## Actual PostgreSQL verification

The explicit owned PostgreSQL fixture applied actual migrations in fresh unique
schemas. Tests exercised public inspection/cancel/retry APIs plus internal worker
services. Two recovery writers were observed waiting behind a real release row
lock before release. Both serialized, and exactly one subsequent owner could
finish; event sequences remained unique and monotonic. Source loads, all five
pinned-identity mismatches, cancellation-before-missing-builder ordering, stale
cleanup, terminal replay, foreign scope and safe error handling passed.

The HTTP surface in these tests is ASGI; this slice did not add a real worker or
repeat the prior socket-level HTTP/browser qualifications. The database and locks
are actual PostgreSQL. No source/index/model service is used. Disposable schema
cleanup is limited to each fixture's owned schema; user data remains intact.

## Verification

Passed:

- `uv run pytest tests/integration/test_narrative_release_execution.py -q --tb=short`:
  6 passed,1 explicit PostgreSQL skip under the default SQLite fixture.
- With `FLINT_GRAPH_NARRATIVE_PG_URL` loaded from the ignored owned fixture receipt:
  `uv run pytest tests/integration/test_narrative_release_execution.py tests/integration/test_narrative_releases_api.py -q --tb=short`:
  41 passed,5 backend-specific skips,23 existing Alembic deprecation warnings.
- Final added identity checks on both backends:
  `uv run pytest tests/integration/test_narrative_release_execution.py -q --tb=short -k 'private_input or cancelled_input'`:
  4 passed,10 deselected,2 existing warnings.
- `uv run pytest -q --tb=short`:1315 passed,52 skipped in177.01 seconds.
- `uv run ruff check .`; `uv run mypy` (184 source files); `uv lock --check`;
  `docker compose config --quiet`; `git diff --check`.

The deterministic evaluation and offline SQL generation were not repeated after
this internal-service-only change; both passed in the immediately preceding child
slice, and neither prompts/evaluation nor schema/migrations changed. Native engine
and browser tests were likewise not repeated because their code/behavior did not
change. Keep the ordinary API's release switch disabled and #124 open until the
host runner, immutable store/publication/downloads, Temporal recovery and Releases
UI/end-to-end proof are complete. The existing frontend remains running.
