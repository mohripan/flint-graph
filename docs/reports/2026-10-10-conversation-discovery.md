# Conversation title discovery and rename verification

Tracking: [#98](https://github.com/mohripan/flint-graph/issues/98), UI prerequisite #73.
Contract: [conversation API](../architecture/conversation-contract.md).

## Outcome

Delivered member-authorized strict title-only rename and tenant-scoped literal
title search. Titles/search reject NUL and enforce 200-character bounds. Renaming
preserves created-at/UUID ordering, original questions, turn identities, query
state, idempotency and usage. Existing row locking serializes renames; last
committed title wins. No migration, erasure or inference is introduced.

HTTP regressions failed before rename and search implementation. Further NUL
and capability regressions failed before their guards were added. Cases cover
literal wildcard/escape/backslash search, empty and missing search, actual cursor
paging, foreign cursors/resources, archive visibility, strict body validation,
member/viewer permissions and membership revocation. Discovery is advertised as
`conversation_discovery=true`; broad chained memory remains false.

## Live verification

Only the API was rebuilt, preserving runtime provider settings and other services.
Final image config:
`sha256:be81a8536a403afc288289f000cae40436c520e2d21ea3a52e72a6c96603e3ec`.
Live checks used the existing agent-created synthetic workspace
`d48f7d9a-9bc9-446d-ab90-bbf45b039f9a`, never the user's private corpus.

Conversation `03a2e550-7063-4320-9d48-ca7704f5a615` was renamed to
`Storage-only live verification (renamed)`. Its two cancelled turns and empty
invocation ledgers remained exactly unchanged; its next-turn counter stayed 3.
Three additional clearly synthetic conversations were retained for inspection:
`d4a22133-b39b-43af-8a38-09b41e2c24cf`,
`83492888-2aed-41a4-8457-cbf2d207dd56`,
`929f072c-d89b-4a26-951c-3d84553797b6`.

Real API checks passed for trimmed rename/reopen, literal `%`, `_`, `!`, backslash
and case-insensitive search, search cursor paging, archive exclusion/inclusion,
archived/foreign rename 404, invalid body/NUL rejection and zero new inference.
The temporary archive was reopened; no material data was deleted. API-only
restart then preserved the saved title, counter, turn count and discovery
capability. Local recording: `notes/conversation-discovery-live-2026-10-10.json`.

## Exact checks

- Final `uv run pytest -q --tb=short`: 914 passed, 15 expected skips.
- Final PG-enabled `tests/integration/test_conversations_api.py`: 27 passed,
  2 expected SQLite row-lock concurrency skips.
- `uv run ruff check .`: passed.
- `uv run mypy`: passed, 160 source files.
- `uv lock --check`: passed.
- AGENTS.md offline Acme evaluation command: passed; baseline unchanged.
- `FLINT_GRAPH_ENV=test; uv run alembic upgrade head --sql`: passed, 1061 lines;
  no new schema migration.
- `docker compose config --quiet`, API-only rebuild and `git diff --check`: passed.
- Live fixture script and final read-only restart/capability checks: passed.
- Frontend `http://localhost:5173`: HTTP 200 and left running. Local frontend
  build/browser suites skipped because this slice changes no frontend files.

No production substring-search throughput, private per-user threads, full UI,
retention deletion, general memory, query durability or paid-inference claim.
The browser interface and realistic multi-turn quality gates remain #73/#74.
