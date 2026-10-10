# ADR 0026: Conversation ledger foundation

Status: accepted for the ledger slice only. Tracking: #96, parent #62.
ADR 0019's grounded memory and durable execution proposal remains undelivered.

## Design and scope

PostgreSQL conversations and ordered turns reference existing query runs. A turn
does not copy model events, source bodies or vectors. Each accepted turn retains
the original question in its run. Existing standalone runs are never assigned
invented conversation identities. The workspace remains the sharing boundary,
consistent with existing query history; these are not private per-user chats.

Viewer membership permits reads; member or higher creates conversations/turns;
admin or owner archives/reopens them. All resource and cursor lookups include
tenant scope and conversation identity. Missing/foreign resources return 404;
workspace membership/role denial uses the existing 403 boundary. Revocation is
checked on every request. A title is user-provided display text, not instructions.

Turn submission requires a UUID idempotency key. Its fingerprint covers the
original query, requested index (including null), validated filters and stream
flag. Same key/payload returns the original turn/run; changed payload conflicts.
Replay does not require the old retrieval index to remain active. New submissions
must pass current active-index/search-readiness checks. Idempotent replay is
checked before the active-turn rule, but archived conversations reject submission.

Lock the conversation row for the entire submission transaction. Reject a new
turn while its latest run is queued/running; otherwise allocate the next positive
ordinal, create the run and link the turn atomically. PostgreSQL serializes
concurrent requests; uniqueness constraints enforce ordinals, keys and one turn
per run. Composite foreign keys prevent cross-tenant links. SQLite fixtures check
sequential semantics; PostgreSQL tests qualify concurrent serialization.

Conversation lists use stable `(created_at, id)` descending cursors; turn replay
uses increasing ordinals and an authorized turn-ID cursor. Page limits are
1..100. Reads expose authoritative current run state, not a second stale turn
status. Neither list response embeds arbitrary full conversation history.

A member can cancel a queued turn under conversation/run locks so an abandoned
submission does not permanently block the thread. Repeated cancellation is
idempotent. Running/completed/failed turns are refused by this narrow endpoint;
running cancellation still uses request-bound SSE behavior. Cancellation appends
the existing terminal event and never creates a model invocation.

Archival is reversible organization, not deletion or privacy erasure. It blocks
new submissions and is refused while a turn is active. Default lists omit archived
conversations; explicit archived inspection remains membership-authorized. No
physical deletion endpoint or retention automation is introduced. Existing run
inspection remains available under its authorization contract.

## Capability and rollout

Advertise `conversation_ledger=true`, `chained_conversations=false`. Execution
continues through the existing run SSE endpoint, with independently grounded
queries. This slice does not concatenate earlier answers, rewrite follow-ups,
reserve parent budgets, implement summaries/caches, add UI threads, or make SSE
durable. Parent #62 stays open until those independent acceptance gates are met.

## Verification plan

Test one vertical HTTP/service slice at a time: create/read and foreign access;
ordered run-linked turns and readiness; idempotent/conflicting replay; stable
conversation/turn pagination; active-turn rejection and transactional PostgreSQL
concurrent requests; archive/reopen and OIDC role/revocation boundaries. Add
migration 0016, verify generated SQL and apply it to the existing local PostgreSQL
without removing data. Use a newly created disposable fixture workspace for live
API create/turn/replay/reopen checks, then restart only the API to verify storage
survives. Never query or alter the user's private document corpus.

Run full backend tests, PG-enabled focused tests, lint/type checks, offline eval,
lock, SQL, Compose and diff checks. Frontend gates are skipped in this backend-only
slice; live frontend HTTP availability is checked and left running. No new model
call is required to qualify this storage slice. Real follow-up/model and browser
thread verification belongs to the subsequent #62/#73/#74 changes.
