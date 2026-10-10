# Conversation ledger contract

Delivered foundation: #96 / [ADR 0026](../adr/0026-conversation-ledger-foundation.md).
Bounded prior-year interpretation: #97 / [ADR 0027](../adr/0027-bounded-prior-year-followups.md).
Broader follow-up memory remains #62/#75, UI #73, quality #74, budgets #82.

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
