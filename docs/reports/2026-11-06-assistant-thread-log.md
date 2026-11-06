# Assistant thread log

Delivered [ADR 0060](../adr/0060-assistant-thread-event-log.md): a conversation is now
a fold over an append-only event log, modelled on Capsulet's durable runtime.

## What changed

- **Model memory.** `claim_turn` folds the thread log instead of reading the last four
  completed turns. The model is told what became of each proposal (accepted, rejected,
  undecided, unusable), failed and stopped turns stay in context so "try again" works,
  and older turns survive as one bounded line each instead of vanishing.
- **Log.** Migration `0045_assistant_thread_log` adds
  `narrative_assistant_thread_events` and `next_event_sequence`, backfills existing
  threads, and installs a trigger that refuses `UPDATE` and `DELETE`. SQLite test
  databases get the same refusal through a DDL listener.
- **Writers.** `create_thread`, `post_turn`, `_finish` (every terminal transition),
  `complete_turn`, `accept_proposal` and `reject_proposal` append in their own
  transactions. Idempotent replays return before appending, and a stale execution
  writes nothing.
- **Studio.** **Activity log** beside the chat, a drawer on phones. It polls while open
  and merges by sequence, so repeating a request is harmless. It is named to avoid the
  existing **History** nav item, which means story revisions.

## Verification

Tests were written before the implementation. Commands ran from the worktree
`.claude/worktrees/assistant-parity`.

```powershell
uv run pytest
uv run ruff check .
uv run mypy
$env:FLINT_GRAPH_ENV='test'; uv run alembic upgrade head --sql
docker compose config
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
npm --prefix frontend test
npm --prefix frontend run build
```

PostgreSQL ran through `FLINT_GRAPH_NARRATIVE_PG_URL` against a disposable database on
the existing fixture server, covering the migration, trigger and backfill:

```powershell
uv run pytest tests/integration/test_narrative_assistant_log.py tests/integration/test_narrative_assistant_api.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_assistant_images.py -q
```

Results: full Python suite **2,085 passed, 125 skipped** (the skips are the existing
opt-in live-service gates); frontend **157 passed**; Ruff, mypy, migration SQL, Compose
validation, the offline eval gate and the frontend build passed. The PostgreSQL run
covered both database backends for the assistant integration tests, including
`test_migration_backfills_existing_conversations_faithfully`, which does a real downgrade
and upgrade. One existing test asserted the old history text exactly and was updated to
the new behavior.

### Live qualification

An isolated stack ran from the worktree: its own database, bucket and task queues, with
real PostgreSQL, Temporal, MinIO and Ollama (the local Gemma 12B model), on ports
8321/5322. The main Studio on 8101/5173 was not touched or restarted. Edge, driven by
Playwright, did the following through the real UI:

1. Sent a request. The turn ran through Temporal and produced a reviewable proposal.
2. Clicked **Accept**, which saved revision 2.
3. Asked "What did I just decide about your last proposal?" The model answered "You
   decided to add a narration line about the rain…", which it could not have known before
   this change.
4. The log read `thread.created, turn.requested, turn.completed, proposal.created,
   proposal.accepted, turn.requested, turn.completed`, the panel showed all seven, and
   the page reported no console or page errors.

## Noticed along the way

The same run showed a one-line edit taking three model calls (about 100 s). The model
wrote `speaker: narrator`, and the repair message said only `unknown_reference at
…speaker`, which gave it nothing to fix. Six of the main Studio's 14 real turns also
needed repairs. This is addressed in the next delivery.

## To activate

`git pull`, then restart the Studio with `uv run python tools/narrative/studio.py`. It
applies migration 0045 itself. The API and the assistant worker must restart together.
