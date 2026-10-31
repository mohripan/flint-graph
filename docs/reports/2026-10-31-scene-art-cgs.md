# Event CGs of an existing character (ADR 0041, slice C)

The user asked where CG creation that references a character was. Runtime 0.5.0
already plays event CGs and has a gallery ([ADR 0042](../adr/0042-event-cgs-and-gallery.md)),
and Assets → CGs could browse and upload them, but nothing generated one. This slice
does, following the
[design](../superpowers/specs/2026-10-31-character-expressions-and-poses-design.md#slice-c-scene-art-built-2026-10-31)
and [ADR 0041](../adr/0041-character-expressions-and-poses-from-a-base-sprite.md).
A creator opens Assets → CGs → **Generate CGs**, picks a character and one of its
approved images, and describes the scene. Four 16:9 candidates that look like that
character wait among the CGs for approval, like any generated asset. An approved one
is picked in a stage node's Event CG field. The story format, runtime and player do
not change.

Slice C was planned after slice B (poses) because both use IP-Adapter. B is still
not built, so this slice adds the IP-Adapter pin and loader; poses can reuse them.

## What changed

- **Identity reference (child).** `runtimes/imagegen/generate.py` takes an optional
  `scene` block: the IP-Adapter directory, its SDXL weight and image encoder (relative
  paths inside it), a scale of 0.1–1 and one reference PNG that the parent wrote into
  the private work folder. The child checks every file again (regular files, no path
  escapes, PNG 64–2560 px, at most 16 MiB, SHA-256 match). It refuses `scene` together
  with `cutout`, `inpaint` or `hires`, and at any size but 1344×768. It then:
  1. cuts the figure from the reference (along the alpha of a sprite, or what differs
     from the corner backdrop of an opaque portrait), centres it on white in a square
     and scales it to 448 px;
  2. loads IP-Adapter Plus SDXL (ViT-H) into the pipeline while the SDXL weights are
     still on the CPU, runs the image encoder on the GPU once, and releases it;
  3. moves SDXL to the GPU and renders text-to-image at 1344×768 with the image
     embeddings at scale 0.5.

  The release saves about 1.2 GiB: the measured peak is 8.0 GiB allocated instead of
  9.2 GiB with the encoder kept, so a scene asks for 8.5 GiB free (the hires 1.5×
  floor). No dependency changed; the runtime lock is the same.
- **Parent.** `IpAdapterModel` and `verify_ip_adapter_model` pin the download like the
  other models: the manifest SHA-256 is the operator pin, every file must match, and
  it must hold exactly one `sdxl_models/*.safetensors` and the
  `models/image_encoder` config and weights. `GenerationRequest.scene` carries the
  hash-verified reference bytes and the scale. Results must be opaque 8-bit RGB at
  1344×768, and `GenerationResult.ip_adapter` names the adapter. A scene job on a
  worker without the adapter fails with `ip_adapter_unavailable`.
- **Prompt (`flint_graph.narrative.imagegen.scene_art_request`).** Type tags and `solo`,
  the scene as written, the character's appearance tags (same phrase map as portraits),
  then `safe, masterpiece, high score, great score, absurdres`. There is no
  `looking at viewer` or plain background. The negative prompt is the character's own
  (content policy first, type negatives, long-hair fix), plus `multiple boys` or
  `multiple girls`. The scene text and the character's stored description both pass
  the image content policy; a blocked word refuses the job with 422 before anything
  is queued. Character names in the scene are kept as written: with the same seed,
  "quen sitting on…" and "boy sitting on…" rendered nearly the same image.
- **Jobs (migration 0030).** Purpose `scene_art` (it needs a character) with
  `reference_assets` (`[{character_id, asset_id}]`), `ip_adapter_scale` and, once
  completed, `ip_adapter_model` (`repo@revision`). A check binds them to the purpose
  and requires the adapter on a completed scene job. References are a JSON list
  rather than foreign keys: library assets are discarded, never deleted, and the
  service checks each reference when the job is queued and loads it, scoped to the
  project, when the job is claimed. The jobs reuse the image outbox, fenced Temporal
  activity, idempotency (the references and the scene are part of the request
  identity), workspace limits, GPU contention handling, cancellation and recovery.
- **Worker.** The activity fetches each reference from the store hash- and
  size-verified. The worker verifies the IP-Adapter at startup when
  `FLINT_GRAPH_NARRATIVE_IMAGE_IP_ADAPTER_MODEL_DIR` and `…_MANIFEST_SHA256` are set
  (optional, paired, absolute) and logs whether scene art is ready.
- **API.** `POST` and `GET /v1/narrative/projects/{project}/assets/scene-art-jobs`,
  next to the background jobs, since a CG belongs to the project rather than to one
  character sheet:

  ```json
  {"scene": "Quen sitting on the couch by the window at night",
   "characters": [{"character_id": "quen", "reference_asset_id": "…"}],
   "count": 4, "idempotency_key": "…"}
  ```

  The reference must be a non-discarded PNG `sprite`, `image` or `character_portrait`
  of the project (404 otherwise), approved and 64–2560 px (422
  `invalid-scene-art-request`). `characters` takes exactly one entry for now (see
  "Two characters" below); it is a list so a second can follow without a new shape.
  Results are candidate `image` assets named `{character} CG {n}`, tagged with the
  character so they also show under its library group. Provenance records the scene,
  prompt, each reference (asset ID and SHA-256) and the adapter (repo, revision,
  license and scale).
- **Studio.** Assets → CGs gains **Generate CGs** next to Upload CG
  (`CgGenerator.tsx`, logic in `cgModel.ts`). The panel has a character list, "Look
  from" thumbnails of the character's approved portraits, sprites and images (its
  chosen portrait first; generated CGs never), the scene text, **Generate 4 CGs**,
  progress, cancel and the error of a failed job. Active CG jobs also show under the
  library header in every view. The CGs group in the side rail now stays listed when
  it is empty, because otherwise there was no way to reach Generate CGs in a project
  without CGs: the browser QA found that.

