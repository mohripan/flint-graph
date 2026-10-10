# ADR 0024: Durable query invocation accounting

Status: accepted for the existing request-bound query runtime. Tracking: #94;
parent reservations and caching remain #82 and #83.

## Decision

Use the existing PostgreSQL provider-usage ledger, with versioned, server-owned
metadata, rather than another telemetry-only ledger or a parallel writer updating
the query-run row. Every query embedding, answer generation and nonempty support
check commits a `started` row before dispatch. Its UUID is the invocation ID; an
execution-attempt UUID groups calls, and zero-based clause indices distinguish
coordinated query embeddings without retaining the query or vector.

The accounting writer owns a separate session. It finishes the same row under a
row lock; terminal updates are idempotent. Retries are new invocations, not edits
of the failed attempt. A dispatch is refused if the initial record cannot commit.
Failure/cancellation finalization is attempted for at most ten seconds, preserving
the original exception. A crashed or unavailable finalizer leaves a durable
`started`/unknown row, never a fabricated success or free call.

The main execution writer reconciles query rollups from all tenant/run ledger
rows after execution, including exception/cancellation handling. Replacement,
rather than increments, prevents replay double-counting. Independent ledger
writers do not update the parent row while parallel readers or streaming
generation are holding the execution transaction.
Generation preparation commits before the independent attempt insert. Streaming
draft events commit once when generation returns, before its final ledger update
and the support-attempt insert; they remain provisional and untrusted. A generation
failure rolls back pending draft events before finalizing unknown usage. This
avoids parent event-row locks conflicting with provider-ledger foreign-key locks.

## Usage and completeness

Numeric columns remain nonnegative known lower bounds for compatibility. A
server-recorded `usage_known` boolean explicitly distinguishes unavailable usage
from known zero. Deterministic computations consume known zero provider tokens;
real providers need valid reported integer counts. Embeddings require input usage
and have no generated output tokens. Missing, malformed or out-of-range usage is
unknown; pricing it returns null even when a configured rate is zero. Unknown
does not mean that dispatch failed without consuming anything.

Planning records the expected embedding count (one to three clauses) and answer/
support operations. Clarification deliberately skips generation/support; an empty
claim set skips the support provider. These have zero expected calls, not invented
usage rows. Completed query accounting requires matching expected/recorded counts
and terminal known usage for every ledger row, including earlier attempts.
Unpriced known usage is distinct from missing usage. Cost rollups can be partial;
`unpriced_event_count` must be checked separately.

Query GET/history expose `provider_usage_complete`: null for legacy/unattested
runs, false for gaps, true for reconciled complete usage. Tenant-authorized
`GET /v1/query-runs/{id}/usage` exposes only whitelisted invocation fields.
The admin usage summary adds `unknown_event_count`; old ledger rows without the
attestation remain unknown rather than being silently reclassified.

No SQL migration is needed: correlation, state and completeness use existing
JSON metadata, and existing numeric columns retain their contracts. This is not
an implementation of a hard cost reservation or durable query execution.

## Evaluation compatibility and limits

Fresh capture format 2 carries accounting completeness and scope; financial
nightly format 3 identifies `query-invocations-v1`. Nightly inspection requires
the new invocation capability before inference. Capture validates completeness,
version, operation keys, matching integer counts and zero unknown events. Old
capture format 1 and nightly formats 1/2 remain unchanged recordings; their
answer/support-only totals must not be presented as full query accounting.

No raw queries, vectors, provider exceptions, credentials or source payloads enter
the new ledger metadata, metrics or redacted nightly reports. The ledger measures
adapter invocations, not arbitrary HTTP requests hidden inside injected SDKs.
Current embedding adapters make one HTTP request per invocation and do not retry
internally. Parent budgets, transport retry reservations, cache hits, upstream
billing reconciliation and abandoned-attempt recovery belong to follow-up work.
The narrow local verification uses deterministic embeddings and an existing
Ollama answer/support model; it does not qualify a real embedding provider.
