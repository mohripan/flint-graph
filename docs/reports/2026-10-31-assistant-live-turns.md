# Full-page assistant with live turns: delivery and qualification

Scope: #171 "streamed replies", built on [ADR 0038](../adr/0038-conversational-authoring-through-reviewed-proposals.md)
and the [design](../superpowers/specs/2026-10-31-assistant-streaming-page-design.md).
Prompt v2, base-accurate diffs and story questions remain open #171 items. Only the
local Ollama model was called; no paid provider was used.

## Delivered

- **Assistant page.** The Studio header has an Editor/Assistant switch. The
  Assistant view replaces the editor with a full-height chat for the open project:
  conversations on the left with New chat (a drawer under 900 px), a centered chat
  column, a composer pinned at the bottom (Enter sends, Shift + Enter adds a line)
  and the optional focus scene. View and conversation are remembered, so a reload
  returns to the same chat. New conversations are titled from their first message.
  The right-side panel and its `with-assistant` layout are removed.
- **Live turns.** Each reply shows an activity timeline while it runs: read the
  story (scene counts and focus), writing the reply, drafting changes with a live
  edit count, the check against the story rules, and repair attempts. The model's
  thinking streams into a collapsible block and the reply text streams with a caret.
  Finished replies collapse to "Worked for …"; the latest one loads its summary at
  once, older ones when opened. Stop, proposal review and Accept/Reject/Refine are
  unchanged.
- **Durable events (migration 0023).** `narrative_assistant_turn_events` holds
  ordered steps, thinking and reply deltas and one final status per turn. Only the
  fenced owner writes; every terminal transition appends the status in the same
  transaction; a new attempt starts with its own `start` step so readers discard the
  abandoned attempt's text. Deltas are coalesced (0.35 s, then 1 s after 40 flushes)
  and bounded per attempt and turn, with rows reserved for steps. A requested stop
  ends the model call at the next write instead of the next heartbeat.
- **Streaming provider.** Ollama `/api/chat` now streams under the same per-call
  deadline. The turn loop extracts the reply from the streamed JSON with an
  incremental scanner, counts drafted operations and never shows raw proposal JSON.
  Anthropic stays non-streaming (opt-in); its steps and parsed reply still appear.
- **API.** `GET …/turns/{turn}/events` (JSON, by sequence) and `…/events/stream`
  (SSE with `Last-Event-ID`, keep-alives, a 5-minute cap and short per-poll
  sessions). Viewer and above, 404 for foreign turns. Temporal inputs, results,
  heartbeats and outbox payloads are unchanged and IDs-only.
- **Prompt.** Unchanged: `narrative-assistant/v1` and its pin still apply.

## Finding: implicit thinking on Ollama 0.32

Ollama 0.32.6 thinks by default on thinking-capable models when a request omits
`think`, and thinking tokens count against `num_predict`. On the lantern fixture
the previous request shape spent all 4,096 tokens thinking and returned no answer
(`invalid_response`). With `think: true` the same request was valid in 99 s, and
with `think: false` in 11 s. The adapter now always sends `think`: it is on when
`FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING` is true (default) and `/api/show` reports
the capability, and it adds `FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING_TOKENS` (8,192)
to both the output budget and the context window. Thinking off is the latency switch.

## Verification

Passed (exact commands under Gates below):

- New and updated tests first: scanner (chunking, escapes, surrogates, nesting),
  observable turn steps (valid, repaired, invalid, answer-only, unstreamed
  provider), Ollama streaming/thinking/capability/deadline/stop and safe failures,
  fenced writer (stale owner, stop, batching, splitting, truncation, row cap,
  slower cadence), terminal events on every transition, JSON and SSE reads (order,
  resume, follow until status, legacy turns, foreign 404, viewer read), frontend
  event folding, SSE parsing and reconnect.
- Assistant suites on SQLite and the owned PostgreSQL (migrated through 0023):
  50 passed, 1 SQLite-only skip.
- Live on the owned Temporal: 4 passed on both backends. Thinking and reply text
  are in PostgreSQL events while workflow history contains none of the request,
  story, thinking or reply. With the local gemma-4-12B QAT model and thinking on, a
  durable turn produced a ready proposal in 19.9 s (8 step, 13 thinking, 3 text rows).

Live browser qualification (isolated QA database on the owned PostgreSQL, own API
on 8111, own assistant worker and task queue, owned Temporal, local Gemma with
thinking on, built-in browser at 1280×800 and 375×812; the user's services were not
touched). Counts and timings are in
[`evidence/narrative-assistant-streaming-2026-10-31/live-turns.json`](evidence/narrative-assistant-streaming-2026-10-31/live-turns.json):

- On the 12-scene lantern story, a request for a footsteps scene with a choice and
  two endings showed "Read the story · 12 scenes · focus arrival" after 0.6 s,
  thinking from 10.5 s (13,870 characters), reply text at 92 s, live drafting
  progress (5 edits) and the validation step; ready in 101 s.
- Reloading the page mid-turn returned to the Assistant view and the same
  conversation, replayed the thinking so far and kept streaming.
- Accept created revision 3 (16 scenes, `arrival → footsteps_heard`); the header
  and the page showed it as saved.
- A second request in the same conversation used the accepted story and two
  earlier messages. Stop showed "Stopped." about 0.5 s after the click; the turn
  ended `cancelled` with a final status event (71 rows in 54 s).
- At 375×812: no horizontal overflow, the conversation drawer, a new chat titled
  from its first message, and a question answered without a proposal (78 s).

## Gates

Run on master (with 0022) plus this change in a clean worktree:

| Command | Result |
| --- | --- |
| `uv run pytest -q --tb=short` | 1538 passed, 77 skipped (explicit opt-in suites), 309 s |
| Assistant suites with `FLINT_GRAPH_NARRATIVE_PG_URL` and `FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE` | 56 passed, 3 skipped (SQLite-only and model-less cases) |
| Same live Temporal case with `FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL` | 1 passed (ready proposal, 19.9 s) |
| `uv run ruff check .` | passed |
| `uv run mypy` | no issues in 229 source files |
| `uv lock --check` | passed |
| `uv run flint-graph-eval run … --config-name deterministic` | passed (exit 0, recall@5 1.0, supported claims 1.0) |
| `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql` | 1,740 lines, 0022 → 0023 |
| `docker compose config --quiet` (and `--profile metrics`) | passed |
| `git diff --check` | passed |
| `npm test` / `npm run typecheck` / `npm run build` (frontend) | 67 passed / passed / passed |

## Known limitations and follow-ups

- Change lists still compare against the current saved story, so an accepted
  proposal lists its scenes as "changed" afterwards (base-accurate diffs, #171).
- Story questions get weak answers on prompt v1 (one reply ended on a colon);
  prompt v2 and cited story answers remain #171 items.
- Thinking makes local turns several times slower and can delay the first token
  while Ollama reloads a model for a different context size.
- Anthropic replies are not streamed yet.
- Vite hot reloads from parallel edits remounted the dev page twice during QA;
  the page recovered from persisted events. Final checks used a production build.
- Running deployments need `alembic upgrade head` (0023) before the new API and
  worker start; an older API simply has no events and the page falls back to the
  stored reply.
