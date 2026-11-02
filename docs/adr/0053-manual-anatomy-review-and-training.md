# ADR 0053: Manual anatomy review protects training sources

Date: 2026-11-02. Status: accepted and implemented under the creator's
autonomous continuation of character-model development (#183/#184).

Identity and outfit agreement do not certify anatomy. A seated Aster candidate
kept the broad look but had an extra boot; a combined-adapter candidate had a
malformed hand. Record a separate manual verdict: `unknown`, `acceptable` or
`flawed`. Keep image approval available regardless of this verdict.

Anatomy belongs to immutable image bytes, independent of which look is used for
comparison. Store one workspace/project/SHA-256 review with its own optimistic
version, actor and timestamps (migration 0040). Existing identity/clothing/notes
reviews keep their current version. Old rows read unknown; legacy clients that
omit anatomy cannot erase it. An explicit anatomy write supplies its separate
base version. A stale dialog for another look/copy must reload before changing
the shared verdict. A live copy can revise the verdict even if the original
asset was discarded. Do not infer labels by parsing old free-form notes.

Studio Compare look adds the anatomy control and explains training exclusion.
Cards show Review anatomy even when identity and clothes match. Training pickers
disable known flawed image bytes and explain why. The server remains authoritative
when client flags are missing or truncated. Unknown remains compatible with
existing training; acceptable is a manual assessment, not an automated guarantee.

Refuse known flawed bytes at admission for both character and project-style
training. Keep admitted idempotent replays/history intact. Recheck before reading
training inputs, during progress/watch checks and before publishing a completed
version. Final publication takes the same project lock as review writes so a
committed failure cannot race past the final check. A private staged object can
remain after a publication race, as with cancellation, but no usable weight
binding is published. Existing completed adapters are not retroactively revoked.

These reviews are editor metadata outside game packages and telemetry. No model,
recipe, runtime dependency, Godot version or content policy changes. This adds no
automatic anatomy score/detector, correction model, ranking or creator calibration.
Qualify public review/version/scope and training boundaries, real PostgreSQL
migrations, a real registered Temporal rejection and the browser flow on task-owned
synthetic fixtures. Preserve creator projects and existing fixtures.
