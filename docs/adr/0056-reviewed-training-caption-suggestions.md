# ADR 0056: Reviewed per-image training caption suggestions

2026-11-02. Implemented as a bounded product slice of #184, following the
creator's request to continue model development.

Character/style training captions currently require manual editing and start
from the same reviewed-look tags. Reuse the already pinned, isolated CPU WD tagger
to suggest visible content separately for each approved training image. Keep
appearance, garment, pose, framing and scene tags in a closed versioned vocabulary;
exclude inferred gender/counts, character names, ratings and rendering-quality/style
instructions. Apply the current image content policy. Confidence is an observation,
not calibrated quality or proof that the tags are correct.

`POST /style-jobs/caption-suggestions` authorizes a project member, verifies a
bounded approved PNG from private storage, and records the existing immutable
tagger observation with source/model fingerprints. Release the initial database
transaction before CPU inference; lock/recheck project and source afterward.
Repeated proposals use the saved observation, so its ID and returned confidences
remain consistent even if a later tagger call varies. No training job, look,
approval or anatomy verdict is changed by reading tags.

The editor presents a proposal alongside the current caption. Only an explicit
**Use suggested caption** replaces that image's text, checking its ID/hash again
and resetting rights/same-look/anatomy confirmations. Manual edits made while
tagging remain intact. Empty results, busy/unavailable taggers and older servers
retain manual entry. Abort stale UI requests when the project/look changes.

The chosen, possibly edited caption follows the existing frozen training dataset
and trigger-word path. Old jobs and recipe hashes remain valid. No migration,
prompt template, image policy, model dependency, training recipe or game runtime
changes. No automatic caption acceptance, image approval, scoring/ranking or
model-quality improvement is claimed.

See the [delivery and qualification report](../reports/2026-11-02-training-caption-suggestions.md).
