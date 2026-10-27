# Narrative projects and immutable revisions delivery

Date: 2026-10-27. M31 #122, migration **0017_narrative_projects**.
[Design](../superpowers/specs/2026-10-27-narrative-project-revisions-design.md),
[ADR 0036](../adr/0036-immutable-authored-revisions-and-recoverable-conflicts.md),
[contract](../architecture/narrative-project-contract.md).

The API creates a workspace-owned blank playable text game without a corpus,
model or worker. Saves append canonical source/notices with stable M30 hashes,
explicit bases and idempotency keys. Stale work commits as a recoverable conflict
revision before its 409 response, preserving the current head. Signed identities,
workspace roles, revocation, foreign-resource 404s and archive/restore are enforced.
Revision metadata lists and their cursor queries avoid loading source text.

## Actual database and HTTP proof

An owned **PostgreSQL 17.10** container used immutable local image
`sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`,
read-only root, tmpfs data/runtime directories and a unique loopback port. It did
not mount or modify an existing user database. Tests applied all real migrations
in generated schemas with scoped version ledgers; SQLite enabled FKs. Afterward,
zero generated test schemas remained. Migration 0017 also actually deployed to
that owned database's public schema for a separate HTTP server.

Native checks rejected revision overwrite/delete and cross-project head/parent
references. Two independently signed member identities were both observed waiting
on the held project lock. After release, one edit became current and the other
persisted as a conflict; both original texts were recovered through the API.

A hidden loopback API with explicit test/dev-auth settings passed **15 actual HTTP
requests**: create/retry, save/retry, stale-save/recover/retry, head/history and
archive/restore. [Public evidence](evidence/narrative-projects-2026-10-27/http-proof.json)
contains statuses, fixture IDs and a hash. The probe created its own synthetic
workspace; no existing documents/workspaces were searched or edited.

## Review and corrections

The single authorized reviewer found inherited gaps: missing narrative rate
coverage, unbounded streamed bodies and possible SQL exception prose disclosure.
The implementation adds early bounded buffering and a safe commit boundary.
An injected commit failure carrying a prose canary returned generic 503 without
source in responses/logs; retry succeeded once without duplication.

Retaining ASGI message objects also allowed 50,000 empty frames to consume about
**9.6 MiB** for an 18-byte body. The regression failed before coalescing and passes
below its 1 MiB peak allowance afterward. Equivalent bearer whitespace/UUID forms
could bypass raw-string rate keys: that regression failed with 200 before the fix
and passes with 429 afterward. Keys now normalize and hash credentials, and the
narrative tracker bounds capacity/expiry without evicting active entries. The
reviewer independently reran the final boundary module: **7 passed**.

The first broad run exposed a middleware test's setup assumption after real routes
were added and an old enum test requiring future actions in migration 0015.
The former now uses a dedicated public middleware probe. The latter verifies
actual unconstrained VARCHAR compatibility and preservation of old values; no
historical migration was rewritten. Actual PG audit insert/readback passed.

## Verification

| Command / boundary | Observed result |
| --- | --- |
| `uv run pytest -q --tb=short` | **1228 passed, 43 skipped, 157.11s** |
| Explicit owned `FLINT_GRAPH_NARRATIVE_PG_URL`; `uv run pytest tests/integration/test_narrative_projects_api.py tests/integration/test_narrative_request_boundary.py -q --tb=short` | **34 passed, 3 skipped, 31.28s**; 15 Alembic configuration deprecation warnings |
| Final metadata-cursor optimization, `-k lists_are` with actual PG enabled | **2 passed**, SQLite and deployed PG |
| Boundary/security suites after guardrail fixes | **11 passed** |
| `uv run python tools/narrative/probe_projects.py --url http://127.0.0.1:8101 --output notes/narrative-http-proof-20261027.json` | **15 HTTP requests passed** |
| Explicit owned DB `uv run alembic upgrade head` | All migrations through 0017 actually applied |
| `uv run ruff check .` | Passed |
| `uv run mypy` | Passed, 176 source files |
| `uv lock --check` | Passed, 104 packages |
| Acme deterministic evaluation from AGENTS.md | Passed, unchanged thresholds |
| `FLINT_GRAPH_ENV=test; uv run alembic upgrade head --sql` | Passed, 1116 lines; offline generation |
| `docker compose config --quiet` | Passed |
| `git diff --check` | Passed |

Offline skips include unconfigured live/engine/container integrations and the
host's unprivileged symlink. Three SQLite cases skip PG-only trigger/locking/FK
proof; those cases passed on actual PG. The final cursor optimization preserves
public behavior and passed both backend tests.
[CI](https://github.com/mohripan/flint-graph/actions/runs/40501201632) and
[real container smoke](https://github.com/mohripan/flint-graph/actions/runs/40501202072)
passed for `9dfcf74`; #122 is closed. Preserved #109 WIP participates locally but
is excluded from this delivery.

No engine runtime or React frontend changed; M30's separate real play proof was
not repeated for these API changes. This is the editor's foundation, not a complete
editor/release service. Assets, AI assistance, automatic merge, retention/hard
deletion, distributed quotas, hosted-code isolation and production deployment
remain later work. No paid model, user corpus or existing service configuration
was changed. [Repeat the checks](../runbooks/narrative-project-api.md); continue #123.
