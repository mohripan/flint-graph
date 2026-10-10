# Conversation stream authorization verification — 2026-10-11

Scope: [#100](https://github.com/mohripan/flint-graph/issues/100), the execution-capable
SSE GET for queued conversation runs. No migration, new provider, memory expansion
or durable execution change.

## Defect and boundary

Before the fix, an OIDC viewer could start a queued conversation run through
`GET /v1/query-runs/{id}/events/stream`, despite member-only turn submission and
cancellation. The first signed-token HTTP regression expected 403 but received
200 and executed a clarification run. This was reproduced before implementation.

The endpoint now loads the authorized run, checks actual tenant-scoped turn
references for queued runs, and requires current member/admin/owner membership
before constructing the execution stream. It does not trust conversation
metadata. Viewers can inspect runs/events/usage/provenance and replay non-queued
conversation events. Existing viewer-accessible standalone-query policy stays
unchanged. Ordinary inspection GETs remain non-executing; the SSE GET is the
explicit exception. Authorization is checked at request entry, not continuously
inside a previously authorized stream. Concurrent queued execution claims and
atomic mid-request revocation remain durable-execution work, not this fix.

HTTP tests cover both independent and elliptical queued questions, absent/forged
metadata, all three execution roles, completed/running/failed/cancelled replay,
missing credentials, foreign runs, membership disablement and role downgrade.
Denials leave run state, events and invocation usage unchanged. Assertions use
the public API. Identity-provider JWKS and external projection services are
fixture boundaries; the JWT verifier, database, query graph and accounting are
real. PostgreSQL tests create isolated UUID schemas and do not modify corpus
tables. Replay tests cover state advanced before the GET, not a simultaneous
multi-executor stress test.

## Live local check

Only the API was rebuilt, preserving configured local Gemma/Ollama answer/support
and deterministic-test 384-dimensional embedding settings. Migration remains
`0016_conversation_ledger` (head). API image:
`sha256:a05ebf29c28354838b53262adf9dcb7ba3bfafaddf9a09cbd9a849b37d0c6c17`.

In public FinQA workspace `2eab2f78-208e-4eb9-97a2-087e40af0525`, a new conversation
`8c1f0e7f-3245-4b10-ae06-765747761e53` submitted “What about the prior year?”
Run `02518651-878c-4d4a-aed7-0fa76e5782e9` moved from queued to completed with a
clarification, complete zero-invocation accounting, and no inherited history.
Terminal replay matched the original stream and left run/events/usage and search
readiness unchanged. The local deployed API uses dev auth; viewer/revoked OIDC
behavior was verified separately through signed-token HTTP tests on real isolated
PostgreSQL, not a deployed external identity provider.

An owned agent-browser session reopened the existing two-turn public thread
through the actual frontend/backend at 390px and 1280px. The composer stayed
visible, the document had no horizontal overflow, and no write or inference was
triggered. The mobile screenshot was inspected. Frontend localhost:5173 remains
running; workers, private documents, volumes and optional telemetry services were
left unchanged. Detailed public/synthetic artifacts are gitignored under `notes/`.

## Commands

Passed:

- `uv run pytest -q --tb=short`: 929 passed, 15 skipped.
- `FLINT_GRAPH_PG_INTEGRATION=1 uv run pytest -q tests/integration/test_conversations_api.py tests/integration/test_query_api.py --tb=short`: 136 passed, five skips.
- `uv run ruff check .`; `uv run mypy`: clean, 160 source files.
- `uv lock --check`; deterministic Acme evaluation gate.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: 1061 lines.
- `docker compose config --quiet`; `git diff --check`.
- Frontend `npm test`: 10 passed; `npm run typecheck`; `npm run build`.
- API-only Compose rebuild, runtime Alembic head inspection, fresh live dev-auth
  execution/replay and read-only desktop/mobile browser reopening.

Not run for this server-only boundary fix: another full synthetic browser suite
(the unchanged #99 suite passed previously), fresh substantive model-quality
capture, private-corpus queries, paid providers, remote/OIDC-browser deployment,
load tests, continuous-stream revocation or optional local telemetry fan-out.
The previous test run was interrupted; its result was not counted. A subsequent
test-edit placement mistake was corrected before the complete passing runs above.
CI outcome is recorded in the issue after push. Broader memory, quality,
accessibility, retention and durable-execution parent issues remain open.
