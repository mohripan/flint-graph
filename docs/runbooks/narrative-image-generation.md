# Narrative image generation (local GPU)

Character portraits are generated on the operator's own GPU by an opt-in worker
([ADR 0039](../adr/0039-local-gpu-image-generation-in-an-isolated-child.md)). The API
only records jobs; nothing generates inside a request, and nothing calls a paid
service.

## Requirements

- An NVIDIA GPU with at least 8 GB of free dedicated memory and a driver for CUDA
  12.8 (qualified on an RTX 5070 Ti Laptop GPU, 12 GB, Windows 11).
- The Animagine XL 4.0 diffusers download (`cagliostrolab/animagine-xl-4.0`,
  revision `2b7c1b397761bf5bd3cc42e5b39ec99314a75a96`, CreativeML Open RAIL++-M) with
  its `flintgraph-download.json` manifest in one directory and no other files.
- Optional, for transparent sprites: the anime segmentation download
  (`skytnt/anime-seg`, revision `493cb60893f47441b26ec4fb9a306bce9e342982`,
  Apache-2.0): `isnetis.onnx` plus its `README.md` and `flintgraph-download.json`
  manifest in one directory and no other files. It runs on the CPU (about 1 s per
  image).
- Optional, for event CGs of a character (scene art): the IP-Adapter download
  (`h94/IP-Adapter`, revision `018e402774aeeddd60609b4ecdb7e298259dc729`, Apache-2.0):
  `sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors`, `models/image_encoder/`
  (`config.json`, `model.safetensors`), `README.md` and its `flintgraph-download.json`
  manifest in one directory and no other files.
- The isolated runtime, installed once (PyTorch with CUDA is several gigabytes):

  ```powershell
  cd runtimes/imagegen
  uv sync --frozen
  ```

  Re-run it after pulling changes to `runtimes/imagegen/uv.lock`; the cutout needs
  `onnxruntime` from that lock. The child's own checks need no GPU or model:

  ```powershell
  cd runtimes/imagegen
  uv run --frozen python -I -m unittest discover -s . -p "test_*.py"
  ```

  Set `FLINT_IMAGEGEN_CUTOUT_MODEL` to the `isnetis.onnx` path to also check the
  real segmenter's input and output contract.

## Configuration

