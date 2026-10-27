# Narrative game studio: product direction

Date: 2026-10-27. Direction and first implementation contract approved in
conversation. Delivery is tracked issue by issue; the complete studio is planned,
not delivered. See milestone reports for implemented boundaries.

## Product and audience

Build an AI-assisted authoring studio for independent developers making visual
novels and choice-driven narrative games. A developer owns an editable project:
characters, world facts, scenes, choices, state, assets and releases. The product
helps turn original writing into a playable game and maintain it through revisions.

The first engine is Godot using GDScript. Games have authored dialogue and choices
fixed in a release; players do not need an inference service, FlintGraph account,
or network connection to play an exported desktop project. AI assists production.
Runtime-generated NPC dialogue is a later, separately designed capability.

Success means a creator can build a 15–30 minute original game with at least three
reachable endings, test it in a browser, export an editable Godot project, and
reproduce the tested routes in that project. Duration is a human playtest target,
not an inference from word count. The product name remains FlintGraph for now.

## Creator workflow

1. Create a narrative project in an authorized workspace, optionally importing
   original prose and an approved world bible. Creating a blank game must not
   require a retrieval index, searchable documents, or an LLM.
2. Define characters, locations, relationships, secrets and initial state. World
   truth and what each character knows are separate records.
3. Edit scenes and branching choices through forms and a navigable story graph.
   Inspect conditions, state changes, references and validation errors directly.
4. Ask AI to propose an adaptation, branch or revision. Review a structured diff
   against a specific project revision; accept, edit or reject it.
5. Attach uploaded or generated artwork. Review variations and provenance before
   binding approved assets to scenes and character expressions.
6. Playtest, inspect state and route traces, resolve blocking errors, and create
   an immutable release. Download its Godot source project and browser build.
7. Revise the project. See dependent scenes, assets and test routes that need
   review; existing exports and saves stay tied to their original release.

Example: changing when the detective learns a secret identifies scenes referring
to that knowledge and proposes changes. It does not silently rewrite those scenes
or claim that an LLM has proven narrative consistency.

## Approaches considered

| Approach | Benefit | Cost and decision |
| --- | --- | --- |
| Portable story package and trusted Godot runtime | Explicit semantics, inspectable source exports, shared preview/runtime, room for another engine adapter | Requires a deliberately small runtime and cross-runtime conformance tests; selected |
| Use an existing narrative language as the primary project format | Existing writing/runtime ecosystem | Visual staging, asset bindings, revision proposals and project metadata still need a surrounding contract; evaluate import/export adapters later |
| Generate arbitrary engine code from prompts | Broad apparent flexibility | Hard to reproduce, secure, revise and support; excluded from the initial product |

