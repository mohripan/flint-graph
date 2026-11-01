# Character and clothing preservation research

This is an M40 research checkpoint for #180–#186, following the merged Langfuse
migration. It adds an offline test bench and measured experiments, not a Studio
pose feature or an automatic approval system. No real Studio project was opened.

The central finding is that **a good identity score does not establish a useful
pose or a preserved costume**. In the full-image img2img experiment all 16 requests
kept the original standing composition, despite strong identity/clothing scores.
Explicit outfit text helps coarse clothing retention, while fine coat cuts,
trim, buttons and hair arrangements still change. Creator approval remains
essential. Agent fixture judgments below are explicitly separate from creator
calibration; the fixtures are not an approved LoRA training set.

The recommended next pose experiment is **staged FLUX.2 klein 4B**: 16/16 primary
pose requests, mean b36 distance 0.0551, and 9.56 s median render after loading.
It ran on the local 12 GB card by releasing the text encoder first. This is
[ADR 0046's research direction](../adr/0046-character-preservation-measurement-and-pose-direction.md),
not a shipped Studio model change. All seven issues remain open for the
qualification and product work listed below.

## Retained implementation and experiment contract

- `runtimes/character_eval`: isolated ONNX CPU scorer, complete-run comparison,
  review-file preparation, provisional threshold fitting and report aggregation.
  Its optional parity group calls the real imgutils 0.19.0 APIs offline.
- `runtimes/character_lab`: isolated pinned GPU experiments, whole-figure reference
  preparation, model-specific editing instructions and a synthetic LoRA resource
  probe. Studio/image/voice workers and their owned runtime files are unchanged.
- `evals/character-preservation`: original adult fixtures, fixed pose controls,
  public model manifests and reproducible dataset definitions. The
  [bench README](../../evals/character-preservation/README.md) gives commands.
- [Studio integration design](../architecture/character-preservation-research.md):
  reviewed named looks, job snapshots, advisory candidate scores, private LoRAs,
  bounded worker jobs and remaining reference/context experiments.

No database migration, runtime bump, API dependency or game-export dependency is
introduced. Model weights, caches, private raw outputs and future LoRAs stay out
of Git and games. The existing generic model fetcher verifies published commit
identities and LFS SHA-256/Git blob hashes. Inference uses local safetensors/ONNX
only; no runtime hub downloads or remote checkpoint code.

The pose pilot freezes two original adult characters (Aster and Nera), four
requests (back, sitting, crossed arms, holding a flower), and seeds 101/102: **16
cases per method**, at 832×1216. The sitting request supplies the same garden and
sunset text to every method. Each run records source/model hashes, actual sampling
settings, versions, elapsed time and Torch GPU allocations. Case/reference/scorer
changes make comparisons fail, and reports/baselines are create-only. Identical
seed integers across model architectures do not imply identical latent noise.
All SDXL pilot prompts fit within the 77-token text limit (maximum 72).

The references were selected by the agent from seeds 701–704. They are original
synthetic research images, not assets selected or approved by the creator. The
original generation prompts and seed are recorded. Later look wording is a
manually reviewed fixture description, not automatic acceptance of tagger output.
The two-scale experiment uses a full image and a crop of **the same source**;
it does not demonstrate independent approved views or a coherent character sheet.

An initial probe exposed CLIP's center-crop problem on portrait-shaped full-body
references. The retained method pads the entire image to a white square before
the encoder; tests verify that head and feet remain. Early unpadded/provenance
draft runs are excluded. CCIP scoring separately follows upstream's 384×384
bilinear resize, normalization and learned metric; it does not use the encoder's
padding protocol or substitute cosine similarity.

## Measurement qualification (#180)

CCIP is explicitly a single-character metric. The small checkpoint and b36-24
checkpoint are both pinned with their **matching learned metric ONNX**. Lower
difference means closer identity. The upstream default cutoffs (about 0.1785 and
0.2132 respectively) are source-dataset values, not Studio-calibrated thresholds.
See the [CCIP model card](https://huggingface.co/deepghs/ccip).

The minimal scorer was compared against actual imgutils public APIs, with a
locally seeded private HF cache and Hub offline mode enabled. Maximum absolute
CCIP disagreement was **2.98×10⁻⁸**; WD general/rating probabilities agreed
**exactly** on the two reference images (tolerance 10⁻⁵). The minimal scorer uses
the original SmilingWolf SwinV2 v3 ONNX; parity uses imgutils' separately pinned
embedding-augmented mirror. This establishes numerical parity on these inputs,
not recognition accuracy on the creator's cast. Adapted MIT preprocessing code
retains the [DeepGHS notice](../../runtimes/character_eval/LICENSE.imgutils.txt).

Clothing is a separate confidence-weighted Jaccard measure over an inspectable
garment-tag taxonomy, with probabilities below 0.35 discarded. Missing garment
evidence yields **unknown**, never 1.0. Hair, eye, rating and predicted existing
character names do not contribute. Occlusion, a back view and visible skin versus
sheer tights can change the score without proving a costume change. The tagger
does not establish exact cut, trim, fabric pattern or button placement.

Two concrete misses on the references show why #181 needs creator review:

- The androgynous fixture was requested as an adult boy; the tagger assigns
  `1girl` about **0.981**. It must not overwrite the character's authored identity.
- Aster's `blue_coat` probability is about **0.312**, below the default 0.35
  garment threshold. The generic `coat` survives, so a coarse overlap can miss a
  color error. Lowering the threshold also admits more noise and needs calibration.

Rating probabilities are stored in a separate non-prompt field. The proposed
look workflow admits only reviewed hair/eye/garment tags, applies the existing
typed content policy after underscore normalization, and excludes rating and
copyright-character tags from captions. No content-policy relaxation is involved.
The checkpoint's [official card](https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3/blob/627aef95638667ddcaa3ac8ae625e88ea5b02f51/README.md)
describes tagging validation; those figures are not outfit-match accuracy.

## Methods and interpretation (#182, #185, #186)

The SDXL methods share Animagine XL 4.0, Euler ancestral sampling, 28 requested
steps, guidance 5, dimensions and case seeds. Methods and active parameters are
recorded, including IP scale 0.5, img2img strength 0.7 (fewer actual denoising
steps), and pose ControlNet scale 0.8. Manually drawn skeletons use no OpenPose
detector. They do not encode front-versus-back direction, fingers, or the flower.

`text` uses the full look description without a reference; `ip` omits garment
text; `locked` adds the reviewed fixture's look wording; `multi` adds a second
scale of the same reference; `face` uses **IP-Adapter Plus Face**, not FaceID or
InsightFace; `img2img` adds full-image source pixels; `control` adds the skeleton.
The Plus Face crop can pull the camera into a face/upper-body or overhead shot,
losing the requested full-body framing. More face similarity is not a successful
new pose. The [Diffusers IP-Adapter documentation](https://huggingface.co/docs/diffusers/using-diffusers/ip_adapter)
distinguishes reference embeddings, masks and adapter variants.

The pose-guided method reached **10,740 MiB** of Torch allocation, close to the
12 GB card's practical budget once driver/context overhead is included. Its
inference time was around 16 s per image versus around 11 s for Plus. Torch peak
and device use after inference are named separately; the latter is not a sampled
global VRAM peak. The [ControlNet checkpoint card](https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0)
also notes sensitivity to pose drawing. This pilot uses thick colored skeletons,
but does not establish performance on a production pose editor/detector.

Contact sheets put every output beside its own reference and print both identity
distances and the clothing score underneath. JSON retains per-reference contrast
scores, raw general/rating probabilities, timings and provenance. Manual review
tracks identity, coarse clothes and primary body pose/object separately. Framing
is inspected qualitatively too: the back-view prompt does not explicitly request
a full body, so a crop alone is not counted as a back-pose failure. The other
three requests do include full-body wording, and close crops remain a separate
failure to follow that part of the request.
The agent's judgments were not blinded to scores; any fit is exploratory and
potentially biased. Unknown is retained where visibility is insufficient.

### Fixed-matrix results

Ten methods × 16 cases produced **160 pose candidates**, including the cached
baseline's 16 exact duplicates. An additional 12 control images and six physical
two-person CGs are separate experiments. The GPU was an RTX 5070 Ti Laptop,
12,227 MiB, driver 616.87; host memory was about 31.4 GiB. Environments pin Torch
2.11.0/CUDA 12.8, Diffusers 0.42.1 and ONNX Runtime 1.31.1 independently of Studio.

| Method / evidence sheet | Mean b36 ↓ | Mean garment overlap ↑ | Median render s | Torch peak MiB | Primary pose |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Text](evidence/character-preservation-2026-11-01/text.jpg) | 0.0896 | 0.5532 | 10.961 | 7,349 | 16/16 |
| [IP Plus](evidence/character-preservation-2026-11-01/ip.jpg) | 0.0889 | 0.4829 | 11.383 | 8,184 | 14/16; 1 unknown |
| [Plus + locked wording](evidence/character-preservation-2026-11-01/locked.jpg) | 0.0855 | 0.6421 | 11.172 | 8,184 | 14/16; 1 unknown |
| [Two scales](evidence/character-preservation-2026-11-01/multi.jpg) | 0.0636 | 0.5997 | 11.234 | 8,186 | 14/16 |
| [Plus Face](evidence/character-preservation-2026-11-01/face.jpg) | 0.0744 | 0.5962 | 11.188 | 8,184 | 15/16 |
| [Img2img 0.7](evidence/character-preservation-2026-11-01/img2img.jpg) | 0.0626 | 0.7766 | 8.157 | 8,184 | 0/16 |
| [Img2img 0.95](evidence/character-preservation-2026-11-01/img2img-950.jpg) | 0.0741 | 0.7151 | 10.782 | 8,184 | 12/16 |
| [ControlNet](evidence/character-preservation-2026-11-01/control.jpg) | 0.0931 | 0.6287 | 16.016 | 10,740 | 16/16 |
| [Cached ControlNet](evidence/character-preservation-2026-11-01/control-cached.jpg) | 0.0931 | 0.6287 | 15.859 | 9,178 | 16/16 |
| [Staged klein 4B](evidence/character-preservation-2026-11-01/klein.jpg) | 0.0551 | 0.7655 | 9.562 | 9,569 | 16/16 |

The [machine-readable summary](../../evals/character-preservation/results/pose-summary.json)
pins every score file; adjacent agent reviews define the coarse rubric. Lower
identity distance is not a quality ranking by itself. Text-only generation can
follow poses without preserving the specific person; img2img 0.7 can copy a
standing source while scoring well. Increasing its strength helps movement but
still fails sitting requests. Plus Face also changes framing. Klein generally
keeps full-body framing and visible costume palette, but invents unseen back
details and can alter a braid, coat cut or trim. This easy two-character cast
does not qualify generalization or exact outfit fidelity.

Caching both text encoders' prompt vectors before UNet placement preserves
**all 16 PNG hashes**, while lowering Torch peak from 10,739.9 to 9,177.6 MiB.
Measured device use after rendering falls from 12,190.1 to 10,618.1 MiB; it is
not a continuously sampled device peak. The uncached baseline almost fills the
card. Admission now requires 11 GiB free for cached ControlNet and 11.6 GiB for
the uncached baseline, versus 10 GiB for ordinary SDXL methods. See the
[equivalence receipt](../../evals/character-preservation/results/control-cache-equivalence.json).

Klein uses bf16, four distilled steps, guidance 1, no quantization. Its prompt
encoding phase took 27.406 s and peaked at about 7.80 GiB Torch allocation;
total initialization took 37.719 s. The encoder is then released before the
transformer/VAE. Rendering peaked at 9,569.3 MiB Torch allocation; measured device
use after rendering reached 10,832.1 MiB. Admission requires 11 GiB free GPU and
9 GiB available host RAM. These measured budgets do not justify loading every
model simultaneously or changing the user's running services.

### Negative/outfit controls and provisional calibration

Four [different-face controls](evidence/character-preservation-2026-11-01/controls-negative.jpg)
retain similar hair and clothing colors but add beard/glasses; b36 distances
0.284–0.307 reject these easy negatives. Four intentional outfit requests at
[strength 0.7](evidence/character-preservation-2026-11-01/controls-outfit.jpg)
mostly fail to change the coat. At [0.95](evidence/character-preservation-2026-11-01/controls-outfit-950.jpg)
some trousers/shoes change while the coat remains. These are imperfect
wardrobe controls, not successful new named looks.

Pooled fitting retains **156 unique reference/candidate/crop pairs**, removes 16
cached duplicates, and excludes unknown labels and all multi-person data. The
[agent-only fit](../../evals/character-preservation/results/agent-fit.json) finds
an identity cutoff 0.22750 with TP120/TN4/FP0/FN0 on 124 known labels. This uses
only four negative examples, an easy cast, no held-out split and non-blinded
agent labels; F1 1.0 is **not production accuracy**.

The clothing fit shows why F1 alone is misleading. At confidence 0.35, an overlap
minimum 0.30524 yields F1 0.9466 but TP124/FP14/TN1/FN0: **14 of 15 drifts pass**.
At confidence 0.15 the confusion is TP123/FP10/TN5/FN1; at 0.25 it is
TP121/FP8/TN7/FN3; at 0.5 it is TP124/FP12/TN3/FN0. All thresholds were chosen
on the same labels. None should activate filtering or approval. Finer garment
labels, color/trim checks, more difficult negatives and creator-held-out trials
are required; the current tagger overlap alone is insufficient.

### Two-person references and background context

The separate pair dataset fixes Aster left, Nera right and seeds 101/102. Compare
the [six complete scenes and visual audits](evidence/character-preservation-2026-11-01/pair-comparison.jpg),
not whole-image CCIP. The coarse criterion is exactly two people with intended
hair colors and visible coat/scarf palette; it does not certify fine costumes.

- Production IP Plus child: **0/2** meet that criterion. Seed 101 changes both
  costumes; seed 102 creates three people. Both half-image crops in that scene
  are invalid for single-person identity scoring.
- Klein, two character references: **2/2** meet the coarse criterion. Both have
  two people and retain the main hair/clothing palette. Occluded boots and fine
  back/braid details remain unqualified.
- Klein with the same empty garden as a third reference: **1/2**. Seed 101 turns
  Nera's black hair silver/white. The background reference contains no people.
  Its right-region diagnostic b36 distance is about 0.191, still within the
  upstream cutoff: identity recognition does not certify the approved look.

The [audit](../../evals/character-preservation/results/pair-agent-audit.json)
marks counts and crop validity. Fixed halves can contain crossing limbs and
occlusion; no detector/assignment is qualified and these scores never enter
calibration. Two seeds cannot establish a success rate. This result supports
further two-reference editing tests, not default background-image conditioning
or a claim against the other session's different 7/12 CG dataset.

## LoRA feasibility, not character training (#184)

The resource experiment uses **random tensors only**: zero approved training
images, no saved weights, no style or character quality result. Six backward
passes per resolution use rank 4 (5,806,080 trainable parameters), batch 1, cached
conditioning, gradient checkpointing, fp16 autocast, FP32 trainable parameters and
bitsandbytes AdamW8bit. The VAE and text encoders are absent from the training
phase, as they would be after caching real approved data.

| Square resolution | Torch peak GiB | Device used after GiB | Median steps 2–6 |
| --- | ---: | ---: | ---: |
| 512 | 5.11 | 5.89 | 0.641 s |
| 768 | 5.33 | 6.03 | 0.640 s |
| 1024 | 5.61 | 6.59 | 0.797 s |

This shows a plausible resource budget on the RTX 5070 Ti Laptop (12,227 MiB),
not a measured training duration or required image count. Dataset preparation,
caching, checkpointing, validation and real data variability are excluded. A
linear extrapolation is not a qualified training-time estimate. Actual character
and project-style LoRA training remains conditional on the creator choosing an
approved set. Do not count crops of one image as independent training views.
The [training design](../architecture/character-preservation-research.md#private-loras-184)
specifies 1/4/8/12-image trials, held-out views, caption/trigger ablations,
intentional outfits, two-character checks and private fenced artifacts.
The [Diffusers LoRA guide](https://huggingface.co/docs/diffusers/training/lora)
supports training only adapter parameters; its example timings are not ours.

## Licenses and larger editing candidates

Public full model manifests retain exact commit/file hashes under
`evals/character-preservation/model-manifests`. License declarations are checked
separately from byte integrity; no weights ship in games.

| Component | License / adoption consequence |
| --- | --- |
| CCIP weights | Repositories declare generic `openrail` without an exact variant/license text. **Unresolved for production**; the research manifest says `openrail-unspecified`. Do not label it OpenRAIL++-M by inference. |
| imgutils code | MIT; notice retained. Code rights do not resolve model rights. |
| WD SwinV2 v3 and its embedding mirror | Apache-2.0 declarations, separately pinned. |
| Animagine XL 4.0 | CreativeML Open RAIL++-M, including use restrictions and derivative/distribution duties. A future LoRA must retain the base terms, notices and modification record. |
| IP-Adapter Plus / Plus Face | Apache-2.0 adapter declaration/code; the LAION OpenCLIP ViT-H upstream declares MIT. Plus Face here does not use InsightFace weights. |
| Xinsir pose ControlNet | Apache-2.0 declaration; preserve the SDXL base obligations too. No CMU OpenPose detector/code is installed by this experiment. |
| Person detection | Not used. The anime detector's MIT metadata alone is insufficient to qualify its YOLO training/code/dataset chain; automatic per-person Studio scoring stays unqualified. |
| Diffusers / PEFT / Transformers / Accelerate | Apache-2.0; pinned independent runtime. |
| bitsandbytes / ONNX Runtime | MIT. Torch is BSD-3-Clause; NumPy, Pillow, psutil and NVIDIA bindings retain their own notices. |
| Qwen-Image-Edit | Apache-2.0, pinned source review; standard weights exceed this machine's memory budget, so no unquantized execution claim. A separately pinned quantized/offloaded artifact needs measurement. |
| FLUX.1 Kontext dev | Model/derivative use is noncommercial/nonproduction under v1.1.1. Outputs may be commercial with the license's conditions; this does not authorize a commercial Studio deployment of the model. No acceptance/download is performed for the user. |
| FLUX.2 klein 4B | Apache-2.0 at the pinned checkpoint, with a separate encoder-release experiment; this does not generalize to every FLUX family checkpoint. |

Primary terms: [Animagine card](https://huggingface.co/cagliostrolab/animagine-xl-4.0),
[SDXL license](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md),
[IP-Adapter license](https://github.com/tencent-ailab/IP-Adapter/blob/main/LICENSE),
[LAION encoder card](https://huggingface.co/laion/CLIP-ViT-H-14-laion2B-s32B-b79K),
[Qwen card](https://huggingface.co/Qwen/Qwen-Image-Edit/blob/ac7f9318f633fc4b5778c59367c8128225f1e3de/README.md),
[Kontext license](https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev/blob/24e9dedc4ef646698dc8eb4e18ae2cec3c9fea0d/LICENSE.md),
[klein card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B).
Kontext's output conditions include review/filtering, applicable disclosure and a
restriction on training competitive models from its outputs. Commercial output
permission and commercial model deployment are distinct questions.

At the reviewed commits, selected standard safetensors total about **53.7 GiB**
for Qwen-Image-Edit (transformer/text encoder/VAE), **31.4 GiB** for Kontext,
and **14.9 GiB** for klein. These are disk byte sums, **not measured minimum
VRAM**. Staging, quantization and offload can change requirements; no vendor
hardware claim is substituted for a local measured run.

## What remains open

This delivery must not close all seven issues. Creator calibration and a
creator-selected approved training set are absent. Named-look persistence/UI,
production advisory flags/ranking, independent multi-view/sheet experiments,
qualified person detection/assignment, regional text/background conditioning,
actual character/style LoRA quality, and the creator's final pose choice remain
explicit follow-up qualification. The architecture document defines those
interfaces without inventing delivered Studio behavior.

Current expressions already use a bounded face repaint of the approved sprite;
this pilot does not replace that shipped behavior. Current two-person CG work's
reported 7/12 baseline remains its own dataset, not a head-to-head score against
these original fixtures. Unknown scores never hide a candidate or block approval.

## Verification and exact commands

All commands below ran from `C:\Projects\flint-graph-codex-character-research`.
Dependencies were prepared with `uv sync --all-groups`, `npm --prefix frontend ci`,
and the two isolated `uv sync --project` commands in the bench README. Tests were
added and observed failing before implementation at each new behavior seam;
the retained focused set covers unknown garments, pin/coverage mismatch,
conflicting pooled reviews, duplicate pairs, incomplete reports, reference
padding, editing prompts, finite strengths and memory admission.

The required repository gates passed before the first commit:

```powershell
uv run pytest -q --tb=short
uv run ruff check .
uv run mypy
$env:FLINT_GRAPH_ENV='test'
uv run alembic upgrade head --sql
docker compose config
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

Results: **1,920 passed / 120 skipped**, Ruff clean, mypy 267 files clean,
offline SQL and Compose validation passed, frontend **116 passed**, types/build
passed, and the deterministic Acme evaluation passed. Live/externally provisioned
tests remain opt-in in the default suite; it does not imply live service coverage.

Real pinned engine and preview qualification passed with **33 passed / 1 skipped**:

```powershell
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
```

The skipped extra gate requires a prepared CG builder release image. No runtime
or export change is made here, so no builder was prepared or release built for
this research task. Real engine conformance/import/playback did run.

PostgreSQL tests used only the task-owned `flint-codex-prompt-pg-final` container,
loopback port 6192, with a fresh random database per invocation. The private
wrapper supplies credentials without printing them, upgrades head, downgrades
0033 to 0032, upgrades again, then drops only its own database. **131 passed**:

```powershell
uv run python notes/run-research-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py -q --tb=short
```

A separate one-test source audit confirmed that wrapper imports resolve to this
worktree, not the previous migration worktree. Owned Studio services and real
projects were untouched. No shared container was restarted.

Additional actual research checks passed:

```powershell
uv run pytest tests/unit/test_character_bench.py tests/unit/test_character_bench_report.py tests/unit/test_character_calibration_cli.py -q
runtimes/character_lab/.venv/Scripts/python.exe -m unittest discover -s runtimes/character_lab -p test_*.py
$env:FLINT_GRAPH_CHARACTER_EVAL_MODELS=(Resolve-Path notes/models).Path
uv run pytest tests/integration/test_character_eval_live.py -q
runtimes/character_eval/.venv/Scripts/python.exe runtimes/character_eval/parity.py --dataset evals/character-preservation/pilot-v1/dataset.json --models notes/models --cache notes/hf-parity-v1 --out notes/research/imgutils-parity.json
$env:FLINT_GRAPH_CHARACTER_GPU_MODELS='C:/Projects/flint-graph/notes/models'
$env:FLINT_GRAPH_CHARACTER_CACHED_OUTPUT=(Join-Path (Get-Location) 'notes/research/padded-v1/runs/control-cached')
uv run pytest tests/integration/test_character_cached_control_live.py -q --tb=short
```

These yielded 13 root unit tests, eight isolated lab tests, one real CPU test,
real imgutils parity and one complete 16-image cached GPU resource test. Output
paths are create-only; reruns need new paths. Each ten-method GPU run and the
control/pair/memory experiments also completed with the commands and parameters
recorded in the bench README and retained score/run manifests. Fresh threshold
fits can be reproduced from committed score/review/dataset files without weights.
Cryptographically pinned JSON bytes are preserved by scoped Git attributes;
scorer source is LF on every checkout. Model weights, private notes and secrets
are excluded from the commit.
