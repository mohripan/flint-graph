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


## Reviewed prompt catalog

Assistant instructions, provider/extraction templates and default image conditioning
and content policy use the reviewed catalog. Apply `0033_prompt_bundles`; queued
work retains its admission-time bundle. The default stays offline. Langfuse is an
optional authoring/refresh service with Viewer runtime credentials, no tenant-data
uploads, and no SDK tracing. See [prompt management](prompt-management.md) for
import, review, activation, diagnosis and rollback. Image TOML overrides remain
explicit in locked mode and cannot be combined with managed Langfuse mode.

## Character-preservation research (M40)

The offline [bench](../../evals/character-preservation/README.md) has separate CPU
and GPU environments, fixed original fixtures, model hashes, contact sheets and
explicit agent reviews. See [measured results](../reports/2026-11-01-character-preservation.md)
and [ADR 0046](../adr/0046-character-preservation-measurement-and-pose-direction.md).
The research lab is not a new worker mode. The Studio slice below uses the
existing image worker and model.

Run experiments sequentially with new output directories. Refuse a busy GPU;
never stop another owner's process to fit a model. Cached ControlNet requires
11 GiB free; its uncached baseline requires 11.6 GiB and nearly fills this card.
Staged klein requires 11 GiB free GPU and 9 GiB available host RAM, releases the
text encoder before loading the transformer, and uses only verified local files.
Private weights/caches/raw outputs stay under ignored `notes/`, outside games.

Do not activate the provisional score fits as candidate filters. The tiny agent
fixture set is not creator calibration, garment overlap misses visible changes,
and CCIP's exact model license is unresolved for production. An unavailable score
is unknown and never prevents approval. Actual LoRA training requires the creator
to select approved images; the retained synthetic probe saves no trained weights.

## Reviewed looks and clothing tags

Apply `0034_narrative_looks`, then reload the API/frontend through the owner's
normal process. Characters → Reviewed looks locks an approved reference and
creator-edited tags as an immutable named look. Studio portrait, expression and
CG requests pin that exact record; a new default affects later requests. Use
**New look** for another outfit. **Compare look** on image cards saves manual
feedback and offers an optional coarse garment-tag comparison. Scores/warnings
never hide images or revoke approval. See
[ADR 0047](../adr/0047-reviewed-character-looks-and-advisory-feedback.md) and the
[report](../reports/2026-11-01-reviewed-character-looks.md).

Manual looks/feedback need no ML installation. For optional tag suggestions and
comparisons, prepare the separate CPU environment:

```powershell
uv sync --project runtimes/character_eval
```

