# Chat-to-game assistant: conversational authoring through reviewed proposals

Status: approved by the user on 2026-10-30 ([ADR 0038](../../adr/0038-conversational-authoring-through-reviewed-proposals.md)). Implementation starts after #124
lands, because both change the Studio page. Tracking issue: #168. Scope re-sequences a usable subset of
#150 (project assistant threads) and #126 (bounded proposal jobs and reviewed diffs)
ahead of the M35 prompt-management prerequisites #134/#135; those later issues
replace this design's in-code prompt templates without changing its data contract.

## Direction change and invariants

The user decided on 2026-10-30 that creating a game by chatting with a model is the
primary creator workflow. ADR 0035 rejected a chat-first core workflow; a new
ADR 0038 supersedes that single choice. Every other ADR 0035/0036 invariant stays:

- Model output is a **proposal** against an immutable base revision. Nothing reaches
  story canon until the creator explicitly accepts it; acceptance creates a normal
  append-only revision through the existing base/idempotency/conflict contract.
- Model and tool output are data, never instructions. Proposals are labelled as
  assistant suggestions in history and remain distinguishable from manual edits.
- Manual authoring, playtest, releases and exported games work with no provider.
  Exports contain no prompts, threads or proposals.
- Model calls run as bounded durable jobs on Temporal (provider calls in activities),
  not inside an API request. Concurrency defaults to one turn per workspace.

## Creator experience

The Studio gains an **Assistant** panel docked beside the editor (desktop) or as a
full-screen sheet (mobile). The creator types requests such as "add a scene where
Oren refuses to help unless the player found the rope" or asks questions about the
story. Each assistant turn returns a short reply and, when changes are requested, a
proposal card:

- One-line summary plus a change list: added / changed / removed scenes, characters
  and state variables, each expandable to the proposed text.
- "Show on map" highlights touched scenes in the existing route map.
- **Accept** creates a revision and loads it into the editor; **Reject** discards;
  **Refine** pre-fills a follow-up message. Undo is the previous revision.

Proposals target saved revisions. With unsaved edits the panel asks the creator to
save first (one click), mirroring Releases. A proposal whose base is no longer the
head is rebased when none of its touched IDs changed since the base; otherwise
acceptance returns the existing conflict-revision behavior, keeping both versions.
Viewers can read threads but cannot send messages or accept.

## Provider interface

A new provider-neutral port, separate from the GraphRAG answer/support protocols:

```text
NarrativeAssistantModel.respond(messages, response_schema, limits) -> AssistantOutput
```

`AssistantOutput` carries the parsed JSON object plus input/output token counts and
the provider/model identity. Adapters:

- **Ollama** (default for development): `/api/chat` with a JSON-schema `format`,
  explicit `num_ctx`, temperature and timeout. A live probe on 2026-10-30 with the
  locally installed `gemma-4-12B` QAT model produced a valid 4-node branching
  proposal with no dangling references at ~46 tokens/s on an RTX 5070 Ti (12 GB).
- **Anthropic** (switchable later, same contract): structured JSON validated with
  pydantic, matching the existing adapter style. Never selected implicitly.
- **Deterministic** recorded responses: forced when `env=test` and used by the
  offline gate.

Settings: `FLINT_GRAPH_NARRATIVE_ASSISTANT_PROVIDER` (`ollama|anthropic|deterministic`,
default disabled outside test), `..._OLLAMA_MODEL`, `..._OLLAMA_CONTEXT_TOKENS`
(default 16384), `..._MAX_OUTPUT_TOKENS`, `..._TURN_DEADLINE_SECONDS` (default 180).
The Ollama base URL reuses `FLINT_GRAPH_OLLAMA_BASE_URL`. Provider telemetry gets a
new operation value; it records counts and identities, never story or chat text.

## Proposal format: edit operations, not whole stories

The model returns `{reply, proposal | null}` where `proposal = {summary, operations}`.
Operations (at most 64 per proposal) apply to the base story server-side:

| Operation | Effect |
| --- | --- |
| `upsert_node {id, node}` | Add or replace a line/choice/end/set/branch node |
| `delete_node {id}` | Remove a node; references must be retargeted in the same proposal |
| `upsert_character {id, name}` / `delete_character {id}` | Cast changes |
| `upsert_variable {id, declaration}` / `delete_variable {id}` | Story state |
| `set_entry {id}` / `set_title {title}` | Story header |

