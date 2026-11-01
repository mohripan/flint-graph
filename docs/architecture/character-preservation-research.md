# Character preservation: research boundaries and Studio design

Status: research and implementation design for M40 #180–#186. The offline lab is
implemented. [ADR 0047](../adr/0047-reviewed-character-looks-and-advisory-feedback.md)
delivers the first Studio slice: immutable looks, optional WD suggestions and
garment-tag comparison, and manual advisory feedback. Multi-view looks, automatic
identity scoring/ranking, pose-model rollout and LoRA training below remain
designs, **not shipped features**.
See the [measured report](../reports/2026-11-01-character-preservation.md).

## Compare three separate outcomes

1. **Identity:** CCIP's learned pairwise distance, lower is closer, on one character
   per image/crop. Record the exact feature checkpoint and learned metric together.
2. **Outfit:** confidence-weighted Jaccard over a versioned garment-tag taxonomy,
   with probabilities below 0.35 discarded. No visible garment evidence returns
   unknown. A low overlap requests review; occlusion and back views can cause it.
3. **Request followed:** a separate review of pose, expression, scene, lighting,
   composition, anatomy and unwanted extra people. Identity is not a pose metric.

The report retains agent fixture judgments separately from creator ratings. A
threshold fitted to one tiny dataset is a fit statistic, never production
qualification. Freeze a training split, then measure false accepts/rejects on
held-out characters, outfits and seeds. Include same character/new outfit and
different character/similar hair/clothes negatives. Calibrate the identity and
outfit checks independently; publish confusion matrices and unknown coverage.
Repeat after any checkpoint, preprocessing, crop or taxonomy change.

Identity recognition also does not certify reviewed hair or eye traits. In the
two-person background-reference ablation a black-haired character became
silver-haired while its diagnostic CCIP distance still passed the upstream
cutoff. Add a separate, creator-qualified reviewed-trait check; do not equate
this observation with a proven identity-classification error. Garment tags alone
cannot cover it. The pilot's clothing fit also accepts most labelled drifts,
so no threshold from this delivery should activate automatic filtering.

## Reviewed named looks (#181)

An image approval and a reviewed look are distinct actions. Propose hair, eyes and
clothing from a chosen approved reference, then let the creator edit them before
locking the look. A suggested tag is not an assertion of intent. Preview source
and tags side by side; preserve an explicit draft/reviewed state.

The first slice stores the source hash, reviewed tags, authored character type,
parent, reviewer, policy/bundle and optional raw observation. The fuller proposed
multi-view record contains:

- Project/character IDs, look ID, creator name such as “Travel coat”, parent look
  ID and a schema version.
- Approved source asset ID plus byte SHA-256, optional approved reference IDs and
  crops, and the accepted character-sheet view mapping.
- Reviewed identity and garment tags; original tag probabilities and tagger/model
  hashes; excluded rating observations in a separate non-prompt field.
- Reviewer identity/time, revision ID and the policy/prompt bundle used for review.

An intentional costume change creates another named look. It does not rewrite
old runs or rename the character. Pose, expression, CG and assistant image
suggestions resolve a look ID at admission, store its immutable hash with the job,
and reuse that snapshot on retry. Changing the default affects only later jobs.
For a two-person CG each character resolves its own look independently. Existing
base-image face inpainting remains valuable for expressions because it directly
preserves the rest of the approved image.

Only reviewed tags enter prompts. Normalize underscores to spaces before applying
the existing typed content policy, validate creator edits too, and retain the
reviewed prompt/config bundle identity. Never copy rating tags, predicted existing
character names, or copyrighted-character tags into captions. Do not use a rating
classifier to relax the application policy. There is no schema/database change in
this research delivery; a later feature needs an authorized API and revision tests.

## Advisory candidates (#183)