## Qualification

**GPU probes** (scratch scripts on the RTX 5070 Ti, Quen's approved portrait as
reference; [qualification.json](evidence/scene-art-cgs-2026-10-31/qualification.json)):

- **Scale** ([sheet](evidence/scene-art-cgs-2026-10-31/06-probe-scale-and-crop.png),
  same seed). Without the adapter the text alone gives white hair and red eyes in
  someone else's clothes. At 0.5 the oversized black jacket over a white top, dark
  trousers and the bob come back and the night scene keeps its light. At 0.6 the
  reference's hand-to-shoulder pose starts repeating, and at 0.7 the scene washes
  toward the reference's plain backdrop. The default is 0.5.
- **Crop.** The whole figure padded to a square keeps one character. A square of the
  upper body drew Quen twice.
- **The reference matters.** A sprite with red slash effects around it put those
  effects into the scene, so the panel tells creators to pick a plain portrait or
  sprite.
- **Speed and memory.** About 11 s per image after a 19 s load; 8.0 GiB peak allocated
  with the encoder released.
- **Identity measure.** CLIP ViT-H similarity to the reference is 0.70 for the
  text-only render and 0.69–0.77 for the adapter renders. The scene dominates that
  number, so recognizability was judged by eye; the outfit is the clearest tell.

**GPU end to end through the worker: passed.** The opt-in live test
`test_real_gpu_scene_art_draws_the_referenced_character` ran this branch: API job,
outbox relay, owned Temporal workflow and fenced activity, the real child, then
hash-verified storage. It passed in 126 s (the job itself 112 s, two images). Both CGs
are opaque 1344×768 RGB and both are recognizably Quen; the second even keeps the
white hoodie. The first lost the night setting and sat on a window ledge instead of a
couch.

**Studio on the real stack: passed.** A QA Studio from the worktree ran on API 8121,
playtest 5212 and frontend 5193, with its own database `flint_cg_qa` on the owned
PostgreSQL (migrated to 0030; the user's database stays at 0029) and its own image
queue. The demo project and Quen's approved portrait were copied read-only from the
user's Studio. In the built-in browser and headless Edge (1366×1000):

1. Assets → CGs (listed with 0 CGs after the rail fix) → **Generate CGs**; picked
   Quen Aldwinia, whose approved portrait was preselected as "Look from"
   ([screenshot](evidence/scene-art-cgs-2026-10-31/01-generate-cgs.png)).
2. Scene "Quen sitting on the couch by the window at night, city lights outside" →
   **Generate 4 CGs**. Progress read "Loading the model…"; four candidates arrived
   under To review after 95 s
   ([screenshot](evidence/scene-art-cgs-2026-10-31/02-candidates.png)). All four are
   recognizably Quen on a couch by a night window with city lights.
3. Approved `quen CG 4`, chose it in Write → the first scene's stage → Event CG
   ([screenshot](evidence/scene-art-cgs-2026-10-31/03-stage-event-cg.png)) and saved
   revision 3.
4. Playtest of revision 3: the CG covers the stage under Quen's first line
   ([screenshot](evidence/scene-art-cgs-2026-10-31/04-playtest.png)).

At 390 px the panel stacks without horizontal scrolling
([screenshot](evidence/scene-art-cgs-2026-10-31/05-generate-cgs-390px.png)).

## Two characters

The user asked for one or more characters. A probe gave two references masked to the
left and right halves of the image (IP-Adapter attention masks) with `1boy, 1girl`.
One render of seven kept both identities. The others swapped or merged hair colour
and outfits, because the text tags apply to the whole image
([sheet](evidence/scene-art-cgs-2026-10-31/07-probe-two-characters.png)). That is not
good enough to offer, so a CG shows one referenced character, as ADR 0041 planned.
Two characters need regional prompting or a second inpainting pass per character; a
follow-up can extend `characters` to two without changing the API's shape.

## Limits

- Identity is close, not exact: outfits drift (shorts instead of trousers in some
  renders), and every result is a reviewed candidate.
- The palette leans pale, toward the reference's light backdrop, and a scene can lose
  its time of day. Rerunning or a more specific scene helps; regional or layer-wise
  adapter scales are possible tuning later.
- References are offered only when they carry the character's ID (generated portraits
  and sprites, and uploads made with a character). An upload without one is not
  listed, though the API accepts it.
- Evidence images, job records and the probe outputs are in ignored
  `notes/scene-art-qualification/`.

## Checks

On branch `claude/scene-art-cgs`, based on master 0116894:

- `uv run pytest`: 1818 passed, 105 skipped (SQLite). The scene-art and character
  image suites also passed on PostgreSQL (`FLINT_GRAPH_NARRATIVE_PG_URL`, a throwaway
  schema migrated to 0030): 16 passed.
- `uv run ruff check .` and `uv run mypy`: clean.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: single head
  `0030_narrative_scene_art`.
- `docker compose config`: valid.
- Child (`runtimes/imagegen`, `python -I -m unittest discover`): 29 tests, 1 skipped
  (the real segmenter, which needs its model path).
- Frontend: `npm run typecheck`, `npm test` (108 passed) and `npm run build`.
- Live: `test_real_gpu_scene_art_draws_the_referenced_character` passed on the GPU.
- Skipped: the deterministic RAG eval gate (`flint-graph-eval`), which this change
  does not touch.
