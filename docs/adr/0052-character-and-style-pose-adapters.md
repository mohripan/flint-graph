# ADR 0052: Combine character and project-style adapters in poses

Date: 2026-11-02. Status: accepted and implemented under the creator's
autonomous continuation of character-model development (#184, #185).

ADR 0051 trains an exact reviewed character look. ADR 0050 trains a project style.
Creators need both selections in one pose to influence identity/outfit and
linework/palette together. Neither one certifies anatomy or identical lighting.

Keep the current optional `style_adapter` and its existing request hashes,
bindings and protocols 1–3. Add an optional `character_adapter` with an explicitly
typed reviewed-look target. Migration 0039 adds a private sidecar holding its
version, weight hash and strength, with scoped project/workspace foreign keys and
a foreign key to an actual character-training target. The character version must
match the exact character, immutable look and approved base. Both versions must
be completed in this project and use the installed base-model manifest. Replays
return the admitted job even if the operator subsequently disables new admission.

When `character_adapter` is present, `style_adapter` must be a project style.
Duplicate versions, wrong roles, foreign resources and incompatible models/looks
are refused. Strengths are each 0.1–1 and their sum may not exceed 1. This initial
bound limits combined influence; it is not a measured optimum or a universal
quality guarantee. Existing single selections keep their old semantics.

The isolated pose child gains closed protocol 4: one character adapter followed
by an optional project style, fixed local filenames, weight/dataset/recipe hashes
and strengths. The worker and parent verify private safetensors against the
frozen base and training metadata; the child verifies file hashes before loading
ML libraries. Diffusers/PEFT loads named adapters and applies their individual
weights. Provenance records both roles and hashes. No weights become ordinary
assets, telemetry artifacts, public downloads or game-package content.

`NARRATIVE_POSE_MAX_ADAPTERS=2` opts a coordinated API/pose-worker deployment into
the new selection; the default stays one. New Studio controls use the capability,
offer only this exact trained character look, and keep the old chooser against
older/default APIs. Both choices, strengths and idempotency identity are frozen
when Generate is pressed. Results disclose the selections used.

Qualify through API admission/replay/scope and worker execution, child protocol
and private transfer tests, frontend request tests and real browser/GPU rendering
on synthetic task-owned projects. Preserve running creator Studios. A combined
render establishes operability and memory use; quality comparisons still require
creator-reviewed identity, outfit, anatomy, style and lighting labels.
