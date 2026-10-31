# Transparent character sprites: the cutout step (ADR 0039/0040 follow-up)

On the visual-novel stage (ADR 0040), a generated character carried its scenery in a
box around it, because Animagine XL 4.0 only renders opaque images. The user noticed
this on 2026-10-31. Their chosen order is: stage and textbox first, then character
sprite generation. This report covers only the first step of sprite generation:
cutting the figure out. Expression sheets, poses and the per-expression Sprites
section come later.

## What changed

- **Request.** A portrait job takes `"transparent": true`, allowed only with
  full-body framing (422 otherwise). The flag is part of the request identity, so
  replaying a key with a different value is a 409. Opaque requests keep their
  earlier hash. The prompt adds `white background` after the framing tags. The
  negative prompt adds `feet out of frame, gradient background`. The qualification
  below used `feet out of frame, scenery, detailed background, gradient background`.
  Merging with the portrait prompt fixes (gender negatives, long-hair push-back) would
  have made the longest sprite negative 81 of CLIP's 77 tokens, so the tail would be
  cut. The merge keeps the two tags the positive `simple background, white background`
  does not already cover, at 76 tokens measured with Animagine's tokenizers.
- **Child.** With a `cutout` request field (the ONNX path plus the pinned SHA-256),
  `runtimes/imagegen/generate.py` reads the segmenter bytes, hashes them, and loads
  those exact bytes into onnxruntime 1.31.1 on the CPU. So nothing can be swapped in
  between the check and the load. The segmenter loads before SDXL, so a bad pin
  fails in seconds. Each render then goes through these steps:
  1. Letterbox the render to 1024×1024 on black. Run `skytnt/anime-seg`
     `isnetis.onnx` (input `img`, output `mask`, sigmoid) and scale the mask back
     to 832×1216.
  2. Turn the mask into alpha: values ≤ 0.1 become fully clear and values ≥ 0.9
     fully opaque, with a linear ramp between, which keeps hair soft.
  3. Remove the halo. Edge pixels are blends `C = mF + (1 − m)B`. The child solves
     for `F` using the median colour of the clear pixels as `B`. It then spreads
     edge colours 8 px into the clear area and fills the rest with the mean figure
     colour. Without this, scaled sprites filter in the old background as a light
     fringe.
  4. Crop to the figure with a 16 px margin, clamped to the image and at least
     256 px wide (one thumbnail width).
  5. Fail with `cutout_failed` when less than 0.5 % or more than 90 % of the frame
     is figure.

  The `cutout` field is optional, so a parent from before this change still works
  with the new child.
- **Parent.** The worker verifies the segmenter directory at startup under the same
  manifest-pin rule as Animagine: exact file set, sizes and hashes, and exactly one
  ONNX file (`verify_cutout_model`). Every child PNG now goes through
  `normalize_png` (the upload path, which drops metadata chunks and keeps pixels
  and alpha) before `validate_png`. A sprite must be 8-bit RGBA and match the crop
  box the child reports, and the box must lie inside the render. The runtime record
  must then include `onnxruntime`. A transparent request to a worker without a
  segmenter fails with `cutout_unavailable`.
- **Storage (migration 0025).** `narrative_image_jobs` gains `transparent`,
  `cutout_model` (`repo@revision`) and `cutout_sha256` (the ONNX file), with
  checks:
  - Transparent jobs are full-body character jobs.
  - The cutout record exists only on transparent jobs.
  - A completed transparent job must name its segmenter. An older worker that
    ignored the flag therefore cannot complete such a job with opaque images.

  The images become library assets of kind `sprite` (candidates until approved),
  named `{character} sprite N`. Each one's provenance adds `cutout`: segmenter
  repo, revision, SHA-256, licence (Apache-2.0) and crop box. The asset licence
  stays the image model's. The service also refuses a result whose cutout state
  does not match the job.
- **API.** `ImageJobResponse` has `transparent` and `cutout: {model, sha256} | null`.
- **Studio.** The character sheet has a "Transparent background" checkbox. It is
  enabled for full-body framing and turns the button into "Generate 4 sprites".
  Sprite candidates show on a checkerboard without cropping and offer "Approve
  sprite" (the library approval) instead of "Use as portrait". "How the latest
  images were made" shows the cutout model and hash.

