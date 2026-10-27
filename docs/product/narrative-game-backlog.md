# Narrative game studio: GitHub delivery queue

Created: 2026-10-27. Five milestones and 21 issues (five tracking issues plus
16 focused implementation issues). All are planned and open at creation.

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
| [#126](https://github.com/mohripan/flint-graph/issues/126) | Bounded proposal jobs and reviewed revision diffs | #125, #124 |
| [#127](https://github.com/mohripan/flint-graph/issues/127) | Continuity findings and dependency-aware revisions | #126 |

## M33: controlled game asset production

[Milestone](https://github.com/mohripan/flint-graph/milestone/20) ·
[Tracking issue #115](https://github.com/mohripan/flint-graph/issues/115)

| Issue | Deliverable | Depends on |
| --- | --- | --- |
| [#128](https://github.com/mohripan/flint-graph/issues/128) | Uploaded asset library, approvals and provenance | #122 |
| [#129](https://github.com/mohripan/flint-graph/issues/129) | Bounded image variations and reviewed references | #128, #124 |

## M34: narrative game release qualification

[Milestone](https://github.com/mohripan/flint-graph/milestone/21) ·
[Tracking issue #116](https://github.com/mohripan/flint-graph/issues/116)

| Issue | Deliverable | Depends on |
| --- | --- | --- |
| [#130](https://github.com/mohripan/flint-graph/issues/130) | Reproducible routes and nightly black-box gates | #124, #127, #128 |
| [#131](https://github.com/mohripan/flint-graph/issues/131) | Build isolation, budgets, privacy, telemetry, DX and recovery | #124, #129 |
| [#132](https://github.com/mohripan/flint-graph/issues/132) | Complete original game and live qualification report | #130, #131, #129 |

Platform work is embedded in #124/#131; engine/developer tooling is #119/#121/#131.
The older platform milestones remain available for relevant reusable work, rather
than requiring a new telemetry or inference stack for this pivot. Historical
financial/research issues remain open with their previous evidence intact.
