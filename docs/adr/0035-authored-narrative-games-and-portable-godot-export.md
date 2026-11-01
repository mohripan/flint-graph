# ADR 0035: Authored narrative games with portable Godot export

Date: 2026-10-27. Status: architecture and first implementation contract
accepted. This ADR records intent, not delivered behavior.

## Context

FlintGraph is a developer-facing narrative game Studio whose output is an
editable, playable game. The first release uses authored dialogue and branching
choices, with AI supporting creation rather than being required during gameplay.

Workspace authorization, immutable storage, provenance and durable ingestion are
shared platform services. Game runtime, visual authoring, export and image
generation require explicit narrative contracts. Request-bound query execution
and factual answer faithfulness cannot serve as the authoring job lifecycle or
the validity rule for creative fiction.

## Decision

1. Use a narrative domain separate from source Q&A. Keep PostgreSQL authoritative,
   existing identities and workspace membership, and immutable MinIO artifacts.
   Use project/revision scopes in addition to workspace scope.
2. Define a small engine-independent story package with typed deterministic
   state transitions. Use one reviewed GDScript runtime for Godot source export
   and browser preview; pin and qualify engine/templates before claiming support.
3. Establish package/runtime/export conformance before the studio, then add manual
   authoring, reviewed AI proposals, controlled assets and release qualification
   through milestones 30–34. Each subsystem gets its own focused design.
4. Make AI outputs proposals against immutable base revisions. Creator acceptance
   is explicit and conflict checked. Fiction can invent; approved canon, source
   inspection, model suggestions and character knowledge remain distinguishable.
5. Export snapshots with hashes/versions/notices and documented customization
   boundaries. Exported gameplay requires no AI service or platform account.
6. Defer runtime AI, Unity export, arbitrary generated engine code, engine-edit
   reverse synchronization, generalized delegation and new infrastructure
   products. Reuse existing infrastructure only when it serves a game milestone.

## Alternatives and consequences

An existing narrative language such as Ink is a viable future interoperability
target; it does not alone define the studio's asset, proposal and revision model.
The initial package is intentionally constrained. This creates runtime/compiler
maintenance and parity obligations, which M30 must prove before expanding scope.
Arbitrary engine code generation would increase build safety and revision costs
and is excluded. A chat-first product would not validate the chosen developer
workflow or the promise of a usable export.

Keep milestone evidence, data and delivered security contracts intact. Follow
the Studio dependency order when selecting work. Do not bulk-close existing
issues, remove private corpora or mix the uncommitted #109 trace-probe changes
into this work.

## References

- [Product direction and phased milestones](../product/narrative-game-studio.md).
- [M30 implementation design](../superpowers/specs/2026-10-27-portable-story-runtime-design.md).
- [Godot official web export guidance](https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_web.html), reviewed 2026-10-27.
- [Ink authoring and integration](https://www.inklestudios.com/ink/), reviewed 2026-10-27.
