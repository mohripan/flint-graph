# Portrait prompts follow the creator's description (#170)

The user described a character "Quen Aldwinia": type Boy, framing Full body,
appearance "shoulder-length white hair, red eyes, his face looks like a girl". All
four portraits came out as girls with very long hair in dress-like robes.

## Cause

The server joined the raw description into the prompt:

```text
1boy, solo, shoulder-length white hair, red eyes, his face looks like a girl, full body, ...
```

Animagine XL 4.0 is trained on Danbooru tags. "girl" in plain words competed with
`1boy` and won. "shoulder-length" is not a tag (the tag is `medium hair`). White-haired
anime girls with long hair are a strong prior. The negative prompt was the same for
every character type, so nothing pushed back.

## Change

`flint_graph.narrative.imagegen` now builds the tags itself:

- **Phrase map.** The description is split on commas, semicolons, line breaks and
  sentence ends. Common wording becomes Danbooru tags:
  - Hair length phrases: `shoulder-length` → `medium hair` and `chin-length` →
    `short hair`. "Waist-length" and "floor-length" map to the longer tags.
  - Adjective forms: `long silver hair` → `silver hair, long hair`, `white-haired` →
    `white hair` and `red-eyed` → `red eyes`.
  - Androgyny: for a boy or man, "face looks like a girl", "a girl's face",
    "girlish face" and "feminine features" become `androgynous`. The reverse applies
    for a girl or woman.
  - Repeats of the type tags or `solo` are dropped. Text the map does not recognize
    passes through as written. Type Other is never rewritten for gender.
- **Type tags.** Boy and man add `male focus`. Their negatives add
  `1girl, female focus, breasts`. Girl and woman negatives add `1boy, male focus`.
  Other stays neutral.
- **Hair length.** A stated short or medium length, with no long one, also negates
  `long hair, very long hair`.
- **Hint.** The character sheet now suggests short comma-separated tags, with the
  example "medium hair, white hair, red eyes, androgynous, black coat".

For the reported case the job now records:

```text
prompt:   1boy, male focus, solo, white hair, medium hair, red eyes, androgynous,
          full body, standing, looking at viewer, simple background, safe,
          masterpiece, high score, great score, absurdres
negative: nsfw, explicit, lowres, ... username, blurry, 1girl, female focus,
          breasts, long hair, very long hair
```

### Why a fixed map rather than an Ollama rewrite

- **Same output every time.** The map gives the same tags for the same text, and the
  job keeps the exact prompt the model saw (ADR 0039).
- **Testable.** Unit tests can cover every rule.
- **No GPU contention.** Ollama's 12B model holds about 8 GB, and the image child
  needs 8 GiB free. A rewrite right before each job would force the model to load
  and unload every time.
- **No unknown tags.** A language model can add tags the creator never wrote.
- **Creator text stays on this computer.** Nothing is sent to another service.

The map covers only common phrasings. Anything else stays as the creator wrote it,
and the sheet now steers creators toward tags.

## Token budget

CLIP reads 77 tokens. Animagine's two tokenizers give these counts for the new strings:

| String | Tokens |
| --- | --- |
| Reported case, prompt | 47 |
| Reported case, negative | 68 |
| Longest negative (boy or man, short hair) | 68 |
| Girl or woman negative, short hair | 66 |

## Evidence

- **Before.** These are the user's own four images from job `c06d9cbd`, read from
  MinIO and checked against their recorded SHA-256. They are saved under ignored
  `notes/portrait-prompt-fidelity/before/` (named by seed), with a contact sheet
  `before-sheet.png`. All four show a girl with very long white hair in long robes.
- **After.** The same job was rerun through the real child on the RTX 5070 Ti.
  It used the original seeds `313188645, 1275247027, 2309587623, 2089298423`, the
  same model and the same settings (832×1216, 28 steps, guidance 5). Only the prompt
  and negative differed. The request, the child's events and the images are under
  `notes/portrait-prompt-fidelity/` (`after-request.json`, `after-events.jsonl`,
  `after/`, `after-sheet.png`).

| Seed | Before | After |
| --- | --- | --- |
| 313188645 | Girl, waist-length hair, long robe | Boy, chin-to-neck bob, black coat and trousers |
| 1275247027 | Girl, waist-length hair, long open coat | Boy, neck-to-shoulder hair, open coat and trousers |
| 2309587623 | Girl, very long hair, short robe and tights | Boy, shoulder-length hair, layered coat and trousers |
| 2089298423 | Girl, very long hair, long white dress-robe | Boy, shoulder-length hair, white robe over a long red hakama |

All four keep the white hair and red eyes. The faces are soft and girlish, as the
creator asked, but the bodies are flat-chested and male. None has long hair.

Two remaining gaps:

- Seed 313188645's bob sits nearer chin length than shoulder length.
- Seed 2089298423's long hakama is the closest to the old dress-like look. Clothing
  was not described, so the model chose it.

The child reported 47 prompt tokens, not truncated. Load took 10.8 s, the first image
27.7 s and later images about 10.8 s. Peak device memory was 7.7 GB.

The first try was refused with `gpu_busy`: a vLLM container from the user's other
project held about 10 GB of the GPU. The batch ran after the user stopped it.

To reproduce, use Git Bash from the main checkout with an empty
`notes/portrait-prompt-fidelity/after/`:

```bash
cd /c/Projects/flint-graph/runtimes/imagegen && ./.venv/Scripts/python.exe -I generate.py < ../../notes/portrait-prompt-fidelity/after-request.json
```

## Verification

- Unit: `tests/unit/test_narrative_imagegen_prompt.py`, 48 passed. It covers the
  reported case exactly, negatives per type, the phrase map, androgyny only for the
  opposite type, the hair-length negative and the longest negative.
- `ruff check .`, `ruff format --check` on the changed files and `mypy` (233 files)
  passed.
- Full `pytest`: 1665 passed, 77 skipped.
- Frontend: `npm run typecheck`, `npm test` (71 passed) and `npm run build` passed.
- Live: one batch of four through the real child, with the same seeds as the failing
  job (above).
- Skipped: the eval gate, `alembic upgrade head --sql` and `docker compose config`,
  because no retrieval, migration or compose files changed.
- Not exercised: a job through the owned API and worker. They run the main checkout's
  code, so they still build the old prompt until this branch is merged and they
  restart.

## Follow-ups

- The tags after the description (framing, `safe` and quality) are the first to fall
  outside CLIP's 77-token window on a long description. The job records `truncated`
  and the sheet says so. Placing
  `safe` right after the subject, as Animagine's model card orders it, would keep the
  rating tag in the window for long descriptions.
- Clothing wording such as "dressed like a girl" stays as written, so it can still
  pull toward a girl.
