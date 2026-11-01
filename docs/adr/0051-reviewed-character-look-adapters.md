# ADR 0051: Private adapters for a reviewed character look

Date: 2026-11-02. Status: accepted and implemented following the creator's
autonomous continuation of character-model development (#184).

Extend ADR 0050's private training/selection path with an explicit reviewed-look
target. A member chooses 4–12 approved, same-character/outfit images, including
the locked base, reviews their captions, and confirms training rights and the
same look. Approved unassigned uploads require the same explicit confirmation.
Foreign characters, scene CGs, missing/discarded bases and other workspace/project
resources are refused. The frozen dataset includes the look hash; a scoped sidecar
holds the immutable reviewed-look snapshot and foreign keys (migration 0038).

Reuse the existing rank-4 klein trainer, fenced ledger, exact-run registration,
private safetensors store and bounded MLflow mirror. Project-style requests and
old hashes remain valid. This trains the actual current pose renderer; it does not
claim the original Animagine research acceptance or cross-model compatibility.

Pose admission and each training/render retry check that a character adapter
belongs to this exact character/look/base. Selecting a different outfit/look never
silently reuses its weights. Existing project-style versions remain selectable.
The pose renderer continues to load one explicitly selected trained version and
strength. Independent adapter stacking is outside this delivery.

Characters offers training from the selected reviewed look, with reviewed-look
tags as editable caption suggestions, explicit source/caption/confirmation review,
progress/cancel, frozen target disclosure, and compatible version selection.
MLflow separates character-look and project-style runs with an allowlisted kind;
images, captions, names, prompts and weights remain private and outside telemetry.

Qualify through public admission/selection, scope/replay/fence/retry behavior and
real training, private publication, MLflow, pose rendering and browser controls on
an explicitly selected synthetic QA dataset. Do not touch creator projects, claim
creator ratings, or equate loss with identity/outfit/style/lighting accuracy.
Character adapters remain optional; candidate review remains manual.
