# A first creator's run

I played a first-time creator on an isolated stack: an empty project, and a game made only by chatting. Real
assistant model, real browser, real Temporal, PostgreSQL and MinIO, a real image model and a real key in invite mode.

**The run is not finished.** It reached the sprites. The machine then ran low on memory and the QA stack was stopped,
and I was told not to restart it. See [What has not been run](#what-has-not-been-run).

## What happened

| Step | Result |
| --- | --- |
| "I want to make a short visual novel…" naming Hana and a choice | 45 s, usable proposal, accepted as revision 2 with 9 scenes and a choice |
| Describe Hana and Tobias, ask for stage sprites | 10 s, two cards at 20 credits each, nothing started before the press |
| Press Generate on both | 8 transparent candidates, 40 credits |

The balance went from 800 to 756: two chat turns at 2 credits and two cards at 20, exactly what the screen said.
Browser console problems: none.

In the thumbnails all four Hana candidates kept the black hair and red scarf. Tobias's navy coat came out navy in
about one of four, and the others leaned white or grey. Choosing between candidates exists for this, but a creator
may need a second Generate. That is my look at thumbnails, not a measurement.

## What it found

Before this work a first request often produced nothing usable. Each failure below is real output from the run or
its bench, except the last, which came from reading the code.

| What went wrong | Fix | Where |
| --- | --- | --- |
| Asked to write a story, it asked what people wear | Sent back to write the story, unless the request is about looks | `turn.py`, prompt |
| It said "I'll create…" and proposed nothing | Sent back with a plain reason | `turn.py`, prompt |
| Scenes made of stage steps with no words, playing invented files | Made-up IDs are dropped when no file of that kind exists; the prompt says a scene is its lines | `turn.py`, prompt |
| An enum whose first value was not in its list made the whole proposal unusable | The value joins the list | `turn.py` |
| A story written beside the blank starter was never reached | The game now begins at the story | `turn.py` |
| The starter's unused ending stayed behind and raised "Some scenes would be unreachable" | Starter scenes the story does not reach are removed | `turn.py` |
| Asking for pictures also rewrote each character unchanged, which showed CHANGED and Accept and saved an identical revision | Edits that change nothing are dropped, so a pictures request shows only its cards | `turn.py` |
| A first story using `{name}` asked the name, then played the blank starter | The story is joined to the start before the question is placed | `turn.py` |

The starter clean-up applies only while the project still holds the starter's exact words, so a creator's own short
story is never rearranged, and only once the new story stands on its own. A first version also removed the ending from
a story with a broken link, which added a false "no ending" error to the real one; an existing test caught it. Most of these are code rather than wording because a small local model keeps following
its examples over a prose exception, as earlier reports found. Prompt v13 still narrows when to ask about looks, adds
a story-writing example and rewrites the scene rule.

## Measurements

From real model runs, made **before** the last three rows above were added:

- `bench_story` (3 runs of 3 story requests): 9 of 9 usable proposals, each with a choice and 2 endings. 5 of 9 met my
  stricter bar of at least 4 spoken lines. The others are short but complete stories, and the mystery request tends
  to come out short.
- General assistant bench: 10 of 10.

## What has not been run

- **The last three fixes have unit tests only.** The stray ending, the unchanged edits and the name order have not
  been seen against the live model. The first two came from this run's real output.
- **The rest of the creator's run:** approving a sprite, a background, showing characters on stage, voices, music, a
  title screen, a playtest and a release, all in one chat-made project. Each works in its own report; they have not
  been run end to end in one project.
- **Stray scenes in a project made before this change** are left as they are.

The memory stop was the system's call while the session was idle. It says nothing about which process was
responsible, and I did not investigate one. A stack with every worker and its models loaded is heavy on a machine
that also runs the main Studio, so run it when the machine is otherwise free.

## Verification

No migration, runtime or format change. Passed on the final code:

```powershell
uv run pytest tests/unit          # 1759 passed, 5 skipped
uv run pytest tests/integration   # 697 passed, 144 skipped
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run flint-graph-prompts check --base-ref origin/master
docker compose config -q
```

`alembic upgrade head --sql` passes with `FLINT_GRAPH_ENV=test`. Outside test mode it stops earlier, because settings
require an Anthropic key.

Not run: the PostgreSQL variants of these tests, because `turn.py` works on stories in memory; the real-engine suites,
because nothing in the player changed; and the live model after the last fixes, for the reason above.
