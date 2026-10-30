# Chat-to-game assistant implementation plan

Tracking: [#168](https://github.com/mohripan/flint-graph/issues/168).
Progress 2026-10-30: steps 1–3 delivered (edit operations, collected diagnostics,
pinned v1 prompt/schema, focus-first context, provider port with Ollama/Anthropic/
deterministic adapters, settings and the bounded repair loop). A live probe with the
local `gemma-4-12B` QAT model returned a fully valid 4-operation proposal in ~31 s
once the schema gave each node type an exact shape; a looser shared node schema let
constrained decoding mix fields across types. Through the real adapter and turn
loop, three requests (scene/choice/ending insertion, a route question, a new state
variable with a gated option) all succeeded on the first attempt in 14–60 s.
Prompt v2 candidate: replies still sometimes say a change "was added".
The Anthropic adapter is offline-tested only; no paid call was made.
Step 4 delivered: migration 0020 (threads, fenced turns, proposals), ID-only
outbox/audit, one active turn per workspace under the workspace lock, accept with
untouched-record rebase or conflict revision, reject, cancel and execution fences.
Proven on SQLite and the owned PostgreSQL, including a contended admission race.
The running owned API still uses schema 0019; migrate it before serving step 6.
Step 5 delivered: assistant-only relay registering the accepted run before claims,
`NarrativeAssistantTurnWorkflow` with a heartbeating activity, bounded transient
retries and a shielded finalizer, fenced recovery of turns whose run closed, and the
opt-in `flint_graph.processes.narrative_assistant_worker` process. Live on the owned
Temporal: connected completion with IDs-only history and mid-call cancellation on
SQLite and PostgreSQL, and a real local-Gemma turn producing a ready proposal in ~21 s.
Step 6 delivered: the Studio Assistant panel (docked at ≥1200 px, full-screen sheet
below), conversations, turn progress with Stop, proposal cards with an added/changed/
removed change list, Accept/Reject/Refine, save-first for dirty drafts, viewer
read-only and shared access-loss scope. Live in the browser against the owned API
(migrated to 0020) and assistant worker with local Gemma: a request added a scene,
a choice and an ending (~40 s), Accept created revision 4 that the editor loaded, and
the reference player completed the new route with no structural warnings.

Scope/authorization: the [approved design](../specs/2026-10-30-chat-to-game-assistant-design.md),
[ADR 0038](../../adr/0038-conversational-authoring-through-reviewed-proposals.md) and the
user's 2026-10-30 approval. Starts after #124 lands. Local Ollama is the only live
provider during development; no paid model calls. Tests precede behavior at every
public seam. Preserve unrelated #109 WIP; stage explicit paths only.

1. **Story edit operations and diagnostics** (pure, no database). Add failing tests,
   then `narrative/assistant/operations.py`: typed operations, deterministic
   text-ID derivation, application to a copy of the base story, touched-ID sets,
   operation/size caps. Add a collecting validator that reports up to 50
   diagnostics with exact parity to `validate_story` on the first error.
2. **Context and prompt template.** Versioned `narrative-assistant/v1` template with
   a recorded SHA-256; compact outline with focus-first truncation under a character
   budget; bounded thread history. Golden tests pin rendered prompts.
3. **Provider port and adapters.** `NarrativeAssistantModel` with Ollama `/api/chat`
   JSON-schema output, Anthropic opt-in and deterministic recordings; settings and
   `env=test` forcing; recorded-HTTP adapter tests; provider telemetry operation.
   Bounded repair loop (max two) driven by collected diagnostics.
4. **Ledger and API.** Migration 0020 (threads, messages, proposals), services and
   routes: roles, foreign-ID 404s, idempotent message posting with an atomic outbox
   row, polling reads, cancel, accept (rebase when untouched IDs, else conflict
   revision) and reject. SQLite plus owned PostgreSQL constraint/concurrency proofs.
5. **Durable execution.** Relay dispatch to `NarrativeAssistantTurnWorkflow` on a
   separate `narrative-assistant` queue with ID-only payloads; heartbeating
   activity; fenced persistence; per-workspace concurrency of one; recovery per
   ADR 0037. Owned assistant worker process. Live Temporal plus local Ollama proof.
6. **Studio Assistant panel.** Thread list/log, message composer, turn progress,
   proposal cards with change list and map highlight, accept/reject/refine, save
   first for dirty drafts, viewer read-only, access-loss cleanup and mobile sheet.
   Frontend model tests, then real-browser qualification: chat, accept, playtest
   the new route and build a release with the local model.
7. **Docs and gates.** Runbook (configuring Ollama model/context), report with
   exact passed/skipped commands, milestone/roadmap/backlog/AGENTS updates and
   GitHub issues for this work plus the scene organizer, nav cleanup, local asset
   generation and voice acting follow-ups. Required gates and green CI per commit.

Each commit records the slice actually delivered. Never claim conversational
authoring complete from deterministic recordings alone.
