# The assistant generates pictures and voices

Delivered [ADR 0061](../adr/0061-assistant-runs-generation.md): migration
`0046_assistant_actions`, prompt `narrative-assistant/v4` (bundle `5affac18…`), durable actions,
results in the chat and an automatic-generation switch.

## The bug behind "the assistant is behind"

Live qualification of the existing flow found that a request for a character and sprite took
three model calls and about 100 seconds, and then lost the sprite. Probing the model directly
showed two schema defects hiding each other: one flat shape let it write `"voice": "girl"` for
a character type, and exact shapes alone would have made things worse, because the lock's
sorted keys force `generate_backgrounds` to begin `{"description"`. With that ordering its
thinking said `generate_backgrounds` while its output said `set_title`.

Measured on the same local model (Gemma 12B QAT, thinking on), model time only:

| Request | Before | After |
| --- | --- | --- |
| Character with a transparent sprite | 3 calls, 98 s, sprite dropped | 1 call, 13 s |
| Background | not measured | 1 call, 20 s |
| Expressions | not available | 1 call, 14 s |
| CG | not available | 1 call, 34 s |
| Line and its voice | not available | 1 call, 119 s (long thinking) |
| Narration | 3 calls, about 100 s | 1 call, 28 s |
| Question | 1 call, 5 s | 1 call, 5 s |

## Real end-to-end qualification

An isolated stack ran from the worktree with real PostgreSQL, Temporal, MinIO, Ollama, the
12 GB GPU, the image worker (Animagine XL 4.0, cutout, IP-Adapter) and the voice worker
(Kokoro-82M). It used its own database, bucket and task queues on ports 8321/5322. The main
Studio on 8101/5173 kept running and was not restarted. Edge, driven by Playwright, did this
in one conversation through the real UI, with no page errors:

| Asked | Result | Job time |
| --- | --- | --- |
| "Add a character named Mira… transparent stage sprite" | `waiting`; Accept started it; 4 sprites; **Use on stage** saved a revision | about 3 min 45 s |
| "Generate happy and angry expressions for Mira" | Started with no Accept; 2 repaints of her sprite; **Use as happy** saved a revision | about 1 min 15 s |
| "Add a line… where Mira says she can hear the bell, and voice it" | Accept, then 1 clip with a chosen voice; **Use on the line** saved a revision | about 27 s |
| "Generate a background of a rainy harbor street at night" | Started by itself; 4 backgrounds; **Approve** | about 1 min |
| "Generate a CG of Mira ringing the harbor bell at dawn" | Started by itself, drawn from her approved sprite; 4 CGs; **Approve** | about 2 min |
| "What have we made together so far, and what have I approved?" | Answered from the log (see below) | |

The thread log recorded every step in order, as `action.started`, `job.finished` and
`asset.approved` beside the turns.

### Limits found

- The memory answer had one slip: it counted the approved CG as a second background. The log
  reports both correctly; the model's summary was imprecise.
- One reply said "I've added" before acceptance, despite the prompt asking it not to. The
  proposal still needed Accept, so nothing was applied.
- The line-and-voice turn was 137 s and three calls before the voice corrections, because the
  model put `voice` on a speakerless line. That is now corrected without a call, and covered
  by unit tests, but this exact turn was not re-run live after that fix.
- After acceptance, the proposal's change list compares with the current story, so a newly
  added record can read **Changed**. This existed before and was left alone.

## Not delivered

- **Poses through the assistant.** The FLUX.2 klein model and pose worker are optional and not
  set up on this machine, so this could not be qualified. Characters → Poses still works
  where it is configured.
- **Music and ambience.** The product has no music generation at all (#163 is open), so there
  is nothing for the assistant to drive.

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

Results: full Python suite **2,128 passed, 125 skipped** (the skips are the existing opt-in
live-service gates); frontend **166 passed**; Ruff, mypy, prompt lock history, migration SQL,
Compose validation, the offline eval gate and the frontend build passed. The assistant, CG and
voice integration tests also ran on PostgreSQL through `FLINT_GRAPH_NARRATIVE_PG_URL` against
a disposable database: 126 passed, 3 skipped.

## To activate

`git pull`, then restart the Studio with `uv run python tools/narrative/studio.py`, which
applies migration 0046. The API and the assistant worker must restart together. Existing
proposals keep working: their actions read as offered, and jobs already started for them are
still found.
