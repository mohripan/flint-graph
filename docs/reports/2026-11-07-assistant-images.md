# Keeping characters on stage, and screenshots for the assistant

Prompt v14. See [ADR 0076](../adr/0076-screenshots-for-the-assistant.md) for pictures.

## A character disappeared from a scene

Asked to bring Kaito "more closer", the assistant rewrote his stage step and left out the part that puts him on stage, so
the story no longer showed him anywhere. The Stage panel was right. The Look page still showed him only because its
preview always uses the first character with sprites. The same proposal set his size to 300%, the largest allowed, and
added a stray copy of the step.

| Problem | Fix |
| --- | --- |
| A rewrite of a stage step could drop who was on it | `_keeps_who_is_on_stage` keeps them, unless the request is to take them off or the step hides them |
| Exact copies of a step that nothing reaches | `_without_stage_copies` drops them. A step that is merely unlinked stays and is warned about |
| "Closer" rewrote scenes and picked an extreme size | Prompt v14: framing changes only `stage`, with full body about 100, waist up about 200, face and shoulders about 300 |
| Nothing on screen said he was gone | The Stage panel says when someone speaks but isn't on stage, with **Put on stage**. Off-screen voices stay allowed, so it is only a hint |

With the real model, on an in-memory copy of the owner's story with Kaito put back, the owner's own requests:

| Request | Result, 2 runs each |
| --- | --- |
| "Can you make Kaito closer to the player?" | Kept on stage, `scale` 200, only `upsert_character` |
| "More closer. Like we can only see up until the waist…" | Kept on stage, `scale` 200, only `upsert_character` |
| "Make him a bit smaller, I want to see his whole body." | Kept on stage, `scale` 100, only `upsert_character` |

That is 6 of 6, which is a small sample. The owner's project was not changed and still has Kaito off stage.

## Pictures

In a real browser with the real assistant worker, Ollama, PostgreSQL and MinIO: pasting the owner's real screenshot
showed a thumbnail chip, and sending it took 9 seconds. The activity read "Looked at your picture", the message showed
the screenshot, and the reply named the background from the picture. Browser console problems: none.

Before the writing model saw anything, the vision model was tried directly on two real screenshots. It correctly said no
characters were visible in the one with none, and described the framing and read the dialogue in the other.

## Verification

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run flint-graph-prompts check --base-ref origin/master
docker compose config -q
cd frontend; npm test
cd frontend; npm run build
```

`alembic upgrade head --sql` passes with `FLINT_GRAPH_ENV=test`. The picture and trash tests also pass on real
PostgreSQL with the real migrations. Results are in the commit message.

Not run: drop and the file picker in a real browser, which share the paste path; phones; screenshots of other screens.

Full suite before a final clean-up: 2518 passed, 148 skipped. That clean-up restored formatting-only edits made by
mistake to 38 unrelated files, whose code was checked to be identical, and restored an existing test file that had been
overwritten by the new tests, which moved to `test_narrative_assistant_screenshots.py`. The restored and moved tests and
the unit suite were re-run afterwards. Frontend: 224 passed.
