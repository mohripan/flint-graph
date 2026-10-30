# Character creation with local portrait generation

Date: 2026-10-31. Tracking: #170 (first slice) and the #128 asset-library foundation.
Decision record: [ADR 0039](../../adr/0039-local-gpu-image-generation-in-an-isolated-child.md).

## Goal

The user asked for character creation: today a character is only a name, and they
want to describe a character and get an anime-style image of it. This slice
delivers that inside the Studio on the creator's own GPU at no per-call cost:

1. A character sheet with appearance, character type and framing.
2. "Generate portraits": a durable job that renders up to four candidates locally
   with Animagine XL 4.0, showing progress and allowing cancellation.
3. Candidate review: pick one as the character's portrait (approval), or discard.
4. The chosen portrait appears on the character list and next to that speaker's
   lines in the script editor.

Out of scope for this slice (planned next): showing portraits in playtest and
releases (v1 `line.portrait` plus asset bytes in previews/builds/exports, #128
export bindings), uploads without a model, backgrounds, voices (Kokoro), music
(ACE-Step), turning prose into tags with the local LLM, consistent expressions or
sprites (#158/#167) and assistant-requested generation (#171).

## Story format

Unchanged. Package v1 characters allow only `name`, so appearance and the chosen
portrait are editor metadata stored per project and character ID, like the scene
layout. Revisions, packages, exports and releases do not change in this slice.
Accepted canon for characters is #125's job; it can adopt these profiles later.

## Data (migration 0022)

- `narrative_character_profiles` (PK project + character ID): appearance
  (≤ 600 chars), character type, framing, chosen `portrait_asset_id`, `version` for
  optimistic concurrency, `updated_by`.
- `narrative_image_jobs`: who/what/when, the exact prompt and negative prompt,
  size, steps, guidance and seeds, status (`queued`, `running`, `completed`,
  `failed`, `cancelled`), progress, safe error code, ADR 0037 fencing (workflow run,
  execution token, attempt), and the model and runtime identity reported by the
  worker. Idempotent per project by `Idempotency-Key`.
- `narrative_assets`: one immutable PNG each (plus a child-made thumbnail): SHA-256,
  size, dimensions, seed, self-contained provenance (model, revision, prompt,
  settings, runtime), license, and status `candidate` → `approved` or `discarded`.
  Bytes live in the private create-only artifact store under
  `tenants/{t}/narrative/projects/{p}/assets/{id}/{image|thumbnail}.png` and are
  read back hash-verified. Discarded bytes are kept for now; cleanup is later work.

## API

All tenant/project scoped; foreign projects return 404; archived projects reject
writes with 409. Viewers read, members write.

| Method | Path (`/v1/narrative/projects/{project_id}` …) | Purpose |
| --- | --- | --- |
| GET | `/characters` | Profiles with portrait summaries |
| PUT | `/characters/{character_id}` | Save appearance/type/framing (`base_version`, 409 stale) |
| PUT | `/characters/{character_id}/portrait` | Choose (approve) or clear the portrait |
| POST | `/characters/{character_id}/portrait-jobs` | Queue a generation job (`Idempotency-Key`) |
| GET | `/characters/{character_id}/portrait-jobs` | Recent jobs with their candidates |
| GET | `/image-jobs/{job_id}` | Poll one job |
| POST | `/image-jobs/{job_id}/cancel` | Cancel queued or running work |
| POST | `/assets/{asset_id}/discard` | Hide a candidate |
| GET | `/assets/{asset_id}/content?variant=image\|thumbnail` | Hash-verified PNG bytes |

Admission: 503 when generation is not configured, 429 beyond the per-workspace
active-job limit (default 2), 1–4 images per job, fixed sizes and steps.

## Prompt

Built server-side from structured input so the stored prompt is exact:
`{type tags}, solo, {appearance}, {framing tags}, looking at viewer, simple
background, safe, masterpiece, high score, great score, absurdres` with Animagine's
recommended negative prompt plus `nsfw, explicit`. The `safe` rating tag and
negative terms steer away from explicit output but are not a guarantee; creator
review before approval is the control, and the UI asks creators not to describe
real people. CLIP reads 77 tokens; the child reports truncation and the UI warns.

## Execution

API → transaction (job + ID-only outbox message) → opt-in `narrative_image_worker`
process (relay, recovery and a Temporal worker on its own `narrative-image` queue,
one activity at a time) → fenced activity → isolated child → validation → storage →
fenced completion. This mirrors the qualified assistant job path (ADR 0037/0038).

The child is `runtimes/imagegen/generate.py`, run with `python -I` from its own
locked environment (`runtimes/imagegen/uv.lock`, PyTorch CUDA 12.8 wheels for
Blackwell), never from the API environment. It gets a JSON request on stdin, a
fresh private output directory, a minimal environment with Hugging Face offline
flags, and no database, object-store or Temporal credentials. It loads the pinned
local model with `use_safetensors=True, local_files_only=True` (no remote code),
writes `N.png` and `N.thumb.png`, reports JSON progress lines and exits, which
frees GPU memory for Ollama. The worker verifies the model files against the pinned
download manifest once at startup.

Measured with the GPU free: 12 s load, 28 s for the first image and ~11 s for each
later one, so four candidates take about 80 s. Peak memory is 7.7 GB with the tiled
VAE, so the child requires 8 GB of dedicated free memory, read through NVML.

The parent enforces a wall-clock watchdog, bounded stdout, at most 4 images, the
existing strict PNG validator, exact dimensions and size caps before anything is
stored. Child codes map to safe job errors; `gpu_busy` and `out_of_memory` are
retried. On a single 12 GB GPU a loaded Ollama model leaves too little memory, so
the worker may optionally ask Ollama to unload the configured assistant model
before retrying (`keep_alive: 0`); this is an explicit operator setting.

## Studio

The Characters tab becomes a list (portrait thumbnail, name) and a character sheet:
name, appearance, character type (girl, boy, woman, man, other), framing (portrait,
full body), "Generate 4 portraits", live progress with Cancel, the candidate grid
(Use as portrait, Discard, seed), and the exact prompt under "Details". Images load
through the authenticated API as cached blob URLs. Speaker avatars appear in the
script editor.

## Tests and qualification

Offline: prompt builder, profile/version conflicts, admission limits, idempotency,
role/foreign/archived checks, claim/fence/cancel/complete/fail, relay and recovery,
child protocol parsing and watchdog with a fake child, PNG/dimension rejection and
storage verification, frontend model helpers. Live: real child on the RTX 5070 Ti,
real Temporal/PostgreSQL/MinIO job through the API, browser generation, approval,
reload and speaker avatars.
