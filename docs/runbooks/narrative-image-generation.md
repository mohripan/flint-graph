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
- The isolated runtime, installed once (PyTorch with CUDA is several gigabytes):

  ```powershell
  cd runtimes/imagegen
  uv sync --frozen
  ```

## Configuration

| Setting | Purpose |
| --- | --- |
| `FLINT_GRAPH_NARRATIVE_IMAGE_GENERATION_ENABLED=true` | API admits portrait jobs (otherwise 503). |
| `FLINT_GRAPH_NARRATIVE_IMAGE_WORKER_ENABLED=true` | Explicit worker opt-in. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_TASK_QUEUE` | Its own Temporal queue (default `narrative-image`). |
| `FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR` | Absolute path to `runtimes/imagegen`. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR` | Absolute path to the model directory. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256` | SHA-256 of `flintgraph-download.json`; the pin. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL` | Optional: Ollama model to unload when the GPU is busy. |
| `FLINT_GRAPH_NARRATIVE_IMAGE_MAX_ACTIVE_JOBS_PER_WORKSPACE` | Queued plus running jobs per workspace (default 2). |
| `FLINT_GRAPH_NARRATIVE_IMAGE_JOB_DEADLINE_SECONDS` | Child watchdog (default 600). |

The worker also needs the usual database, Temporal and object-store settings. Start
it with `python -m flint_graph.processes.narrative_image_worker`. At startup it
hashes every model file against the pinned manifest (about 20 s) and refuses to run
on a mismatch, an extra file or a missing runtime.

## What it generates

- Character portraits: 832×1216, from the Characters tab.
- Backgrounds: 1344×768 scenery with `no humans`, from the Assets tab
  (`POST /v1/narrative/projects/{id}/assets/background-jobs`).

Both use the same worker, queue and limits. Candidates wait in the library until a
member approves them. Uploads (PNG images, static TTF/OTF fonts) need no worker.

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
  `generation_timeout`, `invalid_output`, `model_invalid`, `storage_unavailable`).
  The child's stderr is discarded. To diagnose, run `runtimes/imagegen/generate.py`
  by hand with a JSON request on stdin.
- Images are stored create-only under
  `tenants/{tenant}/narrative/projects/{project}/assets/{id}/` and served only after
  their recorded SHA-256 verifies. Discarded candidates keep their bytes; cleanup is
  not implemented yet.
