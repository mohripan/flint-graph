# ADR 0054: Region repairs for pose candidates

Date: 2026-11-02. Status: implemented under the creator's autonomous
continuation of character-model development (#182/#185).

Add a local repair action to an existing pose candidate. The creator selects one
rectangle, describes the correction and requests one or two new candidates. Keep
the source unchanged. A source can be an unapproved or approved available pose
image in this project/character; the frozen reviewed look must still be approved.
An anatomy failure does not prevent repair, and no repair is automatically approved.

Freeze the source asset/hash/size/canvas, selected rectangle and instruction in a
scoped sidecar (migration 0041). Inherit the original pose's exact character/style
adapter versions, hashes and strengths. Reuse the existing pose supervisor,
quotas, cancellation, registered Temporal run and private input/weight loading.
Requests and retries check scope, source availability and model/weight pins;
idempotent replays retain the originally admitted job.

Use the pinned klein editor with the target image first and its approved look as
the detail reference. Reuse the reviewed `narrative.image.pose_views` template;
the correction remains creator-supplied data. No new fixed prompt or policy change.
This is reference editing plus bounded compositing, not a mask-native diffusion
model. The selected area guides which generated pixels are retained.

Closed child protocol 5 adds source-native dimensions/crop, a rectangle and fixed
eight-pixel inward feathering, with the existing verified references and optional
adapters. A rectangle is at least 16 pixels per side, inside the source, and at
most a quarter of its area. Reconstruct transparent source crops on their original
768×1152 canvas for inference. Restore the source's exact native dimensions/crop;
preserve its RGB/RGBA pixels outside the rectangle, including transparency.
Segment generated transparent repairs with the pinned cutout model before copying
the patch. Record source/region/canvas and preservation provenance.

The parent independently decodes the bounded 8-bit RGB/RGBA pose PNGs and rejects
any output that changed an outside pixel, dimensions, channels or crop. Existing
protocols 1–4 remain unchanged. New `NARRATIVE_POSE_REPAIRS_ENABLED` defaults off;
coordinate API/pose-worker rollout with two-reference support before enabling it.
Nothing changes story packages, saves, game runtimes or existing assets.

The Studio uses its existing modal, image controls and visual language, with drag
selection, keyboard movement/resizing and numeric adjustments. Results disclose
the repaired source and region. Manual comparison still checks the patch: a model
can miss the correction or make a visible seam. Qualify API/replay/scope/fences,
strict protocol, independent pixel preservation and browser controls, plus real
opaque and transparent GPU repairs on task-owned synthetic fixtures.

Qualification and limits: [delivery report](../reports/2026-11-02-pose-region-repairs.md).
