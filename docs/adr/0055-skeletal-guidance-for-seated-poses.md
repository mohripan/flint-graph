# ADR 0055: Skeletal guidance for seated poses

2026-11-02. Implemented under the creator's autonomous model work
(#182/#185). The same fixed seed/reference/stored prompt reproduced the reported
missing leg before segmentation. Identity and style adapters alone do not specify
body geometry. Keep this image as an anatomy failure, never a training positive.

Extend the existing pose path with an optional `seated-front-v1` body guide. It
provides a complete COCO-18 skeleton, with separate hip/knee/ankle chains, through
the pinned Apache-2.0 xocialize RefControl 4B pose adapter. This is a structural
condition, not an anatomy detector or guarantee. The no-guide path is unchanged.

Freeze guide coordinates/version/hash and the public adapter manifest in a scoped
sidecar (migration 0042). Keep the approved character look and optional private
character/style versions. A body guide replaces the supplemental character view
so inference has two inputs: skeleton first, approved appearance second. The UI
shows the selected/frozen guide, and new jobs disclose it in history/provenance.
New settings default off. API and pose worker must deploy together.

Closed child protocol 6 transfers verified public weights under a fixed private
filename and a bounded guide description. Render the guide with the isolated
Pillow dependency, fit the approved appearance reference within 512 square, load
the named pose adapter alongside existing private adapters, and retain the pinned
four-step base recipe and GPU/host floors. No weights enter ordinary assets/games. The deployed guide version freezes its
0.8 strength and preprocessing as well as its coordinates.
Carry third-party source/license attribution into generated notices, including
subsequent local repairs of a guided source. Repair preserves its existing pixel
contract and need not rerun the structural condition.

Keep instructions in the reviewed prompt catalog. Retain old prompt bundles and
frozen jobs. Add a dedicated versioned pose-control entry for explicit skeleton/appearance
roles; keep existing character-detail entries unchanged. No image
content-policy relaxation or game runtime change.

Tests precede behavior at admission/replay/scope, worker pin/frozen input transfer,
strict protocol and guide rendering boundaries. Real fixed-seed seated cases must
show both legs/boots; record all outputs, appearance/style limits and actual memory.
Qualify the UI, full Python/PostgreSQL/frontend/Godot gates and live Studio rollout.

Measured outcomes and limits: [delivery report](../reports/2026-11-02-seated-pose-guidance.md).

## Standing and walking presets

The same protocol and qualified public adapter also accept `standing-front-v1`
and `walking-three-quarter-v1`. Each has immutable, complete COCO-18 geometry,
independent of the unchanged seated guide. Capabilities advertise editable pose
context separately from frozen guide data; selecting a guide fills that context.
This extends the preset catalog without a migration, new prompt, runtime bump or
model change. Deploy the API and child together, since older children reject the
new identifiers. [Qualification](../reports/2026-11-02-standing-and-walking-guides.md).
