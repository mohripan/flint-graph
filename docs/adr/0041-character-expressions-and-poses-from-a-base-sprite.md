# ADR 0041: Character expressions and poses from a base sprite

Date: 2026-10-31. Status: accepted. Slices A (expressions) and C (scene art) are
implemented; slice B (poses) is planned. Design: [expressions and poses](../superpowers/specs/2026-10-31-character-expressions-and-poses-design.md).

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
5. **Scene art (slice C)** makes event CGs: a 1344×768 text-to-image scene from a
   description, with one approved image of each of one or two characters as the
   IP-Adapter Plus (ViT-H) identity reference at scale 0.5, no cutout. With two,
   attention masks give the first reference the left half and the second the right. The image encoder runs once
   before SDXL moves to the GPU and is released, so the peak stays at 8.0 GiB. The
   scene description and the character's own description pass the image content
   policy. Results are candidate library images (`scene_art` jobs, asked for from
   Assets → CGs) for the CG layer of ADR 0042; scene art does not change the story
   format or runtime. It was built before slice B and adds the IP-Adapter pin that
   poses will reuse.

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
  so every result is a reviewed candidate. Two-character CGs are experimental: on 12
  fixed seeds (101–112) 7 keep both looks; the rest swap hair or clothes because the
  tags in one prompt bind to the wrong person. Regional prompting fused the two into
  one figure, and repainting each half did not raise the rate, so neither is used.
  The Studio labels them experimental and starts eight candidates instead of four.
  That 7 of 12 is the baseline M40 (#185, scored with CCIP #180) owns improving; the
  report lists it per seed.
- Migration 0026 adds the base, box, strength, expressions and per-image prompts to
  image jobs, with checks that bind them to the new purpose. Migration 0030 adds the
  scene-art references (a checked JSON list, since library assets are never deleted),
  the adapter scale and the adapter that ran.
