# Conversation ledger foundation verification

Tracking: [#96](https://github.com/mohripan/flint-graph/issues/96), parent #62.
Design: [ADR 0026](../adr/0026-conversation-ledger-foundation.md).

## Outcome

Tenant-authorized conversation creation/reopen, ordered turn/run references,
idempotency, stable paging, queued cancellation and archive/reopen are delivered.
PostgreSQL serializes submissions; composite foreign keys enforce tenant links.
Old standalone runs remain unchanged. Capabilities explicitly distinguish ledger
availability from chained memory, which remains false. No earlier answers are
trusted, summarized, concatenated or supplied to new prompts by this slice.

HTTP regressions preceded initial create/turn/archive/cancellation behavior.
Stable paging tests exposed a SQLite persisted-versus-rebound timestamp precision
bug; comparing the cursor's persisted timestamp in SQL fixed it. Archive and
cancellation tests exposed implicit async ORM reloads of `updated_at`; explicit
refresh before serialization fixed them. Further cases qualify conflicting
replay, active-turn policy, ordered paging, foreign cursors, index deprecation,
OIDC viewer/member roles and membership revocation. PostgreSQL concurrency tests
use distinct sessions at the service boundary, not requests serialized by the
same authentication user-row update. Same-key submissions yield one turn/run;
different keys yield one acceptance and one conflict.

## Live storage and migration checks

Applied migration `0016_conversation_ledger` using the deployed API image's
`/app/.venv/bin/alembic upgrade head`; `alembic current` confirms head. Read-only
PostgreSQL inspection confirms both composite FKs and ordinal/key/run constraints.
The runtime image does not include `uv`; an initial attempted `uv run alembic`
container command did not execute, then the installed executable was used.
No volumes, existing tables, source documents or historical runs were removed.

Created a dedicated synthetic fixture workspace:
`d48f7d9a-9bc9-446d-ab90-bbf45b039f9a`.
Its one clearly labelled synthetic document was uploaded through the real intake
API and became searchable through the existing worker pipeline.
Document: `ada58cee-02d6-44d7-ab99-30faeab2bd8a`;
version: `ea3b5a30-6195-4916-bfef-1cecdac8882b`.
It is not part of the pinned 100-document public financial corpus.

Conversation: `03a2e550-7063-4320-9d48-ca7704f5a615`.
Ordered turn IDs:
`5414bf61-b0b6-48db-97fc-c90e0f90e29d`,
`3c1abb53-8fef-414d-9715-3ecfe67a8e6e`.
Run IDs:
`d867095f-ba26-496a-bf40-a4e9e1df0974`,
`6c8ed285-47a0-4f94-9fa2-160376ecfc02`.

Real API checks verified replay, payload conflicts, queued cancellation without
inference, foreign-workspace 404, archive/reopen and ordered cursor replay.
Both runs are cancelled; no query provider invocation was dispatched.
The local verification script's final intake-report field initially used the
wrong response key after its mutation checks; that reporting mistake was fixed,
and read-only inspection completed against the same stored fixture, not another
workspace. API-only restart then preserved the same IDs, ordinals, run states,
next counter 3 and independent-memory metadata. This proves persisted storage
reopen, not in-flight SSE durability or model follow-up quality.

The synthetic fixture is retained for inspectable evidence. The user's private
corpus was not read, restored, re-uploaded or altered. No query model downloads,
paid inference, new runner or external service exposure was introduced.

## Exact checks

- `uv run pytest -q --tb=short`: 875 passed, 15 skipped.
- PG-enabled conversation/API/accounting suite: 112 passed, 5 skipped.
- `uv run ruff check .`: passed.
- `uv run mypy`: passed, 158 source files.
- `uv lock --check`: passed.
- AGENTS.md Acme deterministic eval command: passed; baseline unchanged.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: passed, 1061 lines.
- Applied migration and read-only constraint inspection: passed.
- `docker compose config --quiet`, `git diff --check`: passed.
- Real storage API checks before/after API restart: passed.
- Frontend `http://localhost:5173`: HTTP 200, left running. Local frontend
  test/typecheck/build/browser thread checks skipped: no frontend implementation.
- Live multi-turn inference/quality, memory deletion/invalidation, parent budget,
  workflow replay and retention/purge qualification skipped: not delivered by
  this slice. #62/#73/#74/#75/#82 remain open.
