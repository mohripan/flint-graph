# Chat-to-game assistant: delivery and live qualification

Scope: #168 under [ADR 0038](../adr/0038-conversational-authoring-through-reviewed-proposals.md),
the [design](../superpowers/specs/2026-10-30-chat-to-game-assistant-design.md) and
[plan](../superpowers/plans/2026-10-30-chat-to-game-assistant.md). Commits 419e74f,
b2852e2, 0275071, 4f1c7d8, 1503099 and 0ace3e3 on master. Only the local Ollama
model was called; no paid provider was used.

## Delivered

- **Edits, not regenerated stories.** Typed operations (upsert/delete scene,
  character and variable; entry; title), at most 64 per proposal, stable and
  collision-free text IDs, applied to a copy of the base story and checked by the
  manual-save rules. The validator now collects up to 50 diagnostics; its first
  equals the manual-save error.
- **Model contract.** Pinned `narrative-assistant/v1` prompt and response schema
  (SHA-256 recorded per turn), focus-first context under a character budget with
  delimited, escaped story data, and bounded thread history. Each node type has an
  exact schema shape: a looser shared shape let constrained decoding mix fields.
- **Providers.** Ollama `/api/chat` with JSON-schema output (default), Anthropic
  opt-in, deterministic recordings in tests; failures become safe codes only.
  Unusable output is repaired at most twice; invalid proposals are kept, never
  accepted.
- **Ledger and API.** Migration 0020: threads, fenced turns, proposals. Requests
  only record intent with an IDs-only outbox row; one active turn per workspace
  under the workspace lock; accept rebases when touched records are unchanged,
  otherwise returns the existing conflict-revision contract.
- **Durable execution.** Assistant-only relay registering the accepted Temporal run
  before claims, heartbeating activity with bounded transient retries, shielded
  finalizer, recovery of turns whose run closed, and the opt-in
  `narrative_assistant_worker` process on its own queue.
- **Studio panel.** Conversations, progress with Stop, proposal cards with an
  added/changed/removed list, Accept/Reject/Refine, save-first, viewer read-only,
  shared access-loss scope; docked at ≥1200 px and a full-screen sheet below.

## Verification

Passed:

- `uv run pytest -q --tb=short`: 1471 passed, 75 skipped (after step 5).
- Assistant API and execution suites on SQLite and the owned PostgreSQL
  (`FLINT_GRAPH_NARRATIVE_PG_URL`): 38 passed, 1 SQLite skip, including a contended
  admission race (exactly one 202 and one 429).
- Live on the owned Temporal (`FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE`): 4 passed —
  connected completion with no request or story text in workflow history, and
  mid-call cancellation, on both backends. With
  `FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL` set to the local gemma-4-12B QAT
  model: 1 passed, a ready proposal through the full durable path in 20.6 s.
- Direct turn-loop probes with the same model: a scene/choice/ending insertion, a
  route question and a new gated state variable all valid on the first attempt in
  14–60 s.
- Frontend: `npm test` 47 passed, `npm run typecheck`, `npm run build`.
- `uv run ruff check .`, `uv run mypy` (211 files), `uv lock --check`, offline
  `alembic upgrade head --sql` (1312 lines), `docker compose config --quiet`,
  `git diff --check`, deterministic Acme evaluation unchanged.

Live browser qualification (owned API migrated to 0020, owned assistant worker,
local Gemma, built-in browser):

- In "Harbor bell release QA", the request "add a scene where Oren hears a second
  bell… answer with a lantern or stay silent…" returned a ready proposal in about
  40 s: opening changed; `distant_bell`, `bell_response` (choice) and
  `drifting_ship_end` added.
- Accept created revision 4; the editor loaded it as saved with the new scenes.
- The reference player completed opening → distant bell → choice
  (`signal_lantern` / `stay_silent`) → the new ending, with no structural warnings.
- A release of revision 4 completed through the owned build worker: source
  126,774 B, browser build 10,368,383 B, manifest 934 B.
- Unsaved edits blocked sending and offered Save; at 375×812 the panel was a fixed
  full-screen sheet with no horizontal overflow; the conversation survived reload.

Not verified: a visual canvas playtest of revision 4 in the isolated preview (the
browser pane was hidden, so screenshots did not render; the route was verified with
the reference player, which shares the runtime's parity tests), and any live
Anthropic call (offline-tested adapter only).

## Known limitations

- Replies sometimes say a change "was added" before acceptance; the card labels
  proposals clearly. Candidate wording fix for prompt v2.
- No token streaming yet; turns show progress and take 15–60 s on a local 12B model.
- Change lists compare against the current saved story, so labels on older
  proposals can differ from their original base.
- One active reply per workspace by default.
- Assets (art, voice, music) are out of scope until the asset library and package v2.

Follow-ups: #169 scene organizer and Studio navigation cleanup, #170 local generated
art/voices/music, #171 streamed replies, prompt v2, base-accurate diffs and story
questions.
