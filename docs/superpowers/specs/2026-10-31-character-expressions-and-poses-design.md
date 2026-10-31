# Character expressions and poses from one base sprite

Date: 2026-10-31. Tracks #170 (character art) on top of ADR 0039 (local generation)
and ADR 0040 (stage and sprites). Decision record: [ADR 0041](../../adr/0041-character-expressions-and-poses-from-a-base-sprite.md).

## Goal

A visual novel character needs the same body, outfit and hair in every sprite, with
different faces (expressions) and sometimes different poses. Generating each sprite
from text gives a different person every time. This design derives new sprites from
one approved base sprite instead:

- **Expressions (slice A):** repaint only the face; everything else stays identical.
- **Poses (slice B):** redraw the figure in a new pose, keeping identity through the
  base image.
- **Scene art (slice C):** a full 16:9 event illustration of the character in a
  described scene, keeping identity through the same reference, for the CG layer
  another branch adds to the player.

## Feasibility (2026-10-31, RTX 12 GB, Animagine XL 4.0)

A scratch test on a transparent 808×1212 sprite:

- **Method.** Crop a square around the face, about 2.4× the face box, from the sprite
  composited on white (padded with white past the edges). Upscale it to 1024. Inpaint
  a feathered ellipse over the face with `StableDiffusionXLInpaintPipeline`, loaded
  from the same Animagine weights (a 4-channel UNet, so masked img2img). Downscale,
  paste back, and restore the base alpha.
- **Speed and memory.** About 10 s per expression, peaking at 7.7 GB.
- **Strength.** At 0.7 the face barely changes. At 0.85 the scratch test read well,
  but the first real worker run kept the base's smile on sad and surprised. At 0.9
  happy and angry read clearly and every expression changes its eyes and brows,
  with slight hair drift at the mask edge. At 0.95 the hair inside the mask drifts
  in colour. Default: 0.9. The mouth is the weakest part: on a smiling base, sad and
  often surprised keep a closed-mouth smile (one 0.9 run opened surprised's mouth,
  a later one did not).
- **Result.** Hair, outfit, body and silhouette stay pixel-identical outside the
  face, and the output keeps the base's exact size and alpha. Expressions therefore
  swap on stage without the figure jumping.

## Slice A: expressions

### Request

`POST /v1/narrative/projects/{project}/characters/{character}/expression-jobs`:

```json
{"base_asset_id": "…", "face_box": [350, 40, 480, 170],
 "expressions": ["happy", "angry", "fond of tea"], "idempotency_key": "…"}
```

- **Base.** A non-discarded PNG of the project: a sprite, image or portrait, 64 to
  2560 px on each side. That covers 2× high-resolution sprites (up to 1664×2432);
  the inpaint itself always works on a 1024 px crop, so memory does not grow with the
  base.
- **Face box.** Integer pixels inside the base, at least 16 px on each side, square
  or near-square (aspect between 0.5 and 2). The Studio proposes it from the alpha
  channel (the centre of the top band of the figure; face ≈ 11% of figure height,
  ≈ 7.5% from its top), and the creator drags or resizes it.
- **Expressions.** One to four distinct names. Each is a preset or free text of at
  most 40 letters, digits, spaces, hyphens and apostrophes. Each makes one image.

### Prompt

One prompt per expression, built by the server and stored on the job. In order:

1. the character type tags;
2. `solo, close-up, face`;
3. the character's appearance tags (from its profile, with the same phrase map as
   portraits);
4. the expression tags;
5. `white background`;
6. the quality tags.

The negative prompt is the portrait negative plus `expressionless`.

Presets (Danbooru tags):

| Name | Tags |
| --- | --- |
| happy | smile, open mouth, happy |
| laughing | laughing, closed eyes, open mouth, smile |
| sad | sad, frown, furrowed brow, looking down |
| crying | crying, tears, sad, open mouth |
| angry | angry, frown, v-shaped eyebrows, glaring, clenched teeth |
| surprised | surprised, wide-eyed, open mouth, :o, raised eyebrows |
| embarrassed | embarrassed, blush, wavy mouth, looking away |
| worried | worried, frown, furrowed brow, sweatdrop |
| smug | smug, smirk, half-closed eyes |
| thinking | pensive, closed mouth, looking up |
| sleepy | sleepy, half-closed eyes, yawning |
| determined | determined, serious, closed mouth, v-shaped eyebrows |

Free text is cleaned and used as tags.

### Job and storage

Migration 0026 adds to `narrative_image_jobs`:

- the purpose `character_expression` (it needs a character);
- `base_asset_id`, a composite FK to the project's asset;
- `face_box` (JSON), `strength` (float), `expressions` (JSON list) and `prompts`
  (JSON list), all required exactly for this purpose.

`width`/`height` are the base's size, and `prompt` is the first prompt (kept for
display).

Outputs are candidates of the base's kind, named `<character> <expression>`. Their
provenance records the base asset, face box, strength, expression and its prompt.
Byte-identical outputs dedupe as before.

### Child protocol

An optional `inpaint` block:

