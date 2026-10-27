# Verify narrative project editing locally

The [API contract](../architecture/narrative-project-contract.md) describes roles,
source limits, stable idempotency keys and recoverable conflicts. Manual text
creation requires no corpus or model. The browser authoring editor follows in
#123; `/docs` exposes these APIs in a development deployment.

## Offline and actual PostgreSQL tests

```powershell
uv run pytest tests/integration/test_narrative_projects_api.py tests/integration/test_narrative_request_boundary.py -q --tb=short
```

Normal tests use isolated SQLite files with FKs enabled and never select an
existing workspace database. For actual row locks, immutable-row triggers and
deployed composite references, explicitly select an **owned disposable** PostgreSQL
database with schema/extension creation privileges:

```powershell
$env:FLINT_GRAPH_NARRATIVE_PG_URL='postgresql+asyncpg://<fixture-user>:<fixture-password>@127.0.0.1:<owned-port>/<owned-database>'
uv run pytest tests/integration/test_narrative_projects_api.py tests/integration/test_narrative_request_boundary.py -q --tb=short
```

The fixture generates a unique `narrative_test_<UUID>` schema, applies real
migrations with its own version ledger and removes only that generated schema.
The explicit opt-in has no default workspace URL. It still requires an owned
database: migrations may create the shared `pg_trgm` extension. Do not point the
qualification at a production/user database or assume SQLite proves locking.

The concurrency test uses two signed independent member identities. It holds
the scoped project lock, observes both real PG sessions waiting, releases it and
checks one accepted edit plus one recoverable conflict. Other tests cover roles,
revocation, foreign references, retries, archive/restore, strict source rejection,
bounded metadata lists, SQL failure privacy and request memory/rate limits.

## Real HTTP proof

For an explicitly owned local server/database, apply migrations through `head`,
start the API on loopback with `env=test`, dev auth and telemetry disabled, and
use its chosen port. Keep this separate from existing user services/data. No model
or background worker is invoked by this probe.

```powershell
uv run python tools/narrative/probe_projects.py --url http://127.0.0.1:8101 --output notes/my-new-http-proof.json
```

The helper creates a new synthetic workspace/project and performs 15 actual HTTP
requests: create/retry, save/retry, stale-save/recover/retry, current head/history,
archive, explicit archived read and restore. It never searches or edits existing
documents/workspaces. It leaves its new fixture available for inspection and
writes a new evidence file; choose a new filename for another probe. An unsuccessful
probe can leave its new partial fixture. Workspace cleanup is not part of #122.

Local development used an owned read-only-root PG **17.10** container with tmpfs
data and a unique loopback port, plus a separate hidden loopback API process.
No production deployment, existing database migration or user corpus was touched.
See the [delivery report](../reports/2026-10-27-narrative-projects.md) for actual
results. The M30 [playable game](narrative-web-play.md) remains independent of
these API processes.
