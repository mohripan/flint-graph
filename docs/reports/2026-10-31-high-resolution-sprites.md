# High-resolution character sprites (hires fix)

Date: 2026-10-31. Branch `claude/adoring-knuth-bddd7d`.

## Why

Since runtime 0.4.0 the stage can draw a character at up to 300% of the screen
height. At 160% (thighs up, cut off below the screen) the visible upper body of a
standard sprite is about 700 source pixels stretched over a 1080p screen. Edges
go soft, line art smears and eyes blur. Renders are 832×1216 (sprites about
808–827×1212 after the cutout), Animagine XL 4.0's native size. Asking the model
for a larger canvas directly breaks the composition (duplicated bodies, long
torsos), so the image is upscaled after the render instead.

## What changed

- **Child** (`runtimes/imagegen/generate.py`). A request can carry an optional
  `hires` field (`{"scale": 1.5 | 2.0, "strength": 0.2–0.6}`). The child renders
  at the base size as before, upscales with Lanczos, and repaints the image with
  `StableDiffusionXLImg2ImgPipeline.from_pipe`. The repaint shares the weights,
  scheduler and tiled VAE, and uses the same prompt, negative prompt, steps,
  guidance and seed. Strength is the share of the schedule that is rerun: 0.35
  reruns 9 of 28 steps. The cutout runs on the final image. A hires request raises
  the NVML free-memory floor to 9.5 GiB at 2× (8.5 GiB at 1.5×). The request
  checks reject other scales, other strengths, booleans and extra keys before any
  heavy import.
- **Prompts** (`flint_graph.narrative.imagegen`). New `HiresFix(scale, strength)`
  with `HIRES_SCALE = 2.0` and `HIRES_STRENGTH = 0.35`. `portrait_request(...,
  hires=True)` attaches it, and `ImageRequest.output_size` gives the final size.
- **Parent** (`infrastructure/narrative_imagegen.py`). New `GenerationRequest.hires`.
  Invalid settings fail as `bad_request` before any child starts. The child gets
  the `hires` key only when it is set, so standard jobs still run on an older child.
  Opaque images must have exactly the upscaled size, and sprite crop boxes must
  lie inside it. The 10 MiB PNG and 1 MiB thumbnail limits are unchanged.
- **Jobs** (migration `0027_narrative_image_hires`). New `hires_scale` and
  `hires_strength` columns: both null, or 1.5/2.0 and 0.2–0.6 on character
  renders only (never on expression or background jobs), checked in the
  database. `"hires": true` joins the request identity only when set, so earlier
  request hashes are unchanged. `width` and `height` stay the base render. The job
  response adds `hires` and `output_width`/`output_height`. Asset provenance
  records `hires: {scale, strength}` next to the generation size.
- **Studio**. A "High resolution" box sits under "Transparent background". It is
  on by default for transparent sprites until the creator sets it. "How the latest
  images were made" shows the final size: the render, how it was upscaled and the
  sprite crops. Each candidate shows its pixel size.

## Bounds and the trade-off

- **Per image.** A 2× render is 1664×2432, inside the strict PNG validator's
  4096 px and 16 MP limits. Every base size and scale lands on whole latents
  (multiples of 8), which the child's unit tests check. Thumbnails stay 256 px
  wide (about 135 KB). Measured sprites are 1.9–3.5 MB, well under the 10 MiB
  limit, which stays.
- **Per story.** A standard sprite is about 1.0–1.1 MB, so a story's 48 MiB asset
  budget holds about 45 of them. At 2× it holds roughly 14–26. Because of that,
  high resolution is a per-job choice, on by default only for sprites. Characters
  that are never drawn large, and portraits, are better left standard. Release
  packs keep their existing limits.
- **Time and memory.** A 2× image took 40 s instead of 15 s and peaked 1.2 GiB
  higher. A four-sprite job should take about three minutes, within the 600 s
  default deadline; one image was measured, four were not.
- **Content.** The repaint is a new render at low strength, not a lossless
  upscale. Composition, pose and colours stay, but small details can change: a few
  light specks appeared on the coat in the qualification sprite. Candidates are
  still reviewed before approval.

## Finding: `from_pipe` silently doubled the model

The first 1.5× run held 11.9 GB at 100% for over 10 minutes without finishing,
because it spilled into shared memory. A per-stage diagnostic showed torch
allocating 13.5 GiB right after the repaint began, double the 6.57 GiB of fp16
weights. In diffusers 0.42.1, `from_pipe` defaults `dtype` to `float32` when
none is given. It then calls `.to(dtype)` on the new pipeline, whose modules are
the shared ones, so the whole SDXL model was cast to fp32 in place. Passing
`torch_dtype=torch.float16` fixes it, and the child comments why. The NVML floor
cannot catch this case, because the child checks free memory before it loads the
model.

