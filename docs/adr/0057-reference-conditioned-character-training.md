# ADR 0057: Reference-conditioned character training

2026-11-04. Implemented as an opt-in slice of #184.

The private klein LoRA trainer previously learned from captions and target images,
while pose generation also supplies an approved character image. Add a separate
training recipe that supplies the frozen approved base throughout training.
Keep the existing caption-only recipe, request identity and weights valid.

`conditioning: "reference"` requires a reviewed character/look target and explicit
operator admission through `NARRATIVE_STYLE_REFERENCE_TRAINING_ENABLED` (default
false). Omission or `"text"` preserves existing behavior, including project styles.
The editor offers the option only for character training when the API advertises
it. Changing the choice resets dataset confirmations. History discloses the mode.
An admitted replay remains readable/replayable after admission is disabled.

The worker resolves the unique approved base by its frozen SHA-256, rather than
assuming it is the first selected image. Existing source, scope, look, anatomy,
lease and publication checks still apply. No new database column is necessary:
the recipe hash and existing look snapshot describe the selected mode/source.

Protocol 2 adds a bounded integer reference index; protocol 1 stays supported.
Composite the reference over white, fit within 512 pixels and floor dimensions
to multiples of 16. Cache its normalized VAE mode latent. At every step append
clean reference tokens to noisy target tokens with distinct image IDs (target
time 0, reference time 10), following pinned Diffusers 0.42.1 klein conventions.
Calculate flow loss only on target tokens. Rank, optimizer, target buckets,
resource admission, offline model pins and bounded child supervision stay intact.
Runtime receipts include the reference hash/size and conditioning helper hash;
the parent verifies the source/helper and target-only loss declaration before
publishing private weights.

This aligns one-reference training with the editing input structure. Guided poses
use an additional reference and different appearance token positions; they need
their own qualification. Four images, one seed or lower training loss cannot
establish improved anatomy, lighting or character preservation. Keep this mode
optional, retain failed outputs, and require manual candidate review. Weights
remain private and never ship in games. No image policy, prompt lock, model
dependency, database migration or game runtime change is involved.

See the [qualification report](../reports/2026-11-04-reference-conditioned-training.md).
