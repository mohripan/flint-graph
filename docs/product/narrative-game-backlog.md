# Narrative game studio: GitHub delivery queue

Created: 2026-10-27; dependency review updated 2026-10-30. The original five
milestones contained 21 issues. The user added #133–#167 across four further
milestones and shared conversation work. On 2026-10-31 the user added M39
(#173–#178) for voice references and expressive delivery. These additions are
planned, not delivered.

The [product brief](narrative-game-studio.md) explains the direction. Review the
[M30 written contract](../superpowers/specs/2026-10-27-portable-story-runtime-design.md)
before implementation. This review was approved on 2026-10-27; #117 package
delivery is documented in [M30 progress](../milestones/30-portable-story-runtime.md).
Each later subsystem needs its own focused design.
Issue dependencies are explicit in GitHub; the grouping below is not a claim
that every task must run serially. Close only with real acceptance evidence.

## M30: portable story runtime and Godot proof

[Milestone](https://github.com/mohripan/flint-graph/milestone/17) ·
[Tracking issue #112](https://github.com/mohripan/flint-graph/issues/112)

| Issue | Deliverable | Depends on |
| --- | --- | --- |
| [#117](https://github.com/mohripan/flint-graph/issues/117) | Package v1 and original three-ending fixture | Written contract review |
| [#118](https://github.com/mohripan/flint-graph/issues/118) | Reference execution, traces and saves | #117 |
| [#119](https://github.com/mohripan/flint-graph/issues/119) | Pinned engine/templates and safe source export | #117 |
| [#120](https://github.com/mohripan/flint-graph/issues/120) | Actual Godot player and runtime/save parity | #118, #119 |
| [#121](https://github.com/mohripan/flint-graph/issues/121) | Real web export, browser proof and developer guide | #120 |

## M31: authored narrative game studio

[Milestone](https://github.com/mohripan/flint-graph/milestone/18) ·
[Tracking issue #113](https://github.com/mohripan/flint-graph/issues/113)

| Issue | Deliverable | Depends on |
| --- | --- | --- |
| [#122](https://github.com/mohripan/flint-graph/issues/122) | Authorized projects and immutable revisions | #121 |
| [#123](https://github.com/mohripan/flint-graph/issues/123) | Scene/choice editor and isolated shared-runtime preview | #122 |
| [#124](https://github.com/mohripan/flint-graph/issues/124) | Durable releases, isolated builds and authorized artifacts | #122, #123 |

## M32: reviewed narrative assistance and continuity

[Milestone](https://github.com/mohripan/flint-graph/milestone/19) ·
[Tracking issue #114](https://github.com/mohripan/flint-graph/issues/114)

| Issue | Deliverable | Depends on |
| --- | --- | --- |
| [#125](https://github.com/mohripan/flint-graph/issues/125) | Approved canon, character knowledge and scoped sources | #122 |
| [#126](https://github.com/mohripan/flint-graph/issues/126) | Bounded proposal jobs and reviewed revision diffs | #125, #124; land #135 first |
| [#127](https://github.com/mohripan/flint-graph/issues/127) | Continuity findings and dependency-aware revisions | #126 |
| [#150](https://github.com/mohripan/flint-graph/issues/150) | Project-scoped assistant threads producing reviewed proposals | #96, #125, #126; coordinate #143/#154 |

## M33: controlled game asset production

[Milestone](https://github.com/mohripan/flint-graph/milestone/20) ·
[Tracking issue #115](https://github.com/mohripan/flint-graph/issues/115)

| Issue | Deliverable | Depends on |
| --- | --- | --- |
| [#128](https://github.com/mohripan/flint-graph/issues/128) | Uploaded asset library, approvals and provenance | #122 |
| [#129](https://github.com/mohripan/flint-graph/issues/129) | Bounded image variations and reviewed references | #128, #124 |
| [#167](https://github.com/mohripan/flint-graph/issues/167) | Consistent sprite/background sets from approved references | #129, #158; coordinate #137/#82 |

## M34: narrative game release qualification

[Milestone](https://github.com/mohripan/flint-graph/milestone/21) ·
[Tracking issue #116](https://github.com/mohripan/flint-graph/issues/116)

| Issue | Deliverable | Depends on |
| --- | --- | --- |
| [#130](https://github.com/mohripan/flint-graph/issues/130) | Reproducible routes and nightly black-box gates | #124, #127, #128 |
| [#131](https://github.com/mohripan/flint-graph/issues/131) | Build isolation, budgets, privacy, telemetry, DX and recovery | #124, #129 |
| [#132](https://github.com/mohripan/flint-graph/issues/132) | Complete original game and live qualification report | #130, #131, #129 |

The final #132 game should exercise the M38 presentation/parity work. Keep #130
route qualification and #131 operations reusable while those features are built.

## M35: versioned prompt management

[Milestone](https://github.com/mohripan/flint-graph/milestone/22) ·
[Tracking issue #133](https://github.com/mohripan/flint-graph/issues/133)

| Issue | Deliverable | Dependency/order |
| --- | --- | --- |
| [#134](https://github.com/mohripan/flint-graph/issues/134) | Langfuse source-of-truth ADR, compatibility and prompt-edit threat model | Before catalog implementation |
| [#135](https://github.com/mohripan/flint-graph/issues/135) | Typed catalog, byte-identical goldens and persisted prompt hashes | #134; before #126 |
| [#136](https://github.com/mohripan/flint-graph/issues/136) | Pinned opt-in Langfuse with protected access | Alongside catalog work |
| [#137](https://github.com/mohripan/flint-graph/issues/137) | Locked fallback, label resolution and per-run prompt identity | #135, #136 |
| [#138](https://github.com/mohripan/flint-graph/issues/138) | Evaluation-gated prompt promotion and rollback | #137 |
| [#139](https://github.com/mohripan/flint-graph/issues/139) | Privacy-safe prompt-version telemetry | Coordinate #79 trace destination |
| [#140](https://github.com/mohripan/flint-graph/issues/140) | Narrative task prompts and creative rubrics | #126; avoid a whole-M35 prerequisite cycle |

Langfuse prompt management is the user's chosen direction. Runtime requests must
remain usable from a reviewed committed lock without waiting for Langfuse.
PostgreSQL remains authoritative for runs/provenance/usage, file-based reviewed
quality baselines remain authoritative, and prompt management uploads no tenant
documents/questions/answers. Trace-backend adoption remains #79's separate decision.

## M36: measured context engineering

[Milestone](https://github.com/mohripan/flint-graph/milestone/23) ·
[Tracking issue #141](https://github.com/mohripan/flint-graph/issues/141)

| Issue | Deliverable | Dependency/order |
| --- | --- | --- |
| [#142](https://github.com/mohripan/flint-graph/issues/142) | Provider-accurate counts and pre-call admission | #135; extends #95 |
| [#143](https://github.com/mohripan/flint-graph/issues/143) | Instruction/history/memory/evidence/tool/output budgets | #142; coordinate #82 parent reservations |
| [#144](https://github.com/mohripan/flint-graph/issues/144) | Stable provider prefixes and measured cache usage | #135, #142; complements #83 server KV cache |
| [#145](https://github.com/mohripan/flint-graph/issues/145) | Inspectable compact per-call context manifests | #143; IDs, versions and counts |
| [#146](https://github.com/mohripan/flint-graph/issues/146) | Measured ordering/deduplication/size tuning | #142, #143; fixed quality workload |

Per-call token planning does not complete cross-call budget enforcement. Preserve
quality gates, authorization and explicit overflow behavior; avoid silent
truncation or cross-scope cache reuse. Real provider/cache measurements remain
required acceptance evidence.

## Shared M27 conversation work

[Milestone](https://github.com/mohripan/flint-graph/milestone/14). These are focused
extensions of #62/#84, reusing the delivered #96/#97/#99 ledger and ordering.

| Issue | Deliverable | Dependency/order |
| --- | --- | --- |
| [#147](https://github.com/mohripan/flint-graph/issues/147) | Standalone query rewriting for general follow-ups | #135 and conversation ledger |
| [#148](https://github.com/mohripan/flint-graph/issues/148) | Bounded prior turns as context, never citable evidence | #147, #143 |
| [#149](https://github.com/mohripan/flint-graph/issues/149) | Branch from edited/regenerated earlier turns | Reuse #96/#99; invalidate branch summaries |

## M37: controlled durable memory

[Milestone](https://github.com/mohripan/flint-graph/milestone/24) ·
[Tracking issue #151](https://github.com/mohripan/flint-graph/issues/151)

| Issue | Deliverable | Dependency/order |
| --- | --- | --- |
| [#152](https://github.com/mohripan/flint-graph/issues/152) | Versioned summaries, selected compaction and prior recall | #75, #143, #147; coordinate #149 branch invalidation |
| [#153](https://github.com/mohripan/flint-graph/issues/153) | Opt-in scoped memory with review/edit/erase controls | #143, #145 |
| [#154](https://github.com/mohripan/flint-graph/issues/154) | Accepted canon slices and character knowledge | #125, #126, #143; coordinate #145 |
| [#155](https://github.com/mohripan/flint-graph/issues/155) | Poisoning, self-reinforcement and cross-scope tests | #152–#154; reuse #74/#81 security gates |

PostgreSQL owns accepted memory; retrieval/LangGraph stores are projections.
Memory remains context rather than evidence. Nothing is remembered or shared
implicitly, and inference KV state (#83) is a separate ephemeral layer.

## M38: visual novel presentation, package v2

[Milestone](https://github.com/mohripan/flint-graph/milestone/25) ·
[Tracking issue #156](https://github.com/mohripan/flint-graph/issues/156)

| Issue | Deliverable | Dependency/order |
| --- | --- | --- |
| [#157](https://github.com/mohripan/flint-graph/issues/157) | Package v2/stage/save design and explicit migration ADR | #122, #124, #128; before v2 code |
| [#158](https://github.com/mohripan/flint-graph/issues/158) | Layered characters, expressions and outfits | #157, #128; coordinate #125 canon |
| [#159](https://github.com/mohripan/flint-graph/issues/159) | Studio 2D character creator | #158 |
| [#160](https://github.com/mohripan/flint-graph/issues/160) | Multiple positions, entry/exit and speaker focus | #158 |
| [#161](https://github.com/mohripan/flint-graph/issues/161) | Background variants, CGs and gallery | #157, #128 |
| [#162](https://github.com/mohripan/flint-graph/issues/162) | Bounded effects and reduced-motion transitions | #160, #161 |
| [#163](https://github.com/mohripan/flint-graph/issues/163) | Music, ambience, SFX and volume controls | #157, #128 |
| [#164](https://github.com/mohripan/flint-graph/issues/164) | Themed player and standard VN controls | #157 |
| [#165](https://github.com/mohripan/flint-graph/issues/165) | Named/customizable protagonist | #158 |
| [#166](https://github.com/mohripan/flint-graph/issues/166) | Real cross-runtime stages/saves/performance parity | #160–#164; include #165 coverage |

Existing v1 packages, immutable releases and saves stay valid. Migration creates
an explicit new revision; no silent rewrite of old exports. Use approved assets,
data-only staging and bounded formats, with no arbitrary scripts/shaders or remote
assets. Manual uploads must work without a model. The shared runtime needs actual
Python/browser/Godot parity and accessibility qualification. #167 specializes #129
for consistent v2 art; it does not bypass asset review or model-call budgets.

## M39: expressive and cloned character voices

[Milestone](https://github.com/mohripan/flint-graph/milestone/26) ·
[Tracking issue #173](https://github.com/mohripan/flint-graph/issues/173)

| Issue | Deliverable | Dependency/order |
| --- | --- | --- |
| [#174](https://github.com/mohripan/flint-graph/issues/174) | Evaluate, pin and isolate local cloning/expressive voice models; ADR | ADR 0043; first |
| [#175](https://github.com/mohripan/flint-graph/issues/175) | Private voice references with a consent declaration | ADR 0043; parallel with #174 |
| [#176](https://github.com/mohripan/flint-graph/issues/176) | Character voices cloned from an approved reference | #174, #175 |
| [#177](https://github.com/mohripan/flint-graph/issues/177) | Per-line delivery (emotion and intensity), defaulting from the line's expression | #174; coordinate with #176 |
| [#178](https://github.com/mohripan/flint-graph/issues/178) | Per-character model choice, license acceptance, release notices and a player license screen | #174 |

[ADR 0043](../adr/0043-asset-folders-and-line-voices.md) delivered line voices with
Kokoro-82M, which has fixed English voices and no emotion control. Kokoro stays the
default; other models are opt-in per character. Cloning needs a recorded consent
declaration, references are private project data that never ship, and weights must
allow use in released games. A model whose license puts duties on generated audio
(IndexTTS2 treats its output as a derivative work) is offered only after the creator
accepts its license; releases then carry its notices and a player license screen.
No paid or remote voice service is required.

## Current sequencing

Finish #124's bounded v1 builds/publication/download/UI qualification first. Then
land #134 → #135 before #126, while independent canon (#125) and asset (#128)
foundations can proceed. Context planning/manifests support assistant and memory
work; #157 follows #124/#128 and pins v2 before presentation changes. Complete
M38 parity before claiming the final #132 game. These are dependency priorities,
not permission to call planned work complete or to resume the old financial queue.

Platform work is embedded in #124/#131; engine/developer tooling is #119/#121/#131.
The older platform milestones remain available for relevant reusable work, rather
than requiring a new telemetry or inference stack for this pivot. Historical
financial/research issues remain open with their previous evidence intact.
