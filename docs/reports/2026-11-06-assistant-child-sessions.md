# Child sessions in the assistant

Delivered [ADR 0063](../adr/0063-assistant-child-sessions.md): migration
`0048_assistant_child_sessions` and prompt `narrative-assistant/v6`.

## What changed

- **Sidebar tree.** A parent has a chevron, and its children sit under a connector line. A parent
  opens when it or a child is open, and stays open while a child is working so the spinner is
  never hidden. A child's header has a link back to its parent, and `?thread=` links open a child
  under its parent even when the parent is outside the loaded page.
- **Started by the creator.** **New child session** in the header; the next message is its task.
- **Started by the assistant.** `start_child_session`, for when asked or for several large parts.
  Sessions queue through the action dispatcher and run on their own, with **Open this session**
  on the proposal.
- **Connected.** A child hears its task and what its parent did. A parent hears what its children
  did, in its Activity log and its next turn.

## A bug the live test caught

The first live run passed every automated check: both assistant-started sessions reached
"finished". The screenshot told a different story: "Chapter 1 Outline" had not done its task. It
had tried to start a child session of its own, been refused, and still counted as replied. The
prompt already said not to, so the operation is now absent from the schema inside a child session,
and the run was repeated checking what each session actually produced:

| Session | Started by | Result |
| --- | --- | --- |
| What should the keeper be afraid of? | Creator | Answered, inventing "the Echoes" |
| Keeper Character Profile | Assistant | Drafted a profile and asked what it needed to continue |
| Chapter 1 Outline | Assistant | A reviewable proposal of 7 scenes |

The parent's own later request used "the Echoes", which only existed in a child's reply, so memory
does travel from child to parent.

## Limits

- "It has replied" means a session's first reply ended. That can be a question or a proposal to
  review, so it is worded as an invitation to open the session.
- There is no delete or archive for sessions.
- Child-session judgment was checked on one live scenario, not measured over many.

## Verification

Tests were written first. Commands ran from the worktree:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-prompts check --base-ref origin/master
$env:FLINT_GRAPH_ENV='test'; uv run alembic upgrade head --sql
docker compose config
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
npm --prefix frontend test
npm --prefix frontend run build
```

Results: full Python suite **2,161 passed, 125 skipped** (the skips are the existing opt-in
live-service gates); frontend **184 passed**; Ruff, mypy, prompt lock history, migration SQL,
Compose validation, the offline eval gate and the frontend build passed. The assistant integration
tests also ran on PostgreSQL through `FLINT_GRAPH_NARRATIVE_PG_URL` against a disposable database:
**156 passed, 3 skipped**.

### Migrations on real data

Because the thread log cannot be edited afterwards, migrations `0044` to `0048` were dry-run on a
throwaway `pg_dump` copy of the main Studio's database, which was only read. The copy was at
`0043` and upgraded cleanly. All 9 conversations, 14 turns and 10 proposals backfilled into 51
events with gapless sequences and correct counters, the fold agreed with the rows on every thread,
and the append-only trigger refused a delete. The copy was then dropped.

### Live qualification

On the isolated stack with the real model, through the real UI in Edge: a parent conversation; a
child started from the header; a parent request to split the work, which started two sessions
that queued and finished by themselves; and a `?thread=` link straight to a child. The parent's log
read `thread.created turn.requested turn.completed child.started child.updated turn.requested
turn.completed proposal.created child.started action.started child.updated child.started
action.started child.updated`. No page errors.

## To activate

`git pull`, then restart the Studio with `uv run python tools/narrative/studio.py`, which applies
migration 0048. The API and the assistant worker must restart together.
