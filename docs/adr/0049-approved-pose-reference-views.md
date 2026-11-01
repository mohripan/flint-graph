# ADR 0049: Additional approved views for character poses

Date: 2026-11-01. Status: implementation authorized by the creator's continuation
of the character-preservation model work (#185).

Extend the existing pose pipeline with one optional additional approved image of
the same character and reviewed outfit. The creator explicitly selects it and
labels its view (front, side, back or detail). The locked look remains the primary
identity/outfit reference. This delivers two-image conditioning through the pinned
klein model; it does not create a second character or silently change the outfit.
A character sheet can be uploaded as a reviewed reference; this slice does not
claim to generate a coherent turnaround automatically.

Freeze ordered asset IDs, source hashes, sizes, view labels and names at admission
in a project/workspace-scoped pose-reference table. Replays retain that snapshot;
changed selections under one idempotency key conflict. Existing single-reference
request hashes and queued jobs remain valid. The worker verifies both sources and
records a reference-manifest hash in candidate provenance. Nothing enters story
format/saves or exports beyond the ordinary approved result PNG.

Use a new catalog entry for the two-view instruction, retaining the single-view
entry byte-for-byte. Child protocol 2 carries two bounded reference hashes and
fixed private filenames; protocol 1 remains accepted for existing workers/jobs.
The additional view is reduced to fit 512×512 before encoding, while the primary
keeps its original qualified preprocessing. Pin and record this preprocessing.
Do not replace or unload another model when resources are busy.

Operator configuration defaults to one reference until the two-view path is
qualified on the installed GPU. A capability field controls the Studio picker;
rollout deploys the additive migration and compatible child/worker before enabling
two-reference admission. Old workers continue to send protocol 1 to the compatible
child. No runtime/build/preview bump is necessary.

The Studio shows the primary alongside approved candidate views, requires an
explicit same-look confirmation, preserves a fixed order and displays the frozen
references with each result. Approval/manual comparison remains the creator's
choice. Extra context may still drift; no identity guarantee or trained LoRA is
claimed. CG/audio/assistant-owned code remains outside this change.

The upstream [Diffusers pipeline documentation](https://huggingface.co/docs/diffusers/en/api/pipelines/flux2)
and installed 0.42.1 source expose a list of reference images to a single edited
result. Qualification must run that exact installed path, including real GPU,
Temporal/MinIO, browser review and the existing regression gates.

See [qualification and remaining rendering limits](../reports/2026-11-01-pose-reference-views.md).
