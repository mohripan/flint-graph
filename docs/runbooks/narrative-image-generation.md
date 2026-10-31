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
| `FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL` | Optional: Ollama model to unload when the GPU is busy. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_MAX_ACTIVE_JOBS_PER_WORKSPACE` | Queued plus running jobs per workspace (default 2). |
| `FLINT_GRAPH_NARRATIVE_IMAGE_JOB_DEADLINE_SECONDS` | Child watchdog (default 600). |

The worker also needs the usual database, Temporal and object-store settings. Start
it with `python -m flint_graph.processes.narrative_image_worker`. At startup it
hashes every model file against the pinned manifest (about 20 s) and refuses to run
on a mismatch, an extra file or a missing runtime. The same applies to the cutout
directory when it is configured; the log says whether the cutout is ready. Without
it, transparent jobs fail with `cutout_unavailable` and everything else works.

## What it generates

- Character portraits: 832×1216, from the Characters tab.
- Transparent stage sprites: the "Transparent background" box on a full-body
  character (`"transparent": true` on a portrait job). The render uses
  `white background` tags, then the child cuts the figure out and stores a cropped
  8-bit RGBA PNG as a library asset of kind `sprite`. A candidate is approved with
  "Approve sprite" or in the library. The job records the segmenter as
  `cutout_model` (`repo@revision`) and `cutout_sha256` (the ONNX file). Each sprite's
  provenance has the crop box inside the 832×1216 render.
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

## Operation

- One generation runs at a time. A job of four 832×1216 portraits takes about 80 s
  with the GPU free: 12 s to load the model, about 28 s for the first image and about
  11 s for each later one.
- Ollama's 12B assistant model holds about 8 GB. If too little dedicated memory is
  free, the child refuses with `gpu_busy` rather than letting Windows spill into
  shared memory (about 10× slower). With the release setting, the worker asks Ollama
  to unload that model and retries once. Otherwise the job retries with backoff and
  then fails with a clear message. The assistant reloads its model on its next turn.
- Child failures map to safe codes (`gpu_busy`, `out_of_memory`,
  `generation_timeout`, `invalid_output`, `model_invalid`, `storage_unavailable`,
  and for sprites `cutout_failed` when no render had a plausible figure and
  `cutout_unavailable` when the worker has no segmenter). A sprite render without
  a usable figure is skipped, so a job can finish with fewer candidates than asked.
- Other GPU programs count too. The child needs 8 GB free, so a local vLLM or
  similar container holding most of a 12 GB GPU makes every job fail with
  `gpu_busy`; the Ollama release setting cannot free that memory.
  The child's stderr is discarded. To diagnose, run `runtimes/imagegen/generate.py`
  by hand with a JSON request on stdin.
- Images are stored create-only under
  `tenants/{tenant}/narrative/projects/{project}/assets/{id}/` and served only after
  their recorded SHA-256 verifies. Discarded candidates keep their bytes; cleanup is
  not implemented yet.