Not built, as agreed: the per-expression Sprites section (the main session's next
slice), expression sheets, IP-Adapter consistency and OpenPose poses.

## Qualification

**Real segmenter on real renders (CPU).** I ran the child's own functions with the
pinned `isnetis.onnx` (SHA-256 `f15622d8…6e99`, verified) on the four full-body
Animagine renders in `notes/portrait-prompt-fidelity/before/`. Their gradient and
tinted backgrounds are harder than the white background this mode asks for.
Outputs are in ignored `notes/sprite-cutout-qualification/cpu-existing-renders/`
(sprites, dark-background composites, `summary.json`, `on-dark-sheet.png`,
`edge-zoom.png`).

| Render | Sprite | Cutout time | Corner alpha | Figure alpha (mask > 0.95) | Clear / opaque |
| --- | --- | --- | --- | --- | --- |
| seed 313188645 | 826×1125 | 0.84 s | 0, 0, 0, 0 | 255 | 52 % / 42 % |
| seed 1275247027 | 832×1130 | 0.94 s | 0, 0, 0, 0 | 255 | 58 % / 40 % |
| seed 2309587623 | 806×1139 | 1.03 s | 0, 0, 0, 0 | 255 | 58 % / 38 % |
| seed 2089298423 | 832×1182 | 0.98 s | 0, 0, 0, 0 | 255 | 42 % / 54 % |

The segmenter loads in 0.97 s. On a dark background, edge pixels on the three
light-background renders are 4–8 luma darker than a cutout without decontamination
would show, so the light fringe is gone. On the dark-background render they are
5 luma lighter, because the figure's own colour is restored. Clear pixels carry
figure colours (mean RGB about 130–180), not the background. Seen at full size,
hair strands fade into the dark background with no outline. A few red petals drawn
as part of the art stay, because they are separate small regions of the figure.

**GPU end to end: one transparent full-body character, passed.** The first attempt
was blocked: a `vllm/vllm-openai` container from another local project held 9,962
of 12,227 MiB of GPU memory, and the child needs 8 GB free. The user stopped that
container. A batch from the portrait-prompts session then finished and its image
child exited. With 11,944 MiB free, no Ollama model loaded and no other image
child, I ran the opt-in live test
`test_real_gpu_transparent_job_stores_a_cut_out_sprite` once.

That test lives in `tests/integration/test_narrative_image_workflow_live.py`. It
runs this branch's code: API job, outbox relay, owned Temporal workflow and
activity, the real child on the RTX 5070 Ti with both pinned models, then the
stored, hash-verified content. It passed in 66 s. The job ran for 58 s, covering
child start, model load, render and cutout.

| Check | Result |
| --- | --- |
| Job | `completed`, `transparent: true`, 1 asset of kind `sprite`, status `candidate`, named `mira sprite 1` |
| Recorded cutout | `skytnt/anime-seg@493cb60893f47441b26ec4fb9a306bce9e342982`, SHA-256 `f15622d853e8260172812b657053460e20806f04b9e05147d49af7bed31a6e99` |
| Runtime | torch 2.11.0+cu128, diffusers 0.42.1, CUDA 12.8, onnxruntime 1.31.1, RTX 5070 Ti Laptop GPU |
| Prompt | `…, full body, standing, white background, looking at viewer, simple background, …` |
| Sprite | 808×1212 8-bit RGBA, 991,613 bytes, crop box `[17, 4, 825, 1216]` in the 832×1216 render, seed 2704456433 |
| Alpha | corners 0, 0, 0, 0; maximum on all four borders 0; 49.3 % opaque, 48.7 % clear, 2 % partial; 1,175 opaque pixels in the centre column |
| Clear pixels | mean RGB 137, 134, 142: bled figure colours, not the white background |

