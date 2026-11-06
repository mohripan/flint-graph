# The Library, and a much faster assistant

Delivered [ADR 0062](../adr/0062-attach-library-items-to-assistant-messages.md): migration
`0047_assistant_attachments`, prompt `narrative-assistant/v5`, and the composer's **Library**.
Measuring it also led to turning assistant thinking off by default.

## The Library

**Library** in the composer opens the project's characters, approved pictures and voice clips,
with search. Picking one attaches it to the next message as a chip, and approved results in the
chat have **Attach to message**. The model gets each attached item's details under the IDs it
must use, and attached files can never fall outside the 120-file list it otherwise sees.

## Scene quality and speed

Live testing of "she stands here" with Mira and a background attached found three more cases of
the model doing the wrong thing, all fixed at the root:

- **Lines without a speaker.** Optional fields are written last, and the model stopped before
  reaching `speaker`. Prompt v5 has two exact line shapes: a spoken line requires its speaker and
  writes it first, and narration has no speaker or voice at all.
- **An asset ID where an expression belongs** (`sprite: mira_sprite_1`). This is now corrected
  without a call. The repair message also pointed at the wrong thing, so the model repeated
  itself; it now lists each character's expressions.
- **Files not made yet** (an invented `cg` ID, or showing an expression still being generated).
  The field is left out, or the usual face is used, until the creator has approved the result.

Also, a line rewritten with the same words now keeps its voice clip, and a voice's name in the clip
field is dropped.

### Thinking is now off by default

Measured on real turns with the exact grammar. A case is "right" only if the proposal does what
was asked; for scenes that includes the requested line, by the right speaker, on the right
background.

| | Right | Median turn | Worst turn |
| --- | --- | --- | --- |
| Thinking off, final code | 30 of 30 | 4 s | 11 s |
| Thinking on, scene requests only, before the last fixes | 3 of 4 | 180 s | 429 s, plus one timeout |
| Thinking off, the same scene requests, before the last fixes | 8 of 12 | 9 s | 17 s |

The thinking-on column could not get faster by being fixed: long thinking pushed calls against
the 180-second deadline, and one turn in the live UI ran past five minutes on repeated repairs.

**What this does not show.** It measures doing the right thing, not how good the prose is, on a
small set of requests against one model. The final 30 of 30 is a good run: intermediate runs of
the harder scene request scored 4 of 6 and 6 of 8, some of which were reasonable clarifying
questions that the scoring counted as misses, and one more correction went in after those.
`FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING=true` turns thinking back on for long creative work.

## Who can see what

The user asked whether people with different invitation keys can see each other's projects.
`tests/integration/test_narrative_assistant_isolation.py` now proves the answer for the
assistant under real OIDC: a second signed-in person gets 403 on every read and write when naming
someone else's workspace, 404 when going through their own, and lists only their own workspaces.

Keys do not provide this separation; sign-in does. Under `FLINT_GRAPH_AUTH_MODE=dev` there is one
user, who becomes an owner of any workspace they name. Staging and production refuse dev auth
unless `allow_unsafe_dev_auth` is set.

Workspace names are unique across the server, so a second person cannot use a name someone else
already has. It reveals only the name. This is unchanged and worth revisiting before wider use.

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

Results: full Python suite **2,147 passed, 125 skipped** (the skips are the existing opt-in
live-service gates); frontend **173 passed**; Ruff, mypy, prompt lock history, migration SQL,
Compose validation, the offline eval gate and the frontend build passed. The assistant integration
tests also ran on PostgreSQL through `FLINT_GRAPH_NARRATIVE_PG_URL` against a disposable database:
**130 passed, 3 skipped**, including the cross-user isolation tests under real OIDC settings.

### Live qualification

On the isolated stack with the real model, through the real UI in Edge: opened **Library**, picked
Mira and searched for and picked "rainy harbor street at night 1", and sent "Write a very short
scene where she stands here and says one line about the weather." In 8 seconds, on one attempt, the
proposal added a stage step with that background and `sprite: neutral`, then her line about the
weather, linked between the existing bell line and the ending, and kept the bell line's voice
clip. No page errors.

## To activate

`git pull`, then restart the Studio with `uv run python tools/narrative/studio.py`, which applies
migration 0047. The API and the assistant worker must restart together.
