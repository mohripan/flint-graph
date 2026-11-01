# ADR 0047: Reviewed character looks and advisory candidate feedback

Date: 2026-11-01. Status: Accepted; first Studio integration of #181/#183.

## Context

[ADR 0046](0046-character-preservation-measurement-and-pose-direction.md) separates
identity, visible clothes and following the requested pose. Its agent-only pilot
does not qualify automatic approval thresholds. CCIP's exact weight license also
remains unresolved. Creators can nevertheless review and reuse a named look now.

## Decision

Store immutable looks as private editor metadata, separate from story revisions.
A look pins a project/character, an approved reference's ID and SHA-256, reviewed
trait/clothing tags, authored character type, reviewer, optional parent and
tagger observation, and review-time prompt bundle/policy hashes. Changing an
outfit creates another named record. Selecting a default has its own optimistic
version. A retried creation does not reselect an earlier look.

Use explicit look-aware admission endpoints for Studio portraits, expressions
and CGs. Delegate resource admission, outbox writes and execution to the existing
image pipeline, then pin complete look snapshots in the same transaction.
Expressions use the approved source pixels; CGs use the approved reference and
reviewed description; ordinary portraits use the reviewed words. This does not
guarantee identity or exact clothes. No new pose model or LoRA mode is introduced.

Serialize admission in the existing workspace/project lock order. Include the
look in idempotency, refuse cross-use of legacy request keys, and replay the
original recipe after a default changes. Preserve the image-worker protocol and
owned generator code. Original APIs remain available; assistant integration is
separate work.

An optional isolated WD14 CPU child proposes tags from verified image bytes.
The creator edits them before locking. Only visible-trait/garment allowlists
enter suggestions; rating, predicted gender and existing-character tags never
become descriptions. Apply the current typed image policy to normalized creator
tags too. Retain raw observations/model/code hashes privately. The child opens
no CCIP weights, downloads nothing and uses no GPU. Missing/invalid installation
leaves manual look entry available.

Show reference and candidate together. Save separate manual character/clothes
feedback with version and actor; show its warnings on cards. Optional garment-tag
overlap is uncalibrated, with explicit unknowns and no identity result or automatic
verdict. Known CGs receive no per-person score without qualified crops. Never
hide, discard or revoke approval because of feedback or a score. Signal bounded
feedback-list truncation/failure instead of implying that no warnings exist.

## Consequences

Migration 0034 adds scoped looks, selection, job snapshot, manual feedback and
observation tables. Existing projects need no backfill and have no selected look.
No story-format, runtime-version, save or game-export change is needed. Private
metadata and weights never ship; ordinary artwork still exports through authored
asset bindings. References must be reviewed by the creator; no detector is claimed.

Multi-view looks, coherent sheets, CCIP production use, calibration, ranking/best-N,
the staged klein pose worker and actual character/style LoRAs remain separate
work. See the [report](../reports/2026-11-01-reviewed-character-looks.md).