Download only the reviewed `wd14` model using the fetch/copy procedure in the
[bench README](../../evals/character-preservation/README.md#prepare-offline-models).
Copy its reviewed manifest bytes verbatim. Do not install CCIP for this feature.
Set these API values in the owner's private environment:

| Setting | Value |
| --- | --- |
| `FLINT_GRAPH_NARRATIVE_LOOK_TAGGER_PYTHON` | Absolute path to the isolated environment's Python executable. |
| `FLINT_GRAPH_NARRATIVE_LOOK_TAGGER_MODEL_DIR` | Absolute path to `wd14`, containing `model.onnx`, `selected_tags.csv` and its reviewed manifest. |

The exact manifest SHA-256 is
`7e95e8ddb226fe53d512698f9589cbe37d7d1a26f53a78f63fa31010e4ddccf5`.
Every model file is verified; the child uses CPU only and downloads nothing.
Each API process runs at most one child, bounded to 45 seconds. An occupied
tagger returns 429 so another tab can retry instead of waiting indefinitely.
Keep weights/private observations outside releases. Missing or broken settings,
pins or bytes produce a recoverable message; use manual entry/review rather than
guessing a score. Tags miss colors and fine details. CCIP, ranking/best-N and
per-person CG metrics remain unqualified. Assistant image suggestions retain
their profile-based path.

## Character poses (ADR 0048)

This separate optional worker edits one immutable reviewed look using
`black-forest-labs/FLUX.2-klein-4B`, revision
`e7b7dc27f91deacad38e78976d1f2b499d76a294` (Apache-2.0). Use the pinned download
manifest from the model-fetch tool, not a moving branch or unverified checkpoint.
A reproducible download uses the public file list in
[`runtimes/posegen/model-files.txt`](../../runtimes/posegen/model-files.txt):

```powershell
$poseFiles = Get-Content runtimes/posegen/model-files.txt
$poseArgs = @('--repo','black-forest-labs/FLUX.2-klein-4B','--revision','e7b7dc27f91deacad38e78976d1f2b499d76a294','--license','apache-2.0','--out','notes/models/flux2-klein-4b')
foreach ($poseFile in $poseFiles) { $poseArgs += @('--file',$poseFile) }
uv run python tools/narrative/fetch_model.py @poseArgs
```

The model directory must contain the diffusers configuration, tokenizer, Qwen3
encoder, transformer and VAE files listed in that manifest. Its SHA-256 is the
`NARRATIVE_POSE_MODEL_MANIFEST_SHA256` pin; every file is verified at worker startup
and in each child. The operator retains the weights privately.

```powershell
uv sync --frozen --project runtimes/posegen
$env:FLINT_GRAPH_NARRATIVE_POSE_WORKER_ENABLED='true'
uv run python -m flint_graph.processes.narrative_pose_worker
```

Configure absolute `FLINT_GRAPH_NARRATIVE_POSE_RUNTIME_DIR` and
`FLINT_GRAPH_NARRATIVE_POSE_MODEL_DIR`, the manifest pin and a distinct
`FLINT_GRAPH_NARRATIVE_POSE_TASK_QUEUE`. Enable API admission separately with
`FLINT_GRAPH_NARRATIVE_POSE_GENERATION_ENABLED=true`. For the launcher, append
`pose` to the explicit `STUDIO_SERVICES` list; the default services do not enable it.
Transparent results also need the existing pinned `NARRATIVE_IMAGE_CUTOUT_*`
installation. Reload API/image/pose worker code together after migration 0035,
while queues are idle: older image relays cannot distinguish the new pose sidecar.
Never restart another operator's processes. If using Langfuse refresh, deploy and
activate a reviewed bundle containing `narrative.image.pose` before enabling poses.

The child is offline and has a private temporary home/cache. It stages bf16 text
encoding, frees the encoder, then loads transformer/VAE directly to CUDA with low
CPU memory loading. Output is 768×1152, four steps, guidance 1; transparent sprites
are cropped after CPU segmentation. No high-resolution repaint, face-only inpaint,
additional references or model switching is hidden behind this operation.

This path needs one CUDA device supporting bf16, 11 GiB free dedicated VRAM and
6 GiB available host RAM. These are admission observations, not a shared resource
reservation: other image/audio/LLM workers can contend. A busy resource or OOM retries
within the inherited three-attempt workflow; it never unloads another model. The
child deadline defaults to 900 s (60–1100 s configurable) inside the 20-minute
activity timeout. GPU coordination remains M41 work. The API imports no ML packages.

Klein's distilled editing pipeline does not support SDXL negative conditioning.
The typed policy checks creator instructions/reviewed tags; its negative-prompt
tags are not applied by this model. The prompt is catalog-versioned and the exact
chat-wrapped token count is checked against 512 before encoding; long input fails
with `prompt_too_long`, rather than being silently truncated.

Jobs use the existing full-body character-render ledger purpose plus an immutable
`narrative_pose_jobs` sidecar. POST/GET
`/v1/narrative/projects/{project}/characters/{character}/looks/pose-jobs` explicitly
identifies `operation=pose`, includes its frozen look/model and returns normal
image-job progress/assets. Generic image-job cancel/content endpoints still apply.
Original portrait/expression/CG workers exclude pose plans during dispatch/recovery;
pose workers select only them. Restoring a changed model pin is required to run an
already-admitted job; retries never silently substitute the new installation.

Optional real-model check (requires these private operator settings and an idle GPU):

```powershell
$env:FLINT_GRAPH_ENV='test'
$env:FLINT_GRAPH_NARRATIVE_POSE_LIVE='1'
uv run pytest tests/integration/test_narrative_pose_live.py -q --tb=short
```

This check uses the repository's synthetic adult QA reference, not a creator's
project. See the [delivery report](../reports/2026-11-01-character-poses.md) for the
real Temporal/MinIO/browser proof and current fidelity limits.

### Additional approved views and rendering consistency (ADR 0049)

After migration 0036 and deployment of the compatible pose API/worker/child,
set `FLINT_GRAPH_NARRATIVE_POSE_MAX_REFERENCES=2` to allow one optional extra view.
The default remains one. The primary reviewed image defines identity/outfit and
requests line weight, palette, shading and light direction. The extra is labelled
front, side, back or detail and is instructed to provide missing shape/garment
information without blending its rendering style. These are model instructions;
outputs can still change linework, illumination and fine costume details.

In Characters → Poses, choose **Additional approved view**, inspect it, label its
view, and explicitly confirm the same character/outfit. The image must be approved,
from the project, unassigned or assigned to this character, and distinct from the
primary hash. Do not select another outfit as a supplementary view. **References
used** shows the immutable sources for an earlier job, even after changing the
form or default look. Reusing a request key with different views returns conflict.

Both sources are hash verified before generation. The additional image fits within
512×512 with Lanczos preprocessing; the primary keeps its existing preprocessing.
The result provenance records ordered source hashes, sizes, view-manifest hash and
preprocessing identity. Child protocol 2 has two fixed private reference files;
protocol 1 remains accepted. Existing single-source job hashes/replays remain valid,
including jobs admitted before the new reference table existed. The new table has
workspace/project foreign keys, an ordered primary/extra constraint and no game
format effect. No reference weights, training data or model files enter exports.

Identity similarity does not measure drawing style or lighting. The live fixture
still had heavier outlines than its primary despite the instructions. For a change
limited to facial expression, use the existing bounded face repaint: it preserves
the body/outfit pixels. A newly drawn pose needs visual review. Project style adapters are
trained through ADR 0050 below; neither instructions nor adapters eliminate review.

To qualify two-reference generation, set the existing live-model opt-in plus
`FLINT_GRAPH_NARRATIVE_POSE_LIVE_SECONDARY` to an explicitly approved synthetic QA
PNG, then run `tests/integration/test_narrative_pose_live.py`. That path verifies
ordered input hashes and the secondary-size cap, not a style-quality score.

### Private project style training (ADR 0050)

After migration 0037, **Look → Project art style** lets a member select 4–12
approved project images, review a content caption for each, confirm training
rights, and train an immutable named version. Use images with consistent
linework/shading and captions describing the person, clothes, pose and scene.
Different characters help separate rendering style from identity. Four images
is an admission minimum, not an established quality threshold. The qualification
set was selected and reviewed by an agent, not calibrated by the creator.

Install the isolated trainer and compatible pose runtime:

```powershell
uv sync --project runtimes/stylegen
uv sync --project runtimes/posegen
```

Keep the existing pinned klein model and pose settings. Add the opt-in settings
to private operator configuration (absolute directory on this machine):

```dotenv
FLINT_GRAPH_NARRATIVE_STYLE_TRAINING_ENABLED=true
FLINT_GRAPH_NARRATIVE_STYLE_WORKER_ENABLED=true
FLINT_GRAPH_NARRATIVE_STYLE_RUNTIME_DIR=C:/Projects/flint-graph-codex-character-studio/runtimes/stylegen
FLINT_GRAPH_NARRATIVE_STYLE_TASK_QUEUE=narrative-style
FLINT_GRAPH_NARRATIVE_STYLE_DEADLINE_SECONDS=1800
```

Select `style` as an additional `STUDIO_SERVICES` entry, beside the existing
`pose` entry; it is optional and off by default. Standalone start:
`uv run python -m flint_graph.processes.narrative_style_worker`. A separate task
queue and absolute pose/training runtime plus base-model manifest pin are required.
Deploy API, worker, both children and their locks together. Existing active owned
processes require an owner-managed reload; do not restart someone else's Studio.

The trainer uses rank/alpha 4, 512² area / 768-side aspect buckets in multiples of
32, batch one, cached text and VAE latents, frozen bf16 base weights, FP32 LoRA
parameters, gradient checkpointing and AdamW8bit at 1e-4. The creator chooses
20–400 updates and a 32-bit seed (defaults 200 and 42). It needs the same 11 GiB
free dedicated GPU / 6 GiB available host admission floors as poses. These are
observations, not reservations; concurrent image/audio jobs can still contend.
No other model process is stopped or unloaded. Busy/low-memory attempts retry at
20 and 40 seconds before failing safely. M41 owns shared GPU coordination.

A dedicated ledger/outbox/run registration and execution token fence every
attempt. Sources must remain approved and match frozen hashes on each retry.
Cancellation stops only that child's process tree. Progress and loss records
persist across views. Closed-run recovery does not interrupt a slow live run.
Weights are strict finite FP32 rank-4 safetensors, hash checked and create-only in
private `style-adapters/<job>/executions/<token>/` objects. They have no ordinary
asset binding or browser download route. Abandoned attempt objects remain private;
retention/garbage collection is not implemented by this slice.

In **Characters → Poses → Project style version**, choose a completed version
and strength 0.1–1.0. Each pose freezes its exact version/weight hash, dataset,
recipe and base model; no adapter remains the default. Metadata identifies the
version used. This path targets the installed FLUX.2 klein 4B renderer. It does not
apply these weights to the SDXL expression/CG workers. Character-specific LoRA
training and broader quality calibration remain #184 work. Review candidates:
style/lighting and fine garment details can still drift.

### Optional MLflow tracking

MLflow records training metadata independently of Langfuse's reviewed prompt
catalog. Temporal remains the job executor; PostgreSQL/private object storage
remain authoritative. The root environment has no MLflow dependency.

For a local loopback tracking UI in its isolated pinned environment:

```powershell
uv sync --project runtimes/modeltracking
runtimes/modeltracking/.venv/Scripts/mlflow.exe server --host 127.0.0.1 --port 6096 --workers 1 --backend-store-uri sqlite:///notes/model-tracking.db --default-artifact-root ./notes/model-tracking-artifacts --no-serve-artifacts
```

On Linux use `runtimes/modeltracking/.venv/bin/mlflow`. Set
`FLINT_GRAPH_NARRATIVE_MODEL_TRACKING_URL=http://127.0.0.1:6096` on the style worker;
omit it to disable tracking. The URL is an operator HTTP(S) origin without embedded
credentials, query or fragment. The worker makes bounded REST requests, then logs
loss steps, image count, time/memory and opaque job/base/dataset/recipe/weight
hashes. It uploads no images, captions, prompts, paths or weights and enables no
autologging. Tracking failure does not undo training. A crash between publication
and mirroring can leave a completed version without a tracking run; PostgreSQL is
the durable record, and the mirror is not an exactly-once event sink.

Local SQLite/loopback operation is development-only. Linux multi-node production
requires operator-managed MLflow authentication/TLS and shared backing storage,
plus existing Temporal, PostgreSQL and private artifact services. GPU admission
across nodes is separate M41 work; local NVML is not distributed coordination.
See the [delivery report](../reports/2026-11-02-private-style-adapters.md) for exact
measurements and the matched-seed comparison.

### Reviewed-character adapters (ADR 0051)

Migration 0038 adds immutable character-look targets to the existing private
training ledger. In **Characters → Poses → Character look training**, select a
reviewed look, open **Train this reviewed look**, and choose 4–12 approved images
of the same character and outfit, including its locked base. Unassigned uploads
are eligible only with explicit same-look confirmation. Other characters, CG
scenes, backgrounds, missing/discarded bases and foreign project/workspace
resources are refused.

The form starts captions with the look's reviewed traits/clothes. Edit each one
to describe its actual pose and scene; these are suggestions to review, not
new tagger observations. Confirm the same look, check anatomy/hands/feet/limb
count in every source, and confirm training rights. These checks record the
creator's review; they are not an automatic anatomy detector. A likeness/outfit
match can still have extra limbs and must not become training data on that
basis alone.

The existing style worker, klein base pin, rank-4 recipe, numeric metrics and
private safetensors store are reused. `POST /style-jobs` accepts an optional
`character_look` object with `character_id`, `look_id`, `same_look_confirmed` and
`anatomy_reviewed`. Old project-style requests/replay hashes remain valid.
Responses identify `kind=character_look` and the frozen look snapshot. The
sidecar has workspace/project/character/look foreign keys, and its look hash
also participates in the frozen dataset hash. Listings batch target lookup.

**Trained rendering version** in Poses offers project styles and versions for
this exact reviewed look. A different outfit/look needs a compatible version;
it never silently reuses another look's weights. Admission and training/render
retries validate the immutable target and the still-approved base. Generated
PNG provenance records the adapter kind and reviewed-look hash as well as the
existing version/weight hash/strength. The default deployment selects one adapter;
ADR 0052 below enables separate character and project-style selections.

MLflow uses `flint-character-look` for these runs and keeps project styles in
`flint-project-style`, adding only an allowlisted `kind` parameter. It uploads
no character name, look tags, image/caption, prompt or weight artifact. The
worker and API must be deployed together after the migration; the new capability
is hidden when an older API does not advertise `character_training`.

This is character/look training for the installed klein pose path. It does not
complete #184's Animagine training, creator-calibrated comparisons or cross-model
CG support. It also does not guarantee anatomy, exact costume trim, lighting or
style fidelity. Keep candidate review manual. Read the [delivery report](../reports/2026-11-02-character-look-adapters.md)
for the real four-image run and the extra-leg regression example.


### Character plus project style in one pose (ADR 0052)

Apply migration 0039 and deploy the API and pose worker together. Then set
`FLINT_GRAPH_NARRATIVE_POSE_MAX_ADAPTERS=2` (default 1). This advertises
`max_adapters=2` on pose history. Older/default APIs keep the existing single
**Trained rendering version** chooser and old request hashes/protocols 1–3.
Do not restart an owned Studio without coordinating with its owner.

In **Characters → Poses**, select **Trained character look** for this exact
reviewed look and optionally **Project style**. Either may be omitted. Completed
versions are immutable; each selection and strength is frozen in the new job.
Both strengths are 0.1–1 and, when combined, must total at most 1. The form blocks
Generate above that total and explains how to reduce it. Start with 0.5/0.5 and
review the result; this is an initial bounded control, not an optimal recipe.

`POST /characters/{character}/looks/pose-jobs` adds optional
`character_adapter: {id, strength}` beside `style_adapter`. The character role
requires a completed character-look version for this exact approved base/look;
when it is present, the style role accepts only a project-style version. Both
must belong to this workspace/project and match the pinned klein model. Foreign,
wrong-look, wrong-role, duplicate, unfinished and wrong-model versions are refused.
Legacy jobs that put a character version in `style_adapter` remain valid.

A scoped sidecar freezes the character version and weight hash separately from
the existing style binding. The worker verifies both private weights and training
metadata before rendering. Protocol 4 transfers one character followed by an
optional style under fixed local filenames, with hashes and strengths only.
The child loads named Diffusers/PEFT adapters and applies their individual weights.
History and PNG provenance disclose both roles. Weights remain private, never in
ordinary image assets, games or MLflow artifacts. No Godot runtime bump is needed.

Inspect face, outfit details, hands/limbs, linework and scene lighting separately.
Combining adapters does not fix an extra leg or guarantee identical rendering.
See [ADR 0052](../adr/0052-character-and-style-pose-adapters.md) and the
[qualification report](../reports/2026-11-02-combined-pose-adapters.md).


### Manual anatomy review and training (ADR 0053)

Apply migration 0040 and deploy the API/style worker together. In **Assets →
Compare look**, review **Anatomy** separately from character appearance and
clothes. Choose **Anatomy problem — exclude from training** for extra/missing
limbs, malformed hands/feet or faulty body geometry. Approval remains available.
Cards show **Review anatomy** even if identity and clothes are both marked same.
A verdict covers these exact image bytes throughout this project, including
reuploads and comparisons against other looks. Other projects are independent.

The review response adds `anatomy` and `anatomy_version`. To change it, send
`anatomy` and `anatomy_base_version` alongside the existing feedback body. Both
ordinary-review and anatomy versions must be current; a stale write returns 409.
Omitting anatomy preserves it for older clients. Explicit `unknown` clears the
failure after a deliberate revision; it does not assert that anatomy passed.
Old notes are not converted into verdicts automatically.

Character and project-style training pickers disable known flawed sources.
The API returns `anatomy-review-failed` (422) if selected bytes are marked flawed.
If a source is flagged after admission, the style worker rechecks before loading
inputs, during progress and at final publication, then fails the job with
`anatomy_review_failed` and no published weights. Remove the source or revise the
review after inspecting it, then start a new training version. Replaying an old
request still returns its original job. Existing completed adapters stay available.

This is a human review and training-data guard, not automatic anatomy detection
or repair. Unknown sources still require the existing training review/rights
checks. See [ADR 0053](../adr/0053-manual-anatomy-review-and-training.md) and the
[report](../reports/2026-11-02-anatomy-training-review.md).


### Repairing one area of a pose (ADR 0054)

Apply migration 0041 and deploy the API and pose worker together. After qualifying
protocol 5, set `FLINT_GRAPH_NARRATIVE_POSE_REPAIRS_ENABLED=true` and
`FLINT_GRAPH_NARRATIVE_POSE_MAX_REFERENCES=2`. Repairs default off; older APIs
omit the capability and the editor hides the action. Existing pose protocols,
request hashes, images and game runtimes stay valid.

In **Characters → Poses**, choose **Repair area…** on an available completed pose.
Candidates can be repaired before approval. Move the rectangle over a faulty hand,
foot or other detail; drag its corner to resize, use arrows to move (Shift resizes),
or enter Left/Top/Width/Height. Describe the correction and generate 1–2 candidates.
The rectangle must stay inside the native image, at least 16 pixels per side and
at most a quarter of the image. The original is unchanged. Inspect the new detail
and patch edges before approving; the model can miss the requested correction.

`POST /characters/{character}/looks/pose-repairs` accepts `asset_id`, `box`
(left/top/right/bottom in source-native pixels), `instruction`, optional `count`
(default 1) and `idempotency_key`. Sources must be pose images in this exact
workspace/project/character, made with the installed model. The original reviewed
look must remain approved. The job freezes the source SHA/size/dimensions/crop,
rectangle, correction and original character/style adapter versions and strengths.
Retries check the source, look and private weight pins again. An identical replay
returns the admitted job even if the feature is subsequently disabled.

The existing klein editor receives the target first and approved look second.
It redraws a candidate canvas; deterministic compositing retains only the selected
area, feathering eight pixels inward. Transparent sources are reconstructed on
the original canvas for inference, then restored to their exact cropped dimensions.
The parent independently decodes RGB/RGBA PNG pixels and refuses any outside change,
including alpha, with `repair_preservation_failed`. Provenance records the region,
source, actual references, inherited versions and outside-pixel digest. Output
approval and anatomy review remain manual; previous verdicts are not copied.

This is reference editing and compositing, rather than mask-native diffusion.
The model does not guarantee a corrected hand, and an insufficient region can cut
off the generated change. See [ADR 0054](../adr/0054-region-repairs-for-pose-candidates.md)
and the [qualification report](../reports/2026-11-02-pose-region-repairs.md).


### Body guidance (ADR 0055)

The creator's one-leg example reproduces before background removal. Character
and project-style versions do not specify a complete body pose. The optional
**Body guide** in Poses supplies both hip/knee/ankle chains and separate wrists.
Select **Seated — both feet on the floor**, **Standing — arms relaxed** or
**Walking — three-quarter view**, and inspect the preview. Each selection fills
an editable context description. The pose text
adds context; the guide sets body geometry. It replaces the additional character
view, while the approved look and optional trained character/style versions remain
available. History and an active job disclose their actual frozen guide.

Apply migration 0042, deploy API/pose worker together and prepare the public pose
adapter separately from private project training:

```powershell
uv run python tools/narrative/fetch_model.py --repo xocialize/refcontrol-FLUX.2-klein-4B-pose-lora --revision b2b0edf2622f2abd980bf868441149d71b3eb7b0 --license apache-2.0 --file refcontrol-pose-klein-4b.safetensors --file README.md --out notes/models/refcontrol-pose-klein-4b
```

Set `FLINT_GRAPH_NARRATIVE_POSE_GUIDES_ENABLED=true`,
`FLINT_GRAPH_NARRATIVE_POSE_MAX_REFERENCES=2`,
`FLINT_GRAPH_NARRATIVE_POSE_CONTROL_MODEL_DIR` to that directory and
`FLINT_GRAPH_NARRATIVE_POSE_CONTROL_MANIFEST_SHA256` to the downloaded manifest
hash (`8dadc212b55432ef49f4b1b9089eb11d6c2bc56eb23ef1ddd7bdc534f47aa460`).
The default is disabled and older APIs hide the selector. Existing no-guide jobs,
request identities, prompts and protocols 1–5 remain valid. Keep the installed
weights/pins available while admitted jobs finish, even after disabling admission.

`POST /characters/{character}/looks/pose-jobs` adds optional
`pose_guide: "seated-front-v1"`, `"standing-front-v1"` or
`"walking-three-quarter-v1"`; omit it for the existing behavior. The sidecar
freezes the guide description/hash and control-model manifest. One guide and one
extra view cannot be combined. The registered worker verifies the base, public
control pin, approved source and any private versions before model execution.
Protocol 6 uses closed fields, fixed private weight filenames and integer COCO-18
coordinates. The guide's version includes the fixed 0.8 pose strength, body raster
and 512-square appearance preprocessing. Change the version for recipe changes;
never silently alter a deployed guide. This public pose adapter is independent
of the private character/style strength budget and is not a training version.

The dedicated `narrative.image.pose_control` prompt was authored in Langfuse and
is part of the complete offline lock. Existing prompt entries/bundles and typed
image policy remain intact. The weights remain private to the operator runtime;
only image pixels and source/license credit enter game packages. Local repairs
use their existing area-preservation path and retain guided-source attribution;
they do not rerun the pose adapter.

Compare hands, limb continuity, costume details, linework and lighting separately.
A guide can still produce malformed fingers or costume drift. The presets cover
front seated, front standing and three-quarter walking. They
are not a general pose editor, learned anatomy validator or promise that every
output has correct anatomy. See the
[seated report](../reports/2026-11-02-seated-pose-guidance.md) and the
[standing/walking report](../reports/2026-11-02-standing-and-walking-guides.md).
