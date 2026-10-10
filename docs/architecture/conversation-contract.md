# Conversation ledger contract

Delivered foundation: #96 / [ADR 0026](../adr/0026-conversation-ledger-foundation.md).
Bounded prior-year interpretation: #97 / [ADR 0027](../adr/0027-bounded-prior-year-followups.md).
Broader follow-up memory remains #62/#75, UI #73, quality #74, budgets #82.

Conversations are workspace-shared PostgreSQL records. Membership, not a thread
ID or tenant header alone, authorizes them. Viewer reads; member creates/submits/
cancels queued turns; admin archives/reopens. Foreign resource/cursor 404 follows
workspace authorization; invalid/revoked membership receives the existing 403.
Titles are bounded display text. Conversation creation does not make an index.
Titles are trimmed to 1..200 characters and reject NUL. Discovery/rename is
advertised separately as `conversation_discovery=true`. Search matches a literal
case-insensitive title substring using database case matching, bounded to 200
characters; SQL wildcard/escape characters are treated literally. Empty/whitespace
search lists all authorized visible conversations. It does not search turn text,
answers, documents or other workspaces, and has no large-history latency claim.
The cursor is authorized independently of the search filter. Renaming does not
change created-at ordering, turn/run identity, idempotency, inference or memory.
Members may rename workspace-shared conversations; viewers cannot. Archived or
foreign conversations return 404. Existing row locking serializes metadata
renames; the last committed rename wins, with no optimistic revision API.

| Endpoint | Contract |
| --- | --- |
| `POST /v1/conversations` | Optional title, default `New conversation`; 201 |
| `GET /v1/conversations` | `limit=1..100`, `before_id`, `include_archived`, title search `q`; newest-created first |
| `PATCH /v1/conversations/{id}` | Required title-only body; member rename, 200 |
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
existing system of record. Ordinary inspection GETs do not dispatch inference.
POST persists a queued run; clients execute/replay through the existing
`GET /v1/query-runs/{id}/events/stream` endpoint. This SSE GET is execution-capable:
a queued run linked by an authoritative tenant-scoped conversation turn requires
current member, admin or owner membership before execution. Viewer access is
read-only for conversation runs: non-queued streams replay persisted events,
without restarting work. Run metadata is not an authorization source; absent or
forged conversation metadata cannot remove the ledger-based check. Existing
standalone-query creation/execution policy remains viewer-accessible.
Foreign run access returns 404 after workspace authorization; missing credentials
return 401, disabled membership or insufficient role 403. Membership is checked
at request entry, not continuously throughout an existing stream. Simultaneous
queued execution claims and atomic mid-request revocation are not guaranteed by
this request-bound path. Queued
cancellation appends one terminal event without inference. Running cancellation
remains request-bound; this slice has no durable dispatch/recovery promise.

Archival blocks new submissions and hides default lists; it does not erase
history, source documents or raw artifacts. Explicit archived inspection and
standalone run inspection remain authorized. Retention/purge automation is not
implemented. API restart preserves ledger state, not in-flight SSE execution.

`/v1/system-readiness` advertises `conversation_ledger=true`,
`prior_year_followups=true`, `chained_conversations=false`. New turns initially
record `memory_mode=independent`; execution records `independent`, `resolved` or
`clarification` plus the server-owned `metadata.conversation_context` policy,
fingerprint, resolved query, prior turn/run identity and considered/omitted counts.
The original `query_text` is never rewritten.

## Bounded follow-up execution

Recognize only a narrow English form such as `What about the prior year?` or
`How about the previous year?`. Resolve exactly one explicit 1901..2099 year
in the immediately preceding trusted question to one year earlier. Successive
follow-ups use that turn's resolved question, not its original elliptical text.
Self-contained new-topic questions execute independently. Unsupported elliptical
or pronoun forms, missing/legacy context and ambiguous/multi-year history clarify.
This intentionally conservative heuristic is not general natural-language memory.

Trust requires a completed, non-abstained prior turn with 1..8 supported claims,
no unsupported claims, and 1..8 distinct citations matching persisted claims and
the latest pack. Exact source IDs, PostgreSQL chunk text/hash, active document
version, undeleted tenant document and completed active-index coverage must still
match. Provider/model/prompt/context/output/temperature/faithfulness settings,
retrieval bounds and per-turn document filters must agree. Missing policy
attestation, failed/cancelled/provisional turns and changed settings fail closed.
Never skip the immediate prior turn to find older favorable context.

Revalidate before retrieval and again before answer generation. The bounded
question supplies scope only; prior answer text is never an evidence record or
model transcript. Classification/linking, fresh retrieval, reranking, arithmetic,
generation and support verification all use the resolved query. Citations are
per-turn fresh source records. Normal document lifecycle rules still apply;
there is no atomic guarantee against concurrent deletion after the final check.

Untrusted follow-ups finalize as an abstained, citation-free clarification with
`ambiguous_conversation_scope`. No search, embedding, answer or support call is
dispatched when clarification is known before retrieval. A source invalidated
during retrieval may already have incurred embedding usage, but generation and
support are skipped. Exact zero expected calls may attest complete accounting;
attempted unknown provider usage still cannot be treated as free or complete.

Old standalone runs remain independent. Full GPT-style chat, broad memory,
retention/summary/cache qualification, parent-wide reservations and durable query
execution remain separate work. See [verification](../reports/2026-10-10-prior-year-followups.md).

## First thread UI (#99)

[ADR 0028](../adr/0028-capability-gated-conversation-thread-ui.md) defines the
capability-gated Ask screen. Conversation ledger support enables real ordered
threads; absent/unavailable capabilities retain independent questions. Standalone
history is a separate view, never manufactured into a conversation. The UI names
workspace-shared ownership and only delivered prior-year interpretation.

History uses authorized title search and created-at cursors; turns use increasing
ordinal cursors. Follow-up submission waits until the latest turn is loaded.
New chat clears selection without deleting server history. Browser storage holds
selected IDs per workspace, not messages or evidence. Reopen/reload/refresh are
GET-only; accepted/lost-response retry keeps the same per-attempt key. Original
and resolved questions remain distinct. Member-facing queued Resume rechecks the
existing run and never creates another turn; queued Cancel uses its dedicated
endpoint. Stop only aborts the current stream; terminal status requires refresh.

The primary transcript scrolls while the composer stays visible. Readers near
the bottom follow new turn content; readers inspecting older content can jump
to latest. Page loading and lazy evidence expansion do not trigger auto-follow.
Each turn loads its own authorized provenance, scopes citation DOM IDs by run,
and can expand full excerpts in the same scroller. Text is not rendered as HTML.
Diagnostics are collapsed; clarification, abstention, partial support, queued,
running, failed and cancelled states are differentiated. Draft SSE text is not
presented as a verified answer.

Selection/workspace changes abort and invalidate old requests; 401/403 removes
conversation data and actions. The UI presents viewers as read-only for these
conversation actions. The backend enforces member-only queued conversation
execution independently of UI controls (#100). Full #73
accessibility/retention and general memory/quality acceptance remain separate.
See [UI verification](../reports/2026-10-11-conversation-thread-ui.md).
See [stream authorization verification](../reports/2026-10-11-conversation-stream-authorization.md).
