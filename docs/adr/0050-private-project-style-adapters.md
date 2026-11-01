# ADR 0050: Private project-style adapters with optional MLflow tracking

Date: 2026-11-02. Status: accepted and implemented as a slice of #184, following
the creator's model-development instruction and request to consider MLflow.

## Decision

Train a project rendering-style LoRA from 4–12 approved images explicitly chosen
by the creator, with reviewed content captions and a training-rights confirmation.
Do not select a creator's real projects or datasets automatically. Qualification
uses a separate synthetic QA project and records agent review separately.

Target the exact installed FLUX.2 klein 4B pose renderer. Adapters are specific to
the base-model manifest; an Animagine/SDXL adapter cannot be presented as compatible
with the klein pose path. This adopts the current renderer for product integration,
while #184's Animagine/character/style comparative work remains separate.

A separate opt-in Temporal worker performs bounded rank-4 LoRA training with cached
text/latents, bf16 frozen weights, FP32 trainable parameters, gradient checkpointing,
8-bit Adam and batch one. Use aspect-ratio-based 32-pixel buckets bounded by
512² pixels and a 768-pixel side. No pickled checkpoints, external uploads, remote
code or implicit model switching. Busy resources retry within fixed bounds.

PostgreSQL owns a dedicated fenced training ledger, frozen dataset/captions,
recipe/base hashes, registered run, cancellation and published adapter metadata.
Private create-only safetensors live outside ordinary asset/release paths. Selected
versions/strength and weight/base/dataset hashes are pinned into pose admissions;
retries reuse that selection. Existing poses with no adapter remain valid. Weights,
training images/captions and private storage keys never enter game packages.

Studio offers explicit training-set/caption review, progress/cancel, immutable
versions and a per-pose adapter selector. A completed run means weights trained
successfully, not that style/lighting accuracy is proven. Approval of generated
candidates remains manual; source choices and training loss are not quality scores.

MLflow is optional experiment tracking, via bounded REST calls from the worker.
Mirror numeric losses/resource measurements and opaque IDs/hashes/recipe values;
never autolog images, captions, prompts, credentials, model weights or filesystem
paths. PostgreSQL/private storage remain authoritative. Tracking failure never
fails training or controls which adapter is active. A separately pinned local
MLflow installation may serve a loopback UI; production auth/storage remain an
operator deployment concern. Existing OTel/Langfuse ownership is unchanged.

## Qualification

Test authenticated admission/scopes, rights/approval/caption checks, immutable
replay, dispatch registration, stale attempts/cancel/recovery, strict safetensors
publication, adapter pinning/application and fail-open tracking before changing
behavior. Then run real GPU training and adapter-backed pose generation on chosen
QA images, real Temporal/PostgreSQL/MinIO, optional real MLflow and browser flows.
Record memory/time and honest held-out style/identity observations. Do not claim
lighting or style locked merely because weights were saved or loss decreased.
