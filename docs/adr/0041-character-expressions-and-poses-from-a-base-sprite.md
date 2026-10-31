# ADR 0041: Character expressions and poses from a base sprite

Date: 2026-10-31. Status: accepted. Slice A (expressions) is implemented; slices B
(poses) and C (scene art) are planned. Design: [expressions and poses](../superpowers/specs/2026-10-31-character-expressions-and-poses-design.md).

## Context

Story format 2 (ADR 0040) shows characters on stage with one sprite per expression.
Text-to-image generation (ADR 0039) draws a different person for every prompt, so a
character's expressions never match. The user asked for consistent characters: the
same body and hair, different expressions, and sometimes different poses.

## Decision

1. **Expressions repaint only the face of an approved base sprite.** The local child
   inpaints a feathered ellipse over a creator-adjustable face box, at 2.4× context
   and 1024 px, with the same pinned Animagine XL 4.0 weights. It pastes the result
   back and restores the base alpha. Everything outside the face, and the image size,
   stays identical, so expressions swap on stage without jitter. Strength is 0.9;
   prompts come from the character's appearance tags plus expression tags, built and
   recorded by the server.
2. **Expression jobs are image jobs** (`character_expression`). They use the same
   outbox, fenced Temporal activity, isolated child, hash-checked storage and
   candidate review as portraits. The base bytes reach the child from the store,
   hash-verified, and the child checks the hash again. Results are candidates; the
   Studio approves one and sets it as that expression's sprite in the draft.
3. **Poses (slice B)** will use ControlNet OpenPose SDXL with preset skeletons, plus
   IP-Adapter Plus (ViT-H) with the base sprite as identity reference, CPU offload,
   and the anime-seg cutout. Both models are Apache-2.0 and pinned by manifest like
   the others.
4. **No face detector.** The Studio proposes a face box from the sprite's alpha, and
   the creator adjusts it.
5. **Scene art (slice C, after B)** makes event CGs: a 1344×768 text-to-image scene
   from a description, with one approved image of the character as the IP-Adapter
   identity reference (the same pinned models as poses), no cutout. The scene
   description passes the image content policy like every other description. Results are
   candidate library images (`scene_art` jobs) for the CG layer that the player adds
   separately; scene art does not change the story format or runtime.

## Consequences

- An expression job needs a base sprite; the first sprite still comes from portrait
  or sprite generation, or an upload.
- Inpainting can drift hair colour inside the mask at high strength. The mask stays
  on the face, and the strength is fixed at 0.9: at 0.85 mouths kept the base's
  smile, and at 0.95 hair drifted. A smiling base can still leave a smile on sad and
  surprised.
- Free-text expressions are tags, so the quality of uncommon ones varies; presets
  carry tested tag sets.
- Poses and scene art keep identity only approximately (outfit details can change),
  so every result is a reviewed candidate. Scene art shows one referenced character
  per image.
- Migration 0026 adds the base, box, strength, expressions and per-image prompts to
  image jobs, with checks that bind them to the new purpose.
