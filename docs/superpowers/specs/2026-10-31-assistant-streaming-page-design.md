# Full-page story assistant with durable live turns

Status: designed 2026-10-31 for #171 (streamed replies), extending
[ADR 0038](../../adr/0038-conversational-authoring-through-reviewed-proposals.md) and the
[chat-to-game design](2026-10-30-chat-to-game-assistant-design.md). Prompt v2,
base-accurate diffs and story questions remain separate #171 items.

## Problem

Turns run 10–100 s on the local 12B model and the Studio panel shows only "Writing
a reply…" until the turn ends. The panel is also a narrow column beside the editor.
Creators should see the reply, the model's thinking and each step as they happen,
on a chat page with room for long conversations.

## Creator experience

- **Assistant page.** The Studio header's **Assistant** button replaces the editor
  with a full-height chat page for the open project: a conversation list with
  **New chat** on the left (a drawer on phones) and a large chat column with the
  composer pinned at the bottom. **Editor** returns to the writing desk. The view
  and the selected conversation are remembered per project, so a reload returns to
  the same chat. Viewers can read; members can write.
- **Live turn.** Under the creator's message the assistant shows an activity
  timeline: *Read the story* (scenes included/omitted, focus scene), *Thinking*
  (streamed text, collapsible), *Writing the reply* (streamed reply text), *Drafting
  changes* (live edit count), *Checking the changes* (valid, or the first problem
  codes), *Fixing N problems (attempt 2 of 3)*. Stop stays available.
- **Finished turn.** The stored reply and the proposal card (Accept / Reject /
  Refine, unchanged contract). The timeline collapses to "Worked for 34 s" and
  can be reopened; its events load on demand.
- New conversations are titled from the first message (200-character limit).

## Durable turn events (migration 0023)

`narrative_assistant_turn_events`: tenant/project/thread/turn scope (composite FK
to the turn), per-turn `sequence` (unique), `attempt` (activity attempt),
`kind` ∈ `step | thinking | text | status`, bounded JSON `payload`, `created_at`.

- **Writers are fenced.** The worker appends only while it owns the turn: each
  flush locks the turn row, checks `running` + execution token, allocates the next
  sequences under that lock and commits. A lost fence stops the model call; a
  requested cancellation stops it within one flush instead of the next heartbeat.
- **Terminal event in the same transaction.** Every transition to completed,
  failed or cancelled (complete, fail, abandon, claim-time and queued
  cancellation, recovery) appends one `status` event with the status and safe
  error code. Streams end on it; a claim appends `step start` with the attempt so
  clients discard text from an abandoned attempt.
- **Batched and bounded.** Deltas are coalesced per kind and flushed every 0.35 s
  or at 2,000 pending characters; steps flush immediately to keep order. Rows hold
  at most 4,000 characters; a turn keeps at most 64,000 thinking characters,
  16,000 reply characters and 1,500 rows. Overflow drops further deltas of that
  kind after one `step truncated` event. Events stay with the turn as its record.
- **Temporal stays IDs-only.** Events are written from inside the activity to
  PostgreSQL; workflow inputs, results, heartbeats and the outbox are unchanged.

## Steps and streamed text

`run_turn` takes an optional observer (domain protocol, no database) and reports
`context`, `model`, `drafting`, `validating`, `repair` and `truncated` steps with
counts and diagnostic codes only. Providers take an optional delta callback:

- **Ollama** streams `/api/chat` NDJSON with the same JSON-schema `format`. The
  whole call keeps the per-call deadline. Ollama 0.32 thinks by default on
  thinking-capable models when `think` is omitted; a live probe on the lantern
  fixture exhausted the 4,096-token budget in thinking and produced no answer.
  The adapter therefore always sends `think` explicitly:
  `FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING` (default true) enables it only when
  `/api/show` reports the `thinking` capability (checked once per adapter), and
  adds `FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING_TOKENS` (default 8,192) to both
  `num_predict` and `num_ctx`. Measured on the same request: thinking 99 s, off 11 s,
  both valid. Turning thinking off is the latency switch.
- **Reply text** is extracted from the streamed JSON by an incremental scanner that
  follows only the top-level `reply` string (escapes and split surrogates
  included); the proposal is never shown raw. The scanner also counts operations
  opened inside `proposal.operations` for the drafting step.
- **Anthropic** stays non-streaming (opt-in, untested live); steps still stream.
- **Deterministic** replays scripts in chunks so tests cover the streaming path.

Prompt text and response schema do not change, so `narrative-assistant/v1` and its
pin stay valid.

## API

- `GET …/threads/{thread}/turns/{turn}/events?after_sequence=&limit=` (JSON, ≤ 500).
- `GET …/threads/{thread}/turns/{turn}/events/stream?after_sequence=` (SSE). Also
  honors `Last-Event-ID`. The dependency session is committed before streaming;
  each poll (0.25 s) uses its own short session. The stream ends after the
  terminal event, or when the turn is terminal and caught up (turns from before
  this change have no events), with a keep-alive comment every 10 s and a
  5-minute maximum after which clients reconnect from the last sequence.

Both are tenant-scoped reads (viewer and above) and return 404 for foreign turns.

## Frontend

New assistant-owned modules: `AssistantPage.tsx`, `assistantStream.ts` (fetch-based
SSE with the tenant header, resume from the last sequence, backoff, access-loss
and 404 handling) and pure event folding in `assistantModel.ts`. The old panel and
its `with-assistant` layout are removed; assistant styles move to `assistant.css`.

## Tests first

Scanner (keys, nesting, escapes, split chunks), observer steps for valid, repaired,
invalid and answer-only turns, Ollama streaming/thinking/capability/deadline with
a mock transport, fenced/bounded/batched writer and terminal events on every
transition, events and SSE endpoints (resume, end, foreign 404, viewer read) on
SQLite and the owned PostgreSQL, no text in Temporal history (live), frontend
folding and stream parsing. Live: the page in the browser against local Ollama with
thinking, a reload mid-turn that resumes, and Accept creating a revision.