## Qualification

GPU: RTX 5070 Ti Laptop (12,227 MiB). Runtime: torch 2.11.0+cu128, diffusers
0.42.1, CUDA 12.8, onnxruntime 1.31.1. The GPU was shared with two other sessions
(the owned image worker, Ollama's assistant model and another session's SDXL
jobs). Every run waited for at least 11 GiB free and refused or retried
otherwise. Early runs that overlapped were stopped and discarded. Evidence:
[qualification.json](evidence/high-resolution-sprites-2026-10-31/qualification.json).
Images are in ignored `notes/hires-qualification/`.

**Child, same seed (2704456433), one transparent full-body sprite each.** All
three runs used the description from the sprite-cutout report.

| Mode | Wall | First image | Torch peak | NVML above idle | Sprite | PNG |
| --- | --- | --- | --- | --- | --- | --- |
| Standard | 37.7 s | 15.3 s | 7.18 GiB | 8.30 GiB | 827×1213 | 1.13 MB |
| 1.5× | 43.7 s | 26.4 s | 7.26 GiB | 8.44 GiB | 1223×1812 | 2.16 MB |
| 2× | 61.5 s | 40.2 s | 7.79 GiB | 9.46 GiB | 1625×2407 | 3.50 MB |

2× fits a 12 GB card, so it is the default. All three sprites are 8-bit RGBA with
fully clear corners and borders and about 53% of pixels opaque.

**Live pipeline.** The new `hires` case of
`test_real_gpu_transparent_job_stores_a_cut_out_sprite` passed in 160 s. It ran
this branch's API job, outbox relay, owned Temporal workflow and activity, and the
real child with both pinned models, then read back the stored, hash-verified
content. The job completed with `hires {2.0, 0.35}` and output 1664×2432. The sprite
is 1315×2221 (1.92 MB), cropped at `[178, 185, 1493, 2406]` inside the upscaled
render. Provenance keeps 832×1216 as the generation size. Alpha: corners 0,
borders 0, 35% opaque.

**On stage at 160%.** The standard and 2× sprites of the same seed were uploaded
to a separate "Hires sprite QA" project on the owned stack. Two characters were
framed at 160% from 4% down, and two at the default 92%. The real Godot playtest
was captured in headless Edge.

- At 160% the figure is 2126 px tall in a 1329 px stage. The standard sprite is
  stretched 1.75×, and its eyes, lashes, hair strands and collar embroidery are
  soft. The 2× sprite (drawn at 0.88×) keeps all of them crisp. The Laplacian
  variance of the face crop rose from 164 to 231. At equal size outside the stage,
  the stretched standard face against the 2× face measured 193 against 320.
- At 92% the 2× sprite is minified 3.5×. Godot samples sprites without mipmaps, so
  zoomed in, the hair outline and coat edges show slight stair-steps that the
  standard sprite (1.8×) does not. At 1:1 both read well and the 2× sprite is
  still slightly crisper. Mipmapped sprite textures in the runtime would remove
  this. That is a runtime change (and version) of its own, left as a follow-up.

## Verification

- `uv run pytest`: 1706 passed, 88 skipped (opt-in live and fixture tests). One
  earlier full run on a busy machine had one failure that did not reproduce. Its
  name was not captured. The
  targeted suites are prompt (+1: hires request and output size), the child
  protocol against the scripted fake child (+3: upscaled size checked, sprite boxes
  inside the upscaled render, invalid settings never reach the child) and the
  character API integration (+1: hires job, identity, response sizes, provenance,
  and a standard job without them).
- `uv run ruff check .` and `uv run mypy` pass.
- `uv run alembic upgrade head --sql` (with `FLINT_GRAPH_ENV=test`) renders 0026.
- Image child: `uv run --frozen python -I -m unittest discover -s . -p "test_*.py"`
  in `runtimes/imagegen` ran 16 tests, OK (1 skipped without the segmenter path):
  hires request checks, base sizes landing on whole latents within PNG bounds,
  Lanczos upscaling and the memory floors.
- Frontend: `npm test` (82 pass, +1 for the hires default and the size text),
  `npm run typecheck` and `npm run build` pass.
- Live on the real GPU: the hires live test passed once (above).

## Combining with character expressions

The change is rebased onto master after ADR 0041 (character expressions) landed.

- The migration is `0027_narrative_image_hires`, revising
  `0026_narrative_image_expressions`.
- Expression jobs never use high resolution. The child and the parent reject a
  request that asks for both, because a hires repaint would redraw the whole base
  instead of its face. The database check allows hires values only on character
  renders.
- The face inpaint accepts bases up to 2560 px, so 2× sprites (up to 1625×2407)
  can be the base of expressions.
- Master's "keep good cut-outs" change (a render without a usable figure is
  skipped) applies to high-resolution sprites unchanged.