Scores belong to private candidate metadata, with source/candidate hashes, look
ID/hash, crop coordinates, model hashes, preprocessing/taxonomy version, thresholds,
status and timing. A scorer outage, missing model, uncertain crop or timeout yields
`unknown`; the candidate still appears and can be approved. Flags say “Review
character” / “Review clothes”, with a brief explanation and the reference visible.
Scores never veto approval. Preserve default generation order; offer an explicit
sort and keep-best-N option only after creator calibration.

If best-N is enabled, bound attempted images, GPU seconds, retries and cost before
admission; expose both retained and discarded candidate counts and an inspectable
receipt. Do not silently reroll until a metric passes. Unknown candidates remain
available. Per-person CG scoring requires verified person detection/segmentation
licenses and evaluation on overlap/occlusion. Use a one-to-one assignment between
reference identities and detected crops; the same crop cannot satisfy both people.
Extra, missing or merged figures are separate failures. Whole-image CCIP is invalid
for a multi-person image. The pilot uses no detector and makes no such claim.

## Private LoRAs (#184)

Train only on approved assets explicitly selected by the creator. Keep a frozen
training-set manifest with rights declarations, hashes, captions and look IDs. The
agent-generated pilot references are not a creator-selected training set. A
synthetic tensor backward-pass probe measures resource feasibility only and saves
no useful weights. It cannot establish required image count, identity retention,
style consistency or the benefit of a trigger word.

The proposed first quality experiment uses 1/4/8/12 independently approved images
per character; never count four crops of one image as four independent views.
Reserve at least one pose/view and independent seeds for testing. Compare reviewed
look captions against reviewed tagger captions plus one original trigger, rank
4/8, 200/500/1000 steps, and deliberately different outfits at inference. Cache
latents and both SDXL text encoders before training; unload the VAE/encoders, train
only UNet LoRA attention parameters, batch 1, fp16 autocast, FP32 trainable weights,
gradient checkpointing and an 8-bit optimizer. Measure dedicated device use and
Torch peak separately; add a safety margin before choosing the worker GPU floor.
Run the same pose bench and two-character tests against the reference baseline.
Style training needs its own approved backgrounds/CGs and held-out art; CCIP is
not a style-quality score. Do not mix character and style experiments or silently
include generated candidates that failed creator review.

A future training job uses the existing fenced ledger/outbox pattern: tenant and
project authorization before reading assets, IDs-only Temporal history, private
verified input copies, bounded writable output, wall/GPU/disk budgets, cancellation,
lease/attempt fencing, hash-verified safetensors output and immutable provenance.
Never load pickled adapters or executable checkpoint code. Store a LoRA as a
private, versioned project artifact pinned to base-model and training-set hashes.
Admission pins the selected LoRA version, strength and license acceptance; retries
reuse it. Weights, references, tags and training data never enter story packages,
Godot exports, release downloads or a public asset URL. Deletion/access revocation
must follow the project's private artifact policy.

## Reference and context experiments (#185)

Do not collapse these into one “more references” setting:

| Method | What must be controlled and measured |
| --- | --- |
| Multiple approved views | Independent sources and view labels; compare full-body plus portrait with genuinely independent views. Two crops of one source are only a scale ablation. |
| Front/side/back sheet | Creator-approved coherent views; test the sheet as one reference versus separately encoded views. A generated sheet can already contain drift. |
| Reference attention / pixel transfer | Separate pose-change ability from texture copying and source-pose leakage; compare masked repaint against full-image img2img. |
| Image editing | The staged klein 4B pilot is measured; extend to creator-approved characters. Qwen-Image-Edit / Kontext have source/license reviews only, not local quality runs. Pin precision/offload and record host RAM as well as VRAM. |
| Regional two-person conditioning | Keep per-character text and image attention in the same explicit region; score two assigned crops and count extra figures. A half-image mask alone does not regionalize text. |
| Background and lighting | The pose pilot holds sunset/garden text fixed. The separate two-person pilot compares klein with/without the same empty background image; one of two context scenes changes hair color. Extend across backgrounds and seeds before a default. |

No method should become the default just because a vendor example succeeds. Run
the fixed matrix, record failures and creator judgments, and qualify license and
memory requirements before adding it to the Studio worker.
