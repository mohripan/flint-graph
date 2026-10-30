# ADR 0039: Local GPU image generation in an isolated child

Date: 2026-10-31. Status: accepted for implementation (tracking #170, #128).
This ADR records intent and measured feasibility, not delivered behavior.

## Context

The user wants characters created from a description with a generated anime-style
image, on their own GPU at no per-call cost. On 2026-10-30 they approved Animagine
XL 4.0 (`cagliostrolab/animagine-xl-4.0`, CreativeML Open RAIL++-M), downloaded with
a pinned revision and verified SHA-256 under ignored `notes/models/`. The machine is
an RTX 5070 Ti Laptop GPU (12 GB, compute capability 12.0, Blackwell) that is shared
with Ollama, whose 12B assistant model holds ~7.9 GB while loaded.

Measured on 2026-10-31 with `runtimes/imagegen` (PyTorch 2.11.0+cu128, diffusers
0.42.1), 832×1216, 28 Euler-ancestral steps, CFG 5, fp16, tiled VAE:

- Model load 11.9 s; first image 27.9 s (CUDA warm-up), then ~11 s each; four
  images in 79.5 s wall including interpreter start; peak 7.7 GB (9.5 GB untiled).
- With Ollama's model resident, Windows reported 10.8 GB free through
  `cudaMemGetInfo` while NVML reported 3.9 GB. The driver spilled into shared
  memory and each image took ~115 s instead of failing.
- Outputs pass the existing strict PNG validator unchanged; prompts of ~48 CLIP
  tokens fit the 77-token window.

## Decision

1. Generation runs only as bounded Temporal jobs in an opt-in
   `narrative_image_worker` process on its own task queue, one job at a time, with
   the ADR 0037 run-registration, fencing and recovery pattern and IDs-only
   history. It never runs inside an API request.
2. The GPU work runs in a separate child (`runtimes/imagegen/generate.py`) from its
   own locked environment (`runtimes/imagegen/uv.lock`, CUDA 12.8 wheels), so
   PyTorch never enters the API or CI environment. The parent starts it with
   `python -I`, a minimal environment with Hugging Face offline flags, no database,
   object-store or Temporal credentials, a fresh private output directory and a
   wall-clock watchdog. It talks over a versioned JSON stdin/stdout protocol.
3. The child loads the pinned local model from safetensors only
   (`local_files_only`, no remote code), checks dedicated free memory through NVML
   before loading (refusing with `gpu_busy`), generates, writes PNGs and exits so
   GPU memory returns to Ollama. The worker verifies the model files against the
   pinned download manifest once at startup.
4. The parent trusts nothing from the child: bounded output lines, at most four
   images, the strict PNG validator, exact dimensions and size caps before bytes are
   stored create-only and hash-verified. Model, revision, prompt, seed, settings and
   runtime versions are recorded with each image.
5. Outputs are candidates. Only explicit creator approval makes an image a
   character's portrait. Prompts include Animagine's `safe` rating tag and an
   explicit-content negative prompt. This steers but does not guarantee, and review
   is the control.
6. On a shared GPU, the operator may opt in to having the worker ask Ollama to
   unload the configured assistant model (`keep_alive: 0`) before retrying a
   `gpu_busy` job. Without that setting, the job retries with backoff and then fails
   with a clear message.

## Alternatives and consequences

Running diffusers inside the API or main worker would put a multi-gigabyte CUDA
stack and model memory into every process and every CI run. A remote image API
costs money per call and was not chosen. A warm resident generator would save
~12 s load and ~17 s warm-up per job, but would hold ~7 GB that the assistant model
needs; it is a later optimization behind the same protocol. Linux/container
execution uses the same child and lock but is not qualified yet. Releases do not
include generated images until the asset export binding (#128) lands.

## References

- [Character creation design](../superpowers/specs/2026-10-31-character-creation-design.md).
- [ADR 0037](0037-temporal-owned-narrative-build-attempts.md),
  [ADR 0038](0038-conversational-authoring-through-reviewed-proposals.md).
