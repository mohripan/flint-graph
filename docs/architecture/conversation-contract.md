# Conversation ledger contract

Delivered foundation: #96 / [ADR 0026](../adr/0026-conversation-ledger-foundation.md).
Grounded follow-up memory remains #62/#75, UI #73, quality #74, budgets #82.

Conversations are workspace-shared PostgreSQL records. Membership, not a thread
ID or tenant header alone, authorizes them. Viewer reads; member creates/submits/
cancels queued turns; admin archives/reopens. Foreign resource/cursor 404 follows
workspace authorization; invalid/revoked membership receives the existing 403.
Titles are bounded display text. Conversation creation does not make an index.

| Endpoint | Contract |
| --- | --- |
| `POST /v1/conversations` | Optional title, default `New conversation`; 201 |
| `GET /v1/conversations` | `limit=1..100`, `before_id`, `include_archived`; newest-created first |
| `GET /v1/conversations/{id}` | Reopen authoritative state; archived excluded unless requested |
| `POST /v1/conversations/{id}/turns` | Existing query fields plus required UUID `idempotency_key`; 201 |
| `GET /v1/conversations/{id}/turns` | `limit=1..100`, `after_id`, `include_archived`; increasing ordinals |
| `GET /v1/conversations/{id}/turns/{turn}` | Turn plus current authorized run state |
| `POST /v1/conversations/{id}/turns/{turn}/cancel` | Cancel queued only; cancelled replay 200; other statuses 409 |
| `POST /v1/conversations/{id}/archive` | Strict boolean `archived`; admin only; active turn 409 |

Accepted turns have immutable positive order, per-conversation key uniqueness
and unique run references. Composite foreign keys enforce tenant-consistent
links. Creation and counter updates share one transaction and PostgreSQL row
lock. A queued/running turn prevents another non-idempotent submission. Same key
and payload returns the same turn/run even if its index was later deprecated;
different payload 409. The requested index/null distinction is fingerprinted.
New turns require active visible indexes and searchable coverage. Invalid or
failed submissions do not consume an ordinal.

A turn response includes its run; run state/events/usage/provenance remain the
existing system of record. GET does not dispatch inference. POST persists a
queued run; clients execute/replay through its existing SSE endpoint. Queued
cancellation appends one terminal event without inference. Running cancellation
remains request-bound; this slice has no durable dispatch/recovery promise.

Archival blocks new submissions and hides default lists; it does not erase
history, source documents or raw artifacts. Explicit archived inspection and
standalone run inspection remain authorized. Retention/purge automation is not
implemented. API restart preserves ledger state, not in-flight SSE execution.

`/v1/system-readiness` advertises `conversation_ledger=true`,
`chained_conversations=false`. Runs explicitly record `memory_mode=independent`.
No previous output enters a new prompt or factual evidence pack. Old standalone
runs are untouched. Do not present this foundation as successful follow-up
interpretation, GPT-style chat, long-history budgets or cache invalidation.
