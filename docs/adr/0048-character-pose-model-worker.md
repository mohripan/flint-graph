# ADR 0048: Character pose generation through a pinned editing model

Date: 2026-11-01. Status: accepted; implementation authorized by the creator.

## Decision

Deliver a Studio pose feature using FLUX.2 klein 4B, selected in ADR 0046. This
implements the model path rather than adding another comparison experiment.
Start from an explicitly selected immutable reviewed look, a pose instruction,
one to four fixed seeds and an optional transparent sprite output. Results are
candidates for creator approval and normal stage binding, never auto-approved.

Reuse the image-job ledger, workspace admission limits, IDs-only Temporal
supervision, execution fences, cancellation, progress and immutable image storage.
A pose-plan sidecar pins operation, source/look snapshot and exact model manifest.
The ledger's existing full-body character-render purpose also carries these
renders; the pose API/UI explicitly identifies the operation. Original portrait,
expression and CG generation remain on their existing model path.

Route pose plans to a distinct opt-in worker/task queue. Shared image relay and
recovery selection filter by pose-plan presence, so the ordinary generator never
claims a pose job and cancellation reaches the correct registered run. Use the
existing workflow/activities' contracts and fenced publication; pose activities
load the verified reference bytes and use the pinned editing generator.

The isolated pose child has its own dependency lock, verifies model files against
the admitted manifest, runs offline and stages text encoding separately from
transformer/VAE rendering on the 12 GB GPU. Each stage loads directly onto CUDA
with low CPU memory loading, avoiding a full CPU weight copy. Admission requires
11 GiB dedicated GPU and 6 GiB available host RAM for this path; these checks
observe availability and do not reserve it across workers. Busy resources retry
within the job's existing attempt/deadline bounds. It never unloads another model or switches the
requested method. Transparent output uses the separately pinned existing anime
segmenter; its code/model identities are recorded. No new ML dependency enters
the API environment. Model weights and references remain private Studio inputs.

The prompt is a versioned catalog entry. Current content-policy validation applies
to creator pose text and reviewed tags; model-specific conditioning is explicit.
Klein has no SDXL-style negative conditioning: blocked input terms are checked,
while the policy's negative tags are not silently presented as applied.
The child rejects an over-budget token sequence instead of silently truncating it.
Look, prompt bundle, source, seeds and model identity stay fixed across retries.

## Boundaries

No new game format, save or runtime version is needed. Approved PNG assets use
the ordinary release binding/NOTICES path; private model weights never ship.
Identity and clothing fidelity still require review. Fine-tuning can be integrated
with explicitly selected approved training data; this feature does not fabricate
a trained character LoRA or claim unseen back-view details are known. Existing
face-only expression repainting remains the expression workflow.

The upstream [model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
and [license](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/blob/main/LICENSE.md)
identify the 4B weights as Apache-2.0. Pin the measured revision
`e7b7dc27f91deacad38e78976d1f2b499d76a294`; verify the installed manifest and
individual files, not a moving branch name. Do not substitute Kontext or 9B
weights under this model identity.

See [delivery and qualification](../reports/2026-11-01-character-poses.md).