[Ink](https://www.inklestudios.com/ink/) already provides branching narrative and
engine integration. The differentiation to validate with creators is the connected
workflow: source material, explicit game logic, assets, reviewed revisions,
playtesting and reproducible export. It is not a claim that this market is empty.

## Architecture and ownership

```text
Original prose / world bible / creator edits
                  |
         Authorized studio APIs
                  |
 PostgreSQL projects, revisions, proposals, job and release ledgers
          |                         |
    Approved story package      Bounded authoring jobs
          |                    retrieval -> proposals -> review
     Validation/compiler             |
          |                    Immutable artifacts in MinIO
     Release manifest <--------------+
          |
 Trusted Godot runtime + content + asset manifest
          |
 Browser preview / downloadable editable Godot project
```

Keep the existing modular monolith. Add explicit narrative domain modules rather
than changing query-run records into game state. PostgreSQL remains authoritative;
MinIO holds immutable packages, assets and build artifacts. Neo4j and OpenSearch
can assist lore discovery after project-scoped retrieval is implemented; they are
not required to play, edit a blank game, or evaluate a choice.

Existing workspaces and OIDC membership are reusable authorization foundations,
but projects require their own workspace-consistent foreign keys and authorization
tests. Documents attached to one project are not automatically available to
another project in the same workspace. Explicit revision-scoped source attachments
bound authoring retrieval. Source text, model output and tool output remain data,
not instructions capable of granting access or approving changes.

Reuse immutable storage, transactional outbox and Temporal for future authoring,
art and export jobs, with job-specific state and bounded retries. Workflows carry
authorized durable references; provider calls run in activities. Request-bound
query SSE is not a durable authoring executor. LangGraph may implement bounded
agent steps without becoming the source of truth for approved project content.

Creative proposals and factual source inspection are distinct operations.
Citation-backed source answers retain existing faithfulness behavior. Fiction may
invent content, but must identify it as a proposal and validate project rules;
fiction does not need a factual-source support score to be authorable.

## Authoring assistance and memory

Introduce agent roles incrementally, after manual authoring and export work:

| Role | Authorized output | Checks |
| --- | --- | --- |
| Narrative designer | Scene/choice proposal against a base revision | Schema, references, scope, state transitions |
| Continuity editor | Evidence-linked findings and proposed revisions | Character knowledge, timeline, approved canon; uncertainty visible |
| Art assistant | Asset request/variation and binding proposal | Reference versions, dimensions, provenance and creator approval |
| Playtest assistant | Suggested routes and reports | Deterministic replay; sampled coverage explicitly labeled |

A coordinator may schedule these tasks with parent-wide model-call, token, cost,
deadline and concurrency bounds. Default concurrency is one until accounting and
cancel/retry behavior are qualified. No arbitrary recursive delegation, shell,
user-provided engine scripts, or automatic publication. Each proposal names its
base revision; acceptance of a stale proposal returns a conflict and preserves
both versions. Private chain-of-thought is not stored as a product artifact.

Memory is approved canon plus revision-scoped facts, character knowledge, source
attachments and explicit dependencies. A prior chat answer cannot silently become
canon. Cached context keys include workspace, project, revision, permissions and
provider/prompt identity; cache reuse is an optimization, not memory authority.

## Asset and export boundaries

Uploaded placeholder art makes the first playable game possible without an image
model. Generated art later records provider/model, prompt and reference versions,
seed when available, license/rights declarations, hashes and approval state.
Recording a declaration does not certify ownership. Assets require explicit
project attachment; tenants do not share private reference-image caches.

Exports are snapshots with schema/compiler/runtime/engine versions, content and
asset hashes, notices and build reports. Secrets, source credentials, private
drafts and provider prompts are excluded by default. Downloaded game source uses
a trusted runtime template with explicit extension points. Re-export creates a
new directory/archive; arbitrary developer engine edits are not reverse-imported
or overwritten. A future Unity adapter consumes the portable package; it is not
included in the first engine milestone.

Server-side Godot imports/builds run in isolated, bounded workers with no provider
credentials, application network access or arbitrary user scripts/plugins. Browser
preview uses an isolated origin without application cookies and a narrow message
protocol. Hosted preview needs separate review of embedding, storage and asset
access. Desktop source export and hosted browser publishing are separate actions.

## Delivery sequence

| Milestone | Deliverable | Exit evidence |
| --- | --- | --- |
| 30: portable story runtime and Godot proof | Small versioned story package, validator, reference interpreter, trusted runtime and export fixture | Real Godot import/playback, deterministic route/save conformance, no backend or model dependency |
| 31: authored game studio | Project/revision APIs, scene editor, browser preview, releases and downloads | Public-API and browser author/edit/test/export/reopen flow; workspace and project isolation |
| 32: reviewed narrative assistance | Source/world modeling, proposal jobs, continuity reports, dependency-aware revisions | Real bounded model capture plus deterministic acceptance/conflict/budget tests; human quality review |
| 33: controlled asset production | Asset library, reference versions, bounded image jobs, approval and export bindings | Uploaded-art baseline and opt-in real generation; export integrity, privacy and creator quality review |
| 34: playable release qualification | Representative complete game, route coverage, performance, recovery and release runbooks | Live browser and exported Godot game, three reachable endings, measured 15–30 minute playtest, qualified release report |

M30 precedes M31. M32 and M33 can progress independently after M31's project,
revision and job boundaries are available. M34 qualifies their combined result;
the manual authoring/export product remains useful without enabling either AI
provider. There are no promised dates, inference throughput or art consistency
scores without measurement.

The first independently reviewable implementation design is
[the M30 story runtime specification](../superpowers/specs/2026-10-27-portable-story-runtime-design.md).
Later milestones each need a focused design before code changes.
The [GitHub delivery queue](narrative-game-backlog.md) links all five milestones,
their tracking issues and 16 focused implementation issues with dependencies.

## Quality, safety and developer experience

Offline PR gates use an original fixture and deterministic recorded proposals;
they do not claim real model quality. Live verification is required for each
implemented boundary: database authorization, Godot import/export, browser input,
durable interruption, and actual selected provider behavior. Missing binaries,
models, credentials or budgets are explicit skips and block the relevant release
acceptance, rather than being replaced with mock-only success.

New nightly game checks use held-out routes and known state outcomes, invalid
packages, cross-project attempts, stale proposals and save compatibility cases.
Story/art quality uses creator rubrics and human review; LLM judges are supporting
signals. Preserve the existing offline RAG gate during the additive transition.

Extend the existing agent threat model for unpublished IP, asset access, hostile
imports, generated code, archive traversal, build workers, preview origins and
cross-project memory. Reuse privacy-safe telemetry, correlate project/revision/
job/release IDs, and track queue time, build time, failures, usage and budgets.
Do not add an extra observability backend or switch inference servers to start
this track. A narrative doctor should eventually report required engine/templates,
storage and provider readiness separately; manual authoring must remain usable
when an optional provider is unavailable.

## Transition from the existing roadmap

Milestones 15–29 remain historical foundation and deferred backlog, with their
actual delivery records intact. They are not prerequisites as a group. Select
generic security, isolation, storage, job and observability work when a game
milestone needs it. Financial-specific enhancements, broad research features,
GraphQL, additional telemetry products, inference-server migration and generalized
runtime AI are deferred until supported by the new product's needs.

Do not delete financial/private documents, rename existing workspaces, reset
volumes, repurpose existing conversations or bulk-close old GitHub issues.
The uncommitted #109 trace-qualification work is preserved separately. No engine,
model, paid endpoint or new corpus is downloaded by this planning change.

## Reference review

Reviewed official documentation on 2026-10-27:

- [Godot web exports](https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_web.html):
  browser requirements, Compatibility renderer, single-threaded option, current
  Godot 4 C# limitation and audio constraints. Stable docs are mutable; the exact
  engine/template version must be pinned and qualified in M30's engine issue.
- [Godot command line](https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html):
  headless/editor/export tooling. Unknown command flags may be ignored, so success
  requires checking outputs and running the result, not exit status alone.
- [Ink](https://www.inklestudios.com/ink/): existing authoring, intermediate JSON
  and engine integration. Choosing the small initial package is a product-scope
  decision, not a finding that mature narrative middleware is insufficient.
