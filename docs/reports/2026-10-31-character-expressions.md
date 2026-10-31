# Character expressions from a base sprite (ADR 0041, slice A)

The user asked for consistent characters: the same body, hair and outfit with
different expressions, and sometimes different poses. Text-to-image generation draws
a new person for every prompt, so expressions made that way never match. This slice
delivers expressions per the
[design](../superpowers/specs/2026-10-31-character-expressions-and-poses-design.md)
and [ADR 0041](../adr/0041-character-expressions-and-poses-from-a-base-sprite.md).
Poses (slice B) are designed but not built.

## What changed

- **Child (`runtimes/imagegen/generate.py`).** An optional `inpaint` request block
  (base image path, SHA-256, face box, strength, one prompt per seed) switches the
  child to `StableDiffusionXLInpaintPipeline`, loaded from the same pinned Animagine
  XL 4.0 weights. For each seed it:
  1. crops a square of 2.4× the face box from the base composited on white, padded
     with white past the edges, and scales it to 1024;
  2. inpaints a feathered ellipse over the box, grown by 12 % sideways and down and
     6 % up (Euler A, 28 steps, guidance 6.0, strength 0.9);
  3. scales the result back and pastes it under the same mask. It changes only fully
     opaque pixels and restores the base alpha exactly.

  The child checks the base file's size (at most 16 MiB), hash and PNG
  dimensions (64–2560, equal to the request's width and height), and the box
  (inside the image, at least 16 px). It also checks the strength (0.3–1) and the
  prompt count. It refuses `inpaint` combined with `cutout`. No new dependency was
  needed, so the runtime lock is unchanged.
- **Prompts (`flint_graph.narrative.imagegen`).** Twelve preset tag sets: happy,
  laughing, sad, crying, angry, surprised, embarrassed, worried, smug, thinking,
  sleepy and determined. Free-text expressions pass through as tags. Each prompt is
  subject → `solo, close-up, face` → expression tags → the character's appearance tags
  → `white background` → quality tags. The expression tags therefore come early,
  well inside CLIP's 77 tokens (57 tokens in the qualification). The negative prompt
  is the character's own plus `expressionless`.
- **Jobs (migration 0026).** A `character_expression` purpose on image jobs with
  `base_asset_id` (a composite foreign key to the library asset in the same project
  and tenant), `face_box`, `strength`, `expressions` and per-image `prompts`. A check
  makes these columns present exactly for expression jobs. The jobs reuse the
  portrait machinery: outbox, fenced Temporal activity, idempotency keys (the
  base, box and expressions are part of the request identity), workspace limits,
  GPU contention handling, cancellation and recovery.
- **Worker.** The activity fetches the base bytes from the store hash- and
  size-verified and writes them into the child's work directory. The parent requires
  each result to have the base's size and to be RGBA exactly when the base is RGBA.
- **API.** `POST` and `GET /v1/narrative/projects/{project}/characters/{character}/expression-jobs`.
  The base must be a non-discarded PNG library asset of kind `sprite`, `image` or
  `character_portrait` (404 otherwise). The request schema allows one to four
  expressions. The service rejects with 422 `invalid-expression-request`:
  - a base outside 64–2560 px (2560 covers the 2× high-resolution sprites of
    up to 1664×2432 that a parallel branch adds);
  - a box outside the image, smaller than 16 px or with an aspect ratio outside
    0.5–2;
  - a name that is not a short tag, or a repeated name.

  Results become candidate assets of the base's kind, named
  `{character} {expression}`. Their provenance records the expression, its prompt,
  the base asset, face box and strength.
- **Studio.** Characters → On stage gains **Generate expressions…** under the sprite
  list (`ExpressionStudio.tsx`, one render line in `CharacterSprites.tsx`). The panel
  shows the chosen base sprite with a face box. Its first guess comes from the
  sprite's transparency, and it can be dragged, resized from the corner handle,
  moved with the arrow keys and resized with Shift. Below are preset chips and a
  free-text field (up to four expressions), then progress. Results preview zoomed
  onto the face, because on a full-body thumbnail the expressions look alike.
  **Use as "happy"** approves the candidate and sets that expression's sprite in the
  draft; **Discard** hides it.

## Qualification

**Strength.** Strengths were compared on the transparent 808×1212 sprite from the
cutout qualification, with the real child. At 0.7 the face barely changes. At 0.85
the first real worker run (below) kept the base's smile on sad and surprised. At 0.9
happy and angry read clearly and every expression changes its eyes and brows, with
slight hair drift at the mask edge. At 0.95 the hair inside the mask drifts in
colour. The default is 0.9. The mouth is the weakest part: on this smiling base, sad
and often surprised keep a closed-mouth smile. One 0.9 run opened surprised's mouth;
the final live run did not.

**GPU end to end through the worker: passed.** The opt-in live test
`test_real_gpu_expressions_repaint_only_the_face` runs this branch's code. Its path:
API job, outbox relay, owned Temporal workflow and activity, the real child on the
RTX 5070 Ti, then stored and hash-verified content. It generates happy, angry, sad
and surprised.

- The first attempt failed with `gpu_busy`, because Ollama's 12B assistant model
  held about 7.9 GB. `FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL` is the same
  opt-in unload the owned image worker uses. With it, the test passed in 83 s at
  strength 0.85.
- Rerun at the final 0.9, it passed in 273 s. The assistant model reloaded on the
  GPU during the job, so the child shared memory with it and ran slower.

| Expression | Same size | Alpha identical | Pixels changed outside the face crop | Mean face change (0.85 → 0.9) |
| --- | --- | --- | --- | --- |
| happy | yes | yes | 0 | 20.6 → 24.2 |
| angry | yes | yes | 0 | 38.4 → 47.3 |
| sad | yes | yes | 0 | 28.1 → 25.3 |
| surprised | yes | yes | 0 | 27.3 → 35.2 |

**Studio on the real stack: passed.** I ran the worktree API (port 8102, its own
database `flint_expr_qa` on the owned PostgreSQL), an image worker on its own queue
and the worktree frontend. This kept the main checkout's older image worker from
taking the jobs. In headless Edge (1366×1000) I:

1. Uploaded the transparent sprite and set it as Mira's `neutral`.
2. Opened **Generate expressions…**. The face box guess was `[353, 41, 483, 171]`;
   the GPU test's hand-measured box was `[350, 40, 480, 170]`.
3. Moved the box with the arrow keys, chose happy and angry, and pressed
   **Generate 2 expressions**. Progress showed "Loading the model…" and the job
   finished in 63 s.
4. Pressed **Use as "happy"**. The sprite list showed neutral and happy, the result
   showed "In use", the asset was approved, and saving gave revision 3.

Both results at strength 0.9 were RGBA, the same size, with identical alpha, 0
changed pixels outside the face crop and a mean face change of 22.6 and 40.2.

Evidence is in [qualification.json](evidence/character-expressions-2026-10-31/qualification.json).
Images, job records and screenshots are in ignored `notes/expression-qualification/`
(`gpu/` and `gpu-0.9/` for the live test, with `gpu-0.9/faces.png` comparing the
faces, and `ui/` for the Studio run).

## Findings fixed during qualification

- At strength 0.85 real runs changed expressions too little, so it is now 0.9.
- High-resolution sprites from a parallel branch reach 1664×2432, above the
  original 2048 px base cap. The cap is now 2560 in the service and the child.
- On full-body result thumbnails the expressions were indistinguishable. Results
  now preview a square 1.6× the face box (`faceView` in `expressionModel.ts`).
- A bad expression name came back as 422 `invalid-appearance` ("Invalid
  description"), because the shared job path maps every prompt error that way. Names
  are now checked first (`expression_names`) and reported as
  `invalid-expression-request`.

## Known limits

- There is no face detector. The box guess assumes an upright figure with the head at
  the top. Other images need the box moved by hand.
- On a smiling base, sad and often surprised keep a closed-mouth smile; eyes and
  brows do change. Regenerating gives new seeds. A per-image negative prompt
  (`smile` for sad, angry and surprised) would likely help. Today the child takes one
  negative prompt per job, so that needs a small protocol change.
- Free-text expressions are plain tags, so uncommon ones vary in quality.
- Expressions repaint the face only. Hand gestures and body language belong to poses
  (slice B).

## How to run the GPU test again

Free at least 8 GB of dedicated GPU memory (`nvidia-smi`), then run, from the
repository root:

```powershell
$notes = (Resolve-Path notes).Path
$env:FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE = "$notes\narrative-temporal-owned.json"
$env:FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR = (Resolve-Path runtimes\imagegen).Path
$env:FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR = "$notes\models\animagine-xl-4.0"
$env:FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256 = (Get-FileHash "$notes\models\animagine-xl-4.0\flintgraph-download.json" -Algorithm SHA256).Hash.ToLower()
$env:FLINT_GRAPH_NARRATIVE_EXPRESSION_BASE = "<path to a transparent sprite PNG>"
$env:FLINT_GRAPH_NARRATIVE_EXPRESSION_FACE_BOX = "350,40,480,170"
$env:FLINT_GRAPH_NARRATIVE_IMAGE_SAVE_DIR = "$notes\expression-qualification\gpu"
uv run pytest tests/integration/test_narrative_image_workflow_live.py -k expressions -v
```

If Ollama's assistant model holds the GPU, also set
`FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL`.

## Verification

- `uv run pytest`: 1712 passed, 86 skipped (the opt-in live and fixture tests). New
  or extended tests:
  - prompt builder (+3);
  - child protocol against the scripted fake child (+3: size and transparency
    kept, wrong-size, flattened or hash-mismatched results refused, prompt count
    and no cutout);
  - character API integration (+1: validation and its problem types, idempotency,
    409 on a reused key, the inpaint request the worker sends, asset names, kind
    and provenance, RGBA content, discarded base, the 2432 px base accepted and
    2600 px refused). It passed on SQLite and the owned PostgreSQL (22 passed),
    with migration 0026 applied in a throwaway schema.
- Live on the owned Temporal with the real GPU: the expression test passed at 0.85
  (83 s) and at 0.9 (273 s); see Qualification.
- The child's own checks (`uv run --frozen python -I -m unittest discover -s . -p
  "test_*.py"` in `runtimes/imagegen`): 17 run, 1 skipped (the real segmenter
  test). Six are new: the face context and its white padding, mask coverage,
  paste keeping size, alpha and body, valid and invalid inpaint requests in a real
  child process, and the 2560 px cap.
- `uv run ruff check .`, `uv run mypy` (233 files), the deterministic eval gate,
  `alembic upgrade head --sql` (with `FLINT_GRAPH_ENV=test`), `docker compose
  config`, and `uv lock --check` (root and `runtimes/imagegen`) pass.
- Frontend: `npm test` (85, +5 for the expression model: face box guess, opaque
  fallback, clamping, names and keys, face preview), `npm run typecheck`,
  `npm run build`.
- Studio in headless Edge on the real stack; see Qualification.

## Operating notes

- Migration 0026 follows 0025. The high-resolution sprites branch also adds a
  0026 (`0026_narrative_image_hires`, adding `hires_scale`/`hires_strength` to image
  jobs). Whichever merges second renumbers to 0027 and points `down_revision` at
  the other. This one replaces the `ck_narrative_image_job_purpose` check, so a
  migration that also changes that check must start from this rule.
- After merging, restart the image worker so the activity sends the base image. The
  child runs fresh from `runtimes/imagegen` for each job and needs no new sync.
- Merging with `master` touches `CharacterSprites.tsx` (one import and one render
  line beside the new framing controls) and `frontend/src/lib/api.ts` (separate
  areas).
- `AGENTS.md` is not updated here, to avoid conflicting with the main session; it
  needs one line pointing to this report.
- The QA database `flint_expr_qa` on the owned PostgreSQL can be dropped.