| Setting | Purpose |
| --- | --- |
| `FLINT_GRAPH_NARRATIVE_IMAGE_GENERATION_ENABLED=true` | API admits portrait jobs (otherwise 503). |
| `FLINT_GRAPH_NARRATIVE_IMAGE_WORKER_ENABLED=true` | Explicit worker opt-in. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_TASK_QUEUE` | Its own Temporal queue (default `narrative-image`). |
| `FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR` | Absolute path to `runtimes/imagegen`. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR` | Absolute path to the model directory. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256` | SHA-256 of `flintgraph-download.json`; the pin. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MODEL_DIR` | Optional: absolute path to the anime-seg directory. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MANIFEST_SHA256` | SHA-256 of that directory's manifest; required with the directory. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_IP_ADAPTER_MODEL_DIR` | Optional: absolute path to the IP-Adapter directory, for event CGs. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_IP_ADAPTER_MANIFEST_SHA256` | SHA-256 of that directory's manifest; required with the directory. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL` | Optional: Ollama model to unload when the GPU is busy. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_MAX_ACTIVE_JOBS_PER_WORKSPACE` | Queued plus running jobs per workspace (default 2). |
| `FLINT_GRAPH_NARRATIVE_IMAGE_JOB_DEADLINE_SECONDS` | Child watchdog (default 600). |

The worker also needs the usual database, Temporal and object-store settings. Start
it with `python -m flint_graph.processes.narrative_image_worker`. At startup it
hashes every model file against the pinned manifest (about 20 s) and refuses to run
on a mismatch, an extra file or a missing runtime. The same applies to the cutout
directory when it is configured; the log says whether the cutout is ready. Without
it, transparent jobs fail with `cutout_unavailable` and everything else works. The
IP-Adapter is checked the same way (about 15 s more); without it, event CG jobs fail
with `ip_adapter_unavailable`.

## What it generates

- Character portraits: 832×1216, from the Characters tab.
- Transparent stage sprites: the "Transparent background" box on a full-body
  character (`"transparent": true` on a portrait job). The render uses
  `white background` tags, then the child cuts the figure out and stores a cropped
  8-bit RGBA PNG as a library asset of kind `sprite`. A candidate is approved with
  "Approve sprite" or in the library. The job records the segmenter as
  `cutout_model` (`repo@revision`) and `cutout_sha256` (the ONNX file). Each sprite's
  provenance has the crop box inside the 832×1216 render.
- High resolution: the "High resolution" box in the character form (on by default
  for transparent sprites; `"hires": true` on a portrait job). Each 832×1216 render is
  upscaled 2× with Lanczos and repainted lightly by the same model (img2img, same
  prompt and seed, strength 0.35), then cut out. Images come out at 1664×2432 (sprites
  are crops of that). The job stores `hires_scale` and `hires_strength`; its `width`
  and `height` stay the base render and `output_width`/`output_height` give the final
  size. Asset provenance records `hires` next to the generation size. Use it for
  characters the stage draws large. Sprites come out two to three times as large
  (1.9–3.5 MB measured, against about 1.0–1.1 MB), so a story's 48 MiB asset budget
  holds roughly 14–26 of them instead of about 45. The repaint can change small
  details, so review the result like any other candidate.
- Backgrounds: 1344×768 scenery with `no humans`, from the Assets tab
  (`POST /v1/narrative/projects/{id}/assets/background-jobs`).
- Character expressions (ADR 0041): Characters → On stage → "Generate
  expressions…" (`POST /v1/narrative/projects/{id}/characters/{character}/expression-jobs`).
  The child repaints only the face inside a box on an approved sprite, image or
  portrait, at strength 0.9, up to four expressions per job, about 10 s each after
  the model loads. Results keep the base's exact size and alpha, so expressions
  swap on stage without the figure moving. They become candidates of the base's
  kind, named `{character} {expression}`. "Use as" approves one and sets it as that
  expression's sprite. The worker fetches the base hash-verified from the store,
  and the child checks the hash again.
- Event CGs of a character (ADR 0041 slice C): Assets → CGs → "Generate CGs"
  (`POST /v1/narrative/projects/{id}/assets/scene-art-jobs`). Choose a character
  and one of its approved portraits, sprites or images ("Look from"), optionally a
  second character (it stands on the right), and describe the scene. The child cuts the figure out of that image, centres it on white and
  passes it to IP-Adapter Plus (ViT-H) at scale 0.5 while it renders a 1344×768 scene
  from the server-built prompt (type, `solo`, the scene as written, the character's
  appearance tags, quality tags). Results are opaque candidate images named
  `{character} CG {n}`; approve one and pick it in Write → Stage → Event CG. The
  job records `reference_assets`, `ip_adapter_scale` and `ip_adapter_model`, and
  each CG's provenance names its references by SHA-256. A plain reference works
  best: effects or busy backdrops around the figure carry into the scene. Two
  characters are experimental: each reference conditions its half of the image and
  both looks survive in about 7 renders of 12, so the Studio starts two jobs of four
  (eight candidates) and asks to keep the best. Check both faces, hair and outfits
  before approving.

All of them use the same worker, queue and limits. Candidates wait in the library until a
member approves them. Uploads (PNG images, static TTF/OTF fonts) need no worker.

## How portrait prompts are built

`flint_graph.narrative.imagegen` builds every prompt on the server, and each job
stores the exact prompt and negative prompt the model saw ("How the latest portraits
were made" in the character sheet).

- The description is split on commas, semicolons, line breaks and sentence ends.
  A fixed phrase map turns common wording into Danbooru tags: `shoulder-length` →
  `medium hair`, `chin-length` → `short hair`, `long silver hair` → `silver hair,
  long hair`, `white-haired` → `white hair`, `red-eyed` → `red eyes`. For a boy or
  man, "his face looks like a girl", "girlish face" or "feminine features" becomes
  `androgynous` (the reverse for a girl or woman). Other text passes through as written.
- Boy and man add `male focus` and negate `1girl, female focus, breasts`. Girl and
  woman negate `1boy, male focus`. Other stays neutral.
- A short or medium hair length without a long one also negates `long hair, very
  long hair`, because the model otherwise defaults to long hair.
- CLIP reads 77 tokens. The longest negative measures 68. A long description is
  truncated, which the job records and the sheet reports.

## Content policy

What is kept out of images is data, not code: the versioned TOML file
`src/flint_graph/narrative/image_content_policy.toml` (`version = 1`).

- `negative` lists tags placed first in every negative prompt: portraits, sprites,
  expressions and backgrounds. The default is `nsfw, explicit`. Animagine XL's rating
  tags are safe, sensitive, nsfw and explicit. Each tag costs CLIP tokens and the
  negative is cut at 77, so a long list pushes the later fixes (hair length, the
  cut-out background) out of reach.
- `blocked` lists words or phrases that refuse a description, an expression name or
  a background before any job starts (HTTP 422 naming the word). Matching ignores case
  and extra spaces and takes whole words: `sex` does not match "Sussex". This applies
  to the assistant's suggested pictures too, when the creator clicks Generate.
- Edit the shipped file, or set `FLINT_GRAPH_NARRATIVE_IMAGE_CONTENT_POLICY` to your own
  copy. The API reads it once at startup and refuses to start on a missing or malformed
  file, so restart the API after an edit. Workers do not read it.
- Each job still stores its exact negative prompt, so a policy change never alters
  what an earlier job recorded. When prompt management moves to Langfuse (M35, #134–#137),
  this file is the natural locked fallback for a labelled policy.

## Operation

- One generation runs at a time. A job of four 832×1216 portraits takes about 80 s
  with the GPU free: 12 s to load the model, about 28 s for the first image and about
  11 s for each later one. A high-resolution sprite took 40 s for its first image
  (15 s standard) on the RTX 5070 Ti, and it needs 9.5 GiB of free dedicated memory
  (8.5 GiB at 1.5×) instead of 8 GiB. An event CG needs 8.5 GiB: four took 95 s
  including the model load (about 11 s each), with the image encoder released before
  the render (8.0 GiB peak instead of 9.2 GiB).
- Ollama's 12B assistant model holds about 8 GB. If too little dedicated memory is
  free, the child refuses with `gpu_busy` rather than letting Windows spill into
  shared memory (about 10× slower). With the release setting, the worker asks Ollama
  to unload that model and retries once. Otherwise the job retries with backoff and
  then fails with a clear message. The assistant reloads its model on its next turn.
- Child failures map to safe codes (`gpu_busy`, `out_of_memory`,
  `generation_timeout`, `invalid_output`, `model_invalid`, `storage_unavailable`,
  and for sprites `cutout_failed` when no render had a plausible figure and
  `cutout_unavailable` when the worker has no segmenter; `ip_adapter_unavailable`
  for an event CG on a worker without the IP-Adapter). A sprite render without
  a usable figure is skipped, so a job can finish with fewer candidates than asked.
- Other GPU programs count too. The child needs 8 GB free (9.5 GiB for high
  resolution), so a local vLLM or similar container holding most of a 12 GB GPU
  makes every job fail with `gpu_busy`; the Ollama release setting cannot free that
  memory.
  The child's stderr is discarded. To diagnose, run `runtimes/imagegen/generate.py`
  by hand with a JSON request on stdin.
- Images are stored create-only under
  `tenants/{tenant}/narrative/projects/{project}/assets/{id}/` and served only after
  their recorded SHA-256 verifies. Discarded candidates keep their bytes; cleanup is
  not implemented yet.