```json
{"image": "<absolute path inside the work dir>", "sha256": "…",
 "box": [l, t, r, b], "strength": 0.9, "prompts": ["…", "…"]}
```

- **Parent.** The parent writes the base bytes it fetched hash-verified from the
  store.
- **Child checks.** The child checks the file's size (at most 16 MiB) and hash, the
  box (inside the image, at least 16 px), the strength (0.3–1) and one prompt per
  seed. `width`/`height` must equal the image's size. It cannot be combined with
  `cutout`.
- **Output.** Same size as the base, and RGBA exactly when the base has alpha. The
  parent rejects anything else.

Peak memory is under the existing 8 GiB free-memory floor.

### Studio

In Characters → On stage, **Generate expressions** opens a panel for one of the
character's sprites:

- the sprite with the draggable, resizable face box;
- preset chips and a free-text field, up to four expressions;
- progress, then candidates, previewed zoomed onto the face so expressions can be
  told apart.

**Use as "happy"** approves the asset and sets the character's `happy` sprite in
the draft. Failed or unwanted candidates can be discarded; regenerating uses new
seeds.

## Slice B: poses (designed, built next)

- **Pose skeletons.** Preset OpenPose skeletons (standing, hand on hip, arms crossed,
  waving, pointing, thinking) are drawn in the child with PIL. They use fixed COCO-18
  keypoints and the standard OpenPose limb colours; there is no pose detector.
- **Generation.** ControlNet OpenPose SDXL (`xinsir/controlnet-openpose-sdxl-1.0`,
  Apache-2.0) guides the pose. IP-Adapter Plus SDXL with the ViT-H encoder
  (`h94/IP-Adapter`, Apache-2.0) uses the base sprite as identity reference, and the
  prompt adds the character's appearance tags. The anime-seg cutout makes the result
  transparent.
- **Memory.** SDXL, ControlNet, IP-Adapter and ViT-H together exceed 12 GB, so the
  child uses `enable_model_cpu_offload()` and is measured. A pose keeps the outfit
  close but not pixel-identical, and outputs are full-body candidates that need
  review.
- **Pins.** Model manifests are pinned like the others: one directory and manifest
  SHA-256 per model, and the job records each model's identity.

## Slice C: scene art (planned, after B)

The user asked for event CGs on 2026-10-31: a full illustration of an existing
character in a scene, for example Quen Aldwinia from the "Stage & theme demo" project
sitting on a couch. The character is referenced by an approved image, not described
again.

- **Request.** `POST /v1/narrative/projects/{project}/characters/{character}/scene-art-jobs`
  with `reference_asset_id` (an approved, non-discarded PNG sprite, image or portrait
  of the project), a `scene` description (bounded free text, for example "sitting on
  a couch in a sunlit living room, reading a book"), one to four images and an
  idempotency key.
- **Generation.** Text-to-image SDXL from the pinned Animagine weights at 1344×768,
  the SDXL 16:9 bucket that backgrounds already use. IP-Adapter Plus SDXL with the
  ViT-H encoder, the models slice B pins, takes the reference composited on white
  and cropped to the figure as the identity image. The server builds the prompt:
  character type and `solo`, the scene tags, the character's appearance tags, then
  quality tags. No ControlNet and no cutout: the output is an opaque RGB scene.
- **Content policy.** The scene description goes through the image content policy
  like every other image description (ADR 0039, `narrative/image_content_policy.toml`,
  overridable with `FLINT_GRAPH_NARRATIVE_IMAGE_CONTENT_POLICY`). The route passes
  `policy=content_policy(settings.narrative_image_content_policy)` into
  `create_scene_art_job`. The request builder calls `policy.check()` on the scene
  text, so a blocked word refuses the job with a 422 before anything is queued. The
  negative prompt starts with `_negative(policy)`, then the character's own
  negatives and `multiple girls`/`multiple boys`, within CLIP's 77 tokens. The IP-Adapter scale, about 0.6, is
  tuned in qualification; too high copies the reference pose and framing.
- **Storage.** The job is an image job (`scene_art`) on the same outbox, fenced
  activity, isolated child and hash-checked storage. Results are candidate library
  assets of kind `image`, named `{character} scene N`. Their provenance records the
  reference asset, scene text, prompt, IP-Adapter scale and model identities. The
  creator approves them in the library or the character sheet.
- **Order.** It shares slice B's IP-Adapter pins, loader and memory work (CPU offload
  if SDXL, IP-Adapter and ViT-H exceed 12 GB), so it follows B.
- **Not in this slice.** The story format and runtime. Showing an approved image as a
  full-screen CG and a gallery is the player side, built separately on branch
  `codex/cg-presentation`: an optional stage-node `cg` field holding an ordinary
  image asset ID, a CG layer and a gallery, runtime 0.5.0. Scene art only produces
  approved images for it. Identity is close, not exact, so every result needs review.

## Out of scope

Face detection models (the creator adjusts the box), automatic mouth or eye
animation, and multi-character poses and scene art (one referenced character per
image).