Missing `text_id`s are derived deterministically (`<node>_text`, `<option>_option`).
Operations keep proposals bounded and reviewable for stories with thousands of
scenes, avoid regenerating unrelated text, and give an exact diff.

Validation: the server applies the operations to a copy of the base story and runs
a new **collecting** validator (up to 50 diagnostics instead of fail-fast) built on
the existing `validate_story` rules and package limits. On failure it sends the
diagnostic codes/locations back to the model for at most two repair attempts. A
proposal that is still invalid is stored as `invalid` with its diagnostics and is
never acceptable. Structural warnings (unreachable scenes, cycles) are shown on the
card but do not block acceptance.

## Context assembly

Each turn sends, within a character budget derived from the context setting:

1. Fixed system instructions (versioned template `narrative-assistant/v1`; its
   SHA-256 is stored on every proposal as a precursor to the #135 catalog).
2. Story header, characters, variables and a compact outline: every node's ID, type,
   speaker, first ~80 characters and edges. Large stories truncate the outline
   farthest from the focus scene first.
3. Full text of the focus scene (the one selected in the editor) and its neighbors.
4. The last turns of this thread (bounded), clearly marked as conversation history.

Only the current project's saved base revision is used: no other projects, drafts,
documents or memory. Lore documents (#125) and memory (#152–#155) attach later.

## Data model and API

Migration 0020 adds project-scoped tables (not the GraphRAG conversation ledger,
which is tenant-scoped and tied to query runs):

- `narrative_assistant_threads`: tenant, project, author, title, timestamps, archive.
- `narrative_assistant_messages`: thread, monotonic sequence, role (`user|assistant`),
  bounded content (8 KB), base revision and focus node for user turns, status for
  assistant turns (`queued|running|completed|failed|cancelled`), error code.
- `narrative_assistant_proposals`: message, base revision, status
  (`ready|invalid|accepted|rejected`), operations, summary, diagnostics, provider,
  model, prompt hash, token counts, accepted revision ID.

Routes under `/v1/narrative/projects/{project_id}/assistant` (member to write,
viewer to read, foreign IDs 404): create/list threads; post a message (202, with an
idempotency key; writes message + outbox in one transaction); list messages after a
sequence (polling, `no-store`); cancel a running turn; accept (idempotent, returns the
new revision or the existing 409 conflict payload); reject.

Execution: the existing outbox relay starts `NarrativeAssistantTurnWorkflow` on a
separate `narrative-assistant` task queue with ID-only payloads. One activity loads
the context, calls the provider with heartbeats, validates/repairs and persists the
reply and proposal in one transaction. Ownership fences and recovery reuse the
ADR 0037 pattern from releases. A dedicated worker process keeps model calls away
from the Godot build worker.

## Out of scope (separate follow-ups)

- **Scene organizer**: chapters, drag-and-drop ordering and compact cards for
  set/branch steps, stored as editor-only metadata. Hide Ask/Documents in the
  Studio navigation at the same time.
- **Generated assets**: anime characters/backgrounds (Animagine XL 4.0), voices
  (Kokoro-82M) and music (ACE-Step 3.5B), downloaded with pinned revisions and
  verified hashes under ignored `notes/models/`. They feed the asset library (#128)
  and need package v2 (#157) before they can ship in a release.
- Token streaming of replies (MVP shows turn progress; streaming follows), Langfuse
  prompt management (#134+), canon/lore sources (#125), memory (#152+).

## Tests and qualification

Tests come before behavior at each seam: operation application and text-ID
derivation; collecting validator parity with `validate_story`; context budgeting
and template hashing; provider adapters against recorded HTTP; repair-loop bounds;
API roles, foreign IDs, idempotency and stale-base rebase/conflict; workflow fences,
cancellation and recovery; frontend proposal/diff models. The offline gate uses
deterministic recorded proposals. Live qualification uses the local Ollama model on
real PostgreSQL/Temporal: chat in the browser, accept a proposal, playtest the new
route and build a release, with exact passed/skipped commands recorded.
