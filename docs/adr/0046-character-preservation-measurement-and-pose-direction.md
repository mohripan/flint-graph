# ADR 0046: Character preservation measurement and pose direction

Date: 2026-11-01

Status: Accepted for research direction; production integration remains proposed.

## Context

M40 #180–#186 asks for character and clothing preservation across poses and CGs
on a 12 GB GPU. Identity, costume fidelity and following the requested pose are
separate outcomes. The fixed original-fixture bench measures 160 pose candidates,
12 control images and six two-person scenes. Reviews are agent judgments, not
creator approval. See the [report](../reports/2026-11-01-character-preservation.md).

## Decision

Use the isolated, versioned bench to qualify changes before Studio integration.
Retain CCIP's matching learned metric and a separate garment-tag overlap; keep
unknowns explicit. Resolve the CCIP weights' exact license and calibrate against
creator labels on held-out characters before production use. Neither identity
distance nor garment overlap certifies an approved look or controls approval.

Take staged **FLUX.2 klein 4B** forward as the first pose-feature candidate. It
followed 16/16 primary pose requests with the strongest mean identity distance
in this small pilot. Release the text encoder before loading the transformer;
measure memory and keep model-specific instructions and precision pinned. This
is a direction for the next implementation, not a shipped default or a claim
about unseen characters. Back-view details require approved independent views.

Keep cached-text SDXL ControlNet as an explicitly chosen alternative. Its 16
images exactly match the uncached baseline while reducing Torch peak by about
1,562 MiB. A busy GPU queues or refuses work; it must not silently change models
or unload another program. Existing face-repaint expressions remain unchanged.

Test two-reference klein CGs further before adoption. Do not default to adding a
background as a third reference: one of two such scenes changed a character's
hair color. Per-person scoring needs count, crop and assignment qualification.

Named reviewed looks, private LoRA jobs and optional advisory candidate flags
follow the [integration design](../architecture/character-preservation-research.md).
Train only on creator-selected approved images; the random-tensor memory probe
is not character/style training. Private weights never enter exported games.

## Consequences

The bench, pinned environments, reviews and evidence are reviewable now. No
database migration, worker rollout, Studio UI change or runtime bump occurs.
All seven issues retain explicit follow-up work. Fine outfit details, coherent
character sheets, regional text, creator calibration, actual LoRA quality and
commercial model-license qualification remain necessary before product claims.
