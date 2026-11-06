# ADR 0060: The assistant's conversation is a fold over an append-only log

Status: accepted (2026-11-06)

## Context

The Assistant is the Studio's primary workflow ([ADR 0038](0038-conversational-authoring-through-reviewed-proposals.md)),
but its idea of a conversation was thin. `claim_turn` rebuilt history from the last four
*completed* turns' request and reply text. So the model:

- never learned whether a creator **accepted or rejected** what it proposed, and could
  propose the same rejected change again;
- had nothing to refer to after a failure, because failed and stopped turns were left
  out, so "try again" meant nothing;
- forgot everything older than four turns, with no trace it had existed.

There was also no record a person could read of what had happened in a conversation.
Everything to come (generation, references, child sessions) needs somewhere to write
what it did.

Capsulet's durable runtime
([its ADR 0018](https://github.com/mohripan/capsulet/blob/main/docs/adr/0018-durable-graph-runtime.md))
solves the same problem for runs: "the log is the run". State is a fold over an
append-only event log, the fold is the only way to build it, and a test folds the log
and asserts any projection agrees.

## Decision

1. **Every thread has an append-only log**, `narrative_assistant_thread_events`
   (migration 0045). Positions are gapless per thread, taken under the thread row's
   lock from `next_event_sequence`, so two writers cannot take the same position.
2. **The database refuses `UPDATE` and `DELETE`** with a trigger that raises, on
   PostgreSQL through the migration and on SQLite through a DDL listener, so ordinary
   tests exercise the refusal too. A trigger rather than a rule: a rule that silently
   does nothing makes a refused mutation look like a success.
3. **Events are written in the transaction of the change they record.** A log line
   cannot exist for a change that rolled back, and a stale worker that loses its fence
   writes nothing.
4. **The conversation is a fold.** `fold_thread` in `narrative/assistant/log.py` is pure:
   no clock, no database. `conversation_from_log` turns it into what the model is told:
   the last four finished turns verbatim, each followed by what became of its proposal,
   and older turns as one bounded line each. Failed and stopped turns stay in.
5. **Unknown kinds are skipped by the fold**, so an older worker reading a newer log
   during a rolling deploy still sees everything it understands. Out-of-order input
   raises: that is a reader bug, and guessing would hide it.
6. **Existing conversations are backfilled.** The migration writes the events each
   thread would have written, ordered by when they happened, so conversations in
   progress keep their past. The whole migration is plain SQL, so `--sql` still works.
7. **The Studio shows the log** as an **Activity log** panel beside the chat, read through
   `GET /assistant/threads/{id}/events` (viewer access, resumable from a sequence).

Event payloads hold story and chat text, and stay in PostgreSQL like the turn rows do.
Temporal history, outbox payloads, audit metadata and logs still carry identifiers only.

### What stays in the rows

This is not event sourcing of the whole turn. Turn rows remain the operational ledger:
fencing tokens, Temporal run binding, cancellation and admission need a row to lock,
and rewriting them gains nothing. `narrative_assistant_turn_events` also stays as the
bounded *live trace* of one reply (streamed thinking, reply deltas), which is high
volume and not part of the conversation's record.

Capsulet's rule still applies at the boundary: a projection is allowed, a second
source of truth is not. So the two are tied together by test:
`test_folding_the_log_agrees_with_the_rows` folds the log and compares it with the
rows, and `test_migration_backfills_existing_conversations_faithfully` does the same
after a real downgrade and upgrade on PostgreSQL.

## Rejected

- **Reading proposals and turns with more joins instead of a log.** It answers "what is
  the state" but not "what happened and when", and each new feature would add another
  join into the prompt builder.
- **A `CHECK` on `kind`.** Every new event kind would need a migration. Writers go
  through `append_thread_event`, which refuses undeclared kinds.
- **Summarizing old turns with the model.** It costs a model call per turn, can drop or
  invent facts, and is not deterministic. Summaries come from the fold.
- **Row-locking turns to allocate positions.** The thread row is the natural owner, and
  it is always the last lock a writer takes, so appends cannot deadlock.

## Consequences

- The model knows what the creator decided, including on the next turn after a failure.
- A stopped or failed request remains in context, at a small cost in prompt size.
- Each lifecycle write now also updates the thread row, which briefly serializes writers
  of one thread. Thread writes are rare and short, so this does not matter in practice.
- The log only grows. A thread writes a handful of events per turn, and reads are capped
  at the newest 5,000.