On a checkerboard, a dark backdrop and a green backdrop, the figure is cut out with
no box of scenery. Hair, coat, ribbons and a loose ponytail strand keep soft edges
with no light fringe. The evidence is in ignored
`notes/sprite-cutout-qualification/gpu/`: the sprite, its job record
`680d4c7f40d74d91.json`, `sprite-sheet.png` and `sprite-edges.png`.

One finding for the later sprite slice: the figure fills render rows 20–1208 of
1216, leaving only 7 px below the hem. The long robe hides the feet. Nothing is cut
off here, but `feet out of frame` in the negative prompt does not guarantee
headroom. A stage that anchors sprites at the bottom will place the hem at the
bottom edge. If later poses need visible feet, the prompt or canvas needs more room
below.

To run it again:

1. Free at least 8 GB of dedicated GPU memory (`nvidia-smi`).
2. Run `uv sync --frozen` in `runtimes/imagegen`.
3. From the repository root, run:

```powershell
$notes = (Resolve-Path notes).Path
$env:FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE = "$notes\narrative-temporal-owned.json"
$env:FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR = (Resolve-Path runtimes\imagegen).Path
$env:FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR = "$notes\models\animagine-xl-4.0"
$env:FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256 = (Get-FileHash "$notes\models\animagine-xl-4.0\flintgraph-download.json" -Algorithm SHA256).Hash.ToLower()
$env:FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MODEL_DIR = "$notes\models\anime-seg"
$env:FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MANIFEST_SHA256 = (Get-FileHash "$notes\models\anime-seg\flintgraph-download.json" -Algorithm SHA256).Hash.ToLower()
$env:FLINT_GRAPH_NARRATIVE_IMAGE_SAVE_DIR = "$notes\sprite-cutout-qualification\gpu"
uv run pytest tests/integration/test_narrative_image_workflow_live.py -k transparent -v
```

Leave `FLINT_GRAPH_NARRATIVE_PG_URL` unset, or the test also runs on PostgreSQL and
renders twice. If Ollama's assistant model holds the GPU, also set
`FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL` so the worker unloads it once.

## Verification

- `uv run pytest`: 1639 passed, 77 skipped (opt-in live and fixture tests). The
  targeted suites pass: prompt (+1), worker settings (+1), child protocol against the
  scripted fake child (19 cases, +9: crop box, RGBA, metadata normalization, missing
  or mismatched segmenter, bad and outside boxes, missing runtime record,
  `cutout_failed`, manifest with exactly one ONNX), character API integration (+2:
  validation, idempotency, sprite assets, provenance, RGBA content, portrait
  refusal, library approval, failure without cutout). 55 passed on SQLite and 17
  on the owned PostgreSQL. The PostgreSQL run applies migration 0025 in a
  throwaway schema.
- Live on the owned Temporal with the real GPU: the transparent sprite test passed
  (1 run, 66 s; see Qualification).
- The child's own checks (`uv run --frozen python -I -m unittest discover -s . -p
  "test_*.py"` in `runtimes/imagegen`, with `FLINT_IMAGEGEN_CUTOUT_MODEL` set): 11
  passed. They cover mask-to-alpha on synthetic arrays (thresholds,
  decontamination, bleed, crop margin and clamping, minimum width, empty and full
  masks), letterboxing, request validation in a real child process, hash
  refusal, and the real segmenter's I/O contract.
- `uv run ruff check .`, `uv run mypy` (233 files), the deterministic eval gate,
  `alembic upgrade head --sql` (with `FLINT_GRAPH_ENV=test`) and
  `docker compose config` pass.
- Frontend: `npm test` (72, +1 for the sprite model), `npm run typecheck`,
  `npm run build`.

## Operating notes

- After merging, run `uv sync --frozen` in `runtimes/imagegen` (adds onnxruntime,
  flatbuffers and protobuf). Then set the two cutout settings and restart the
  image worker; until then, transparent jobs fail with `cutout_unavailable`. The
  owned worker was not restarted for this work. If it is still running code from
  before this change, the database check stops it from completing a transparent
  job with opaque images.
- Migration 0025 follows 0024. A parallel branch that also adds a 0025 needs its
  `down_revision` rebased.
- `AGENTS.md` is not updated here, to avoid conflicting with the main session; it
  needs one line pointing to this report.
