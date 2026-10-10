# ADR 0019: Conversation state and reference-only execution

- Status: proposed; not implemented
- Date: 2026-10-10
- Tracks: product / durable execution and platform performance
- Issues: [#62 conversations](https://github.com/mohripan/flint-graph/issues/62),
  [#63 payload/history budgets](https://github.com/mohripan/flint-graph/issues/63)

## Existing behavior

Each query run is independent: creation accepts a question, retrieval index,
filters and stream flag, without a conversation or previous-turn identifier.
Question history reopens persisted results; it does not supply follow-up memory.
Query execution remains request-bound SSE/LangGraph. Milestone 18's Temporal
query execution is planned, not already available.

Ingestion and indexing already use reference-only workflow inputs: tenant,
document, immutable document version, job and retrieval index IDs, with a batch
index for indexing activities. Raw/derived content is stored outside workflow
history. Activity outputs contain counts, not complete document/vector bodies.
Backfill still loops over batches in one execution; its history growth has not
been qualified at large-corpus scale.

## Proposed direction

PostgreSQL owns tenant-scoped conversations, ordered turns and query-run links.
Define an explicit concurrent-turn policy, immutable attempt/context snapshots,
authorization, retention and deletion before adding model memory. Existing
standalone runs remain independent rather than being retrospectively grouped
into invented conversations. Frontend provides new/reopen/follow-up actions
only when the corresponding backend contract exists.

Use bounded earlier turns to interpret follow-ups and retain both the user's
question and any retrieval rewrite. Earlier answers are context, never verified
source evidence. Retrieve authorized active documents again, and preserve
per-turn citation and support checks. Only finalized outcomes may enter memory;
failed, provisional, unsupported and cancelled outputs must not silently become
facts. Token reservations include history, tools, source context and output.
Persist/version summaries and make omitted history inspectable. Qualify cache
invalidation against permissions, source/index versions and provider settings.

For durable query dispatch, carry stable run/turn/context-pack/checkpoint IDs and
hashes, not growing messages, embeddings or source bodies. Activities load and
authorize immutable referenced inputs. Workflow code must remain replay-safe,
with no storage/model IO. Minimize sensitive text even in error payloads.
Retain explicit attempt and parent-budget accounting across retries and children.

Measure serialized envelopes, history bytes/events, replay/queue latency, worker
memory and end-to-end model usage before tuning batch/concurrency settings. Use
bounded child executions or Continue-As-New where measured history thresholds
justify them; preserve cancellation, progress and idempotency. Verify limits for
the pinned deployment, not assumed cloud defaults. See Temporal's
[workflow task errors](https://docs.temporal.io/references/workflow-task-errors)
and [Python Continue-As-New guide](https://github.com/temporalio/documentation/blob/main/docs/develop/python/workflows/continue-as-new.mdx).

## Alternatives and acceptance

UI-only concatenation cannot provide durable order, server authorization or a
bounded grounded memory policy. A LangGraph thread key is not an access boundary.
A single never-ending conversation workflow risks unbounded history; passing
IDs alone is not a model-inference speedup. Persistent turns can be implemented
before Temporal migration without claiming disconnect/restart durability.

Acceptance requires tenant/revocation/deletion tests, concurrent turns, explicit
new-chat isolation, multi-turn quality evaluations, long-history token budgets,
real API/worker restart/replay/cancellation checks and measured payload/history
budgets. Record implementation decisions and live evidence before changing this
ADR's status. No conversation migration or performance improvement is delivered
by this proposal.
