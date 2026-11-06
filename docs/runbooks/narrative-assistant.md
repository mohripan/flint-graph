# Run the story assistant locally

The Studio's Assistant page lets a creator describe changes in plain language.
The model proposes bounded story edits; nothing changes until the creator accepts,
which creates a normal saved revision ([ADR 0038](../adr/0038-conversational-authoring-through-reviewed-proposals.md)).
Manual writing, playtest and releases keep working when the assistant is off.

## Moving parts

| Piece | Role |
| --- | --- |
| API | Records threads and turns, writes an IDs-only outbox row; never calls a model |
| `flint_graph.processes.narrative_assistant_worker` | Dispatches queued turns to Temporal, runs them, recovers abandoned ones |
| Temporal | Durable `NarrativeAssistantTurnWorkflow` on its own task queue |
| Model provider | Local Ollama by default; Anthropic only when chosen explicitly |

Requests, replies and story text stay in PostgreSQL. Temporal history, outbox
payloads, audit metadata and logs carry identifiers and counts only. While a turn
runs, the worker writes its live progress (steps, the model's thinking, reply text
and a final status) to `narrative_assistant_turn_events`; the API serves those rows
by sequence, so the page streams and resumes after a reload
([design](../superpowers/specs/2026-10-31-assistant-streaming-page-design.md)).

## Configure

Apply migrations first (`0020_narrative_assistant` adds the tables,
`0023_narrative_turn_events` the live progress):

```powershell
uv run alembic upgrade head
```

API and worker settings (environment variables):

| Setting | Default | Notes |
| --- | --- | --- |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_PROVIDER` | `deterministic` in test, else `disabled` | `ollama`, `anthropic`, `deterministic` or `disabled` |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL` | none | Required for `ollama`; name a model you already pulled |
| `FLINT_GRAPH_OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Use `http://127.0.0.1:11434` outside Docker |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_CONTEXT_TOKENS` | 16384 | Must fit context, history, instructions and output |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_MAX_OUTPUT_TOKENS` | 4096 | |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_CONTEXT_CHARS` | 24000 | Story outline budget; farthest scenes from the focus are omitted first |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_TURN_DEADLINE_SECONDS` | 180 | Per provider call, streaming included |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING` | false | Ollama only: `true` thinks when the model reports the capability, and is far slower |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING_TOKENS` | 8192 | Added to the output budget and the context window while thinking |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_MAX_ACTIVE_TURNS_PER_WORKSPACE` | 1 | Admission limit and worker concurrency |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_WORKER_ENABLED` | false | Worker process opt-in |
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_TASK_QUEUE` | `narrative-assistant` | Keep separate from the Godot build queue |

The worker also needs `FLINT_GRAPH_DATABASE_URL`, `FLINT_GRAPH_TEMPORAL_ADDRESS` and
`FLINT_GRAPH_TEMPORAL_NAMESPACE`. With `anthropic`, set `ANTHROPIC_API_KEY`; the
model defaults to `FLINT_GRAPH_ANTHROPIC_ANSWER_MODEL`. Each call is billed.

Choose a local model that fits your GPU. A 12B instruction model quantized to
about 7 GB (for example a Gemma 12B QAT build) produced valid proposals in
14–60 seconds on a 12 GB laptop GPU; a 24B model will spill out of 12 GB.

Thinking is the main latency switch, and it is off by default. Ollama thinks by default on
thinking-capable models when a request does not say otherwise, and thinking tokens count
against the output budget, so the adapter always sends `think` explicitly and budgets
thinking separately. Measured on a Gemma 12B QAT model over nine request types with the
exact output grammar: thinking off got 27 of 27 right with a 3 s median and 17 s worst
case; thinking on got 8 of 9 right with a 43 s median and 137 s worst case. That measured
doing the right thing, not prose quality, so `true` may still suit long creative writing.
See [the report](../reports/2026-11-06-assistant-library.md).

## Run

```powershell
uv run python -m flint_graph.processes.narrative_assistant_worker
```

Start the API with the same provider settings so it accepts turns. In the Studio,
open a project and choose **Assistant** under Studio in the left sidebar (on phones,
the Editor/Assistant switch in the header). The
page lists the project's conversations on the left (a drawer on phones) with
**New chat**, and the chat in the middle. Enter sends, Shift + Enter adds a line.
Save edits before sending; the assistant works from saved revisions.

While a reply runs, the turn shows its steps (reading the story, writing the reply,
drafting changes with an edit count, checking them, fixing problems), the model's
thinking and the reply text as they are produced. Finished replies collapse to
"Worked for …"; open it to see what the assistant did.

## Behavior and limits

Prompt `narrative-assistant/v4` asks focused follow-up questions when a new
character's name, clothes or intended image are missing. It returns a reply with
no proposal while clarifying. Established thread/profile details are reused;
explicitly delegating a choice lets the model make it. Transparent stage sprites
default to high resolution (2×); an explicit `hires: false` opts out. The default
is explained rather than asked as another required question. Sufficiently specified
background requests proceed directly to a proposal. This is model instruction,
qualified on the local model in the linked report; creators still review proposals.

## Generation

The assistant generates pictures and voices itself
([ADR 0061](../adr/0061-assistant-runs-generation.md)): character sprites and portraits,
backgrounds, expressions that repaint an approved picture's face, event CGs, and voices for
lines. Results appear in the chat with **Approve** and **Use**. They stay candidates until
the creator approves them, and story edits still need **Accept**.

**Generate automatically** in the composer is on by default and is remembered per browser.
When it is on, the worker starts each action with no page open. When it is off, each action
waits for a click. It applies per message and is stored on the turn.

| State | Meaning |
| --- | --- |
| `offered` | Waits for a click (automatic generation was off) |
| `waiting` | Needs something the proposal adds; starts when it is accepted |
| `pending` | The worker starts it when the queue has room; a full queue waits, not fails |
| `started` | Has a job |
| `blocked` | Could not start, with the reason shown; **Try again** retries it |
| `finished` | Its job ended, and the Activity log says how |
| `skipped` | The proposal was rejected first |

The API and the assistant worker both admit jobs, so the worker needs the same image, voice
and object-store settings as the API. Each start is an ordinary job: the same content policy,
credits, audit and outbox as Characters and Assets, and one job per action however many
times it is started. `GET .../assistant/proposals/{id}/actions` reads the state, and
`POST .../actions/{index}` starts or retries one.

Expressions and CGs use the character's stage sprite, else their portrait, else their newest
approved picture. With none, the action blocks and says to approve one. A voice action gives
a character with no voice the stock voice it names, or a default for their type. A voice the
creator chose is never replaced. A model with an unaccepted license blocks and says so.
Poses are not available to the assistant yet, and music does not exist in the product.

The schema constrains the model (per-operation shapes, `reply` and `op` first; see the
ADR), so wrong fields cannot be produced by Ollama. A character with a missing detail still
gets a question first (prompt v3's clarification rules are kept in v4).

- One reply at a time per workspace by default; a second send returns 429.
- Unusable model output is sent back with diagnostics for at most two repairs.
  - Each problem says what is wrong as well as where: a field that is missing (with
    its allowed values when they are fixed), or not allowed there.
  - A proposal that is still invalid is shown as "Can't be used" and cannot be
    accepted.
- Some model slips have one obvious meaning, so they are corrected without another call:
  - **Swapped field names:** a character suggestion's look written as `description`
    (or a background's place as `appearance`) is accepted under the right name.
  - **Sprites for pictures not made yet:** links to pictures that don't exist yet are
    dropped when the same proposal generates that character's pictures.
  - **Narration:** `speaker: narrator` (with no such character) becomes narration, a
    voice on a line with no speaker is dropped, and a full voice loses any stray `text`.
  - **Unusable actions:** an action still invalid after the repairs is left out when the
    story changes themselves are valid. The proposal says so.
  A typo in an existing sprite or any other broken story change still makes the
  proposal unusable.
- Accepting a proposal whose base is no longer current rebases it when none of the
  touched records changed; otherwise it is saved as a conflict revision and the
  current story is unchanged.
- Stopping a reply cancels the running model call, normally within a second: the
  worker sees the request on its next progress write. If a worker dies, the next
  attempt of the same workflow run takes over (the page drops the abandoned
  attempt's text); turns whose run closed are failed by recovery.
- Live progress is bounded per turn: at most 64,000 thinking and 16,000 reply
  characters per attempt and 1,500 rows, with the last 100 rows kept for steps and
  the final status. Longer thinking is marked as cut in the step list.
- The open conversation is in the link (`?project=…&thread=…`), and its ID shows
  next to the title (click to copy). A link opens that project and conversation;
  quote the thread ID when reporting a problem with a reply.
- On story format 2 (prompt `narrative-assistant/v2`) the assistant also sets a
  character's name colour, expression sprites and stage framing, writes stage
  nodes and line expressions, changes the theme, and uses approved library files by
  ID. The server adds each library file it uses to the story's assets and pins it by
  SHA-256. The model sees up to 120 approved library files and each character's
  saved appearance.

## The library

**Library** in the composer attaches characters and approved files to the next message
([ADR 0062](../adr/0062-attach-library-items-to-assistant-messages.md)). The model gets their
details under the IDs it must use, and files attached are never dropped by the 120-file limit
on what it otherwise sees. Up to 12 items per message. Approved results in the chat have
**Attach to message**. An item that is not in the story or not approved is refused with a
reason, and a refused message charges nothing.

## Child sessions

Conversations form a tree one level deep ([ADR 0063](../adr/0063-assistant-child-sessions.md)).
**New child session** in the chat header makes the next message start one under the current
conversation. The assistant can also start them with `start_child_session`, up to 8 per proposal,
when asked or for several large parts. They queue and run on their own, and each costs a reply's
credits. A child knows its task and what its parent did, and its parent's log and next turn
know what it did. Proposals in a child are reviewed as usual. Because the per-workspace reply
limit is shared, a message elsewhere can be told to wait while a session runs.

## Conversation history

A conversation is a fold over its append-only log, `narrative_assistant_thread_events`
([ADR 0060](../adr/0060-assistant-thread-event-log.md)). The model is told the last four
finished turns verbatim, with what became of each proposal, and older turns as one line
each. **Activity log** in the chat header shows the same events, and
`GET .../assistant/threads/{id}/events?after_sequence=` returns them. The database refuses
updates and deletes on this table; never work around that to fix data. Migration
`0045_assistant_thread_log` backfills existing threads.

## Troubleshooting

| Message | Check |
| --- | --- |
| "The local model isn't reachable" | Ollama is running and the base URL is reachable from the worker |
| "The model took too long" | A smaller model, a shorter request, or a larger turn deadline |
| "The assistant isn't configured on this server" | API provider setting is `disabled` |
| Turn stays "Waiting for the assistant…" | Worker process running, Temporal reachable, same task queue on API-side relay and worker |
| A long pause before "Thinking" appears | The model is loading; a different `num_ctx` (for example with thinking on) makes Ollama reload it |
| Steps appear but no text streams | A proxy is buffering `text/event-stream`; the page still shows the stored reply when the turn ends |
| "unsupported schema at schema_version" on a format 2 story | The assistant worker predates story format 2; restart it so it validates with the current code |

On Windows, if the Vite dev server serves an old stylesheet after edits, touch the
file or restart Vite; production builds are unaffected.


## Reviewed prompt catalog

Assistant instructions, provider/extraction templates and default image conditioning
and content policy use the reviewed catalog. Apply `0033_prompt_bundles`; queued
work retains its admission-time bundle. The default stays offline. Langfuse is an
optional authoring/refresh service with Viewer runtime credentials, no tenant-data
uploads, and no SDK tracing. See [prompt management](prompt-management.md) for
import, review, activation, diagnosis and rollback. Image TOML overrides remain
explicit in locked mode and cannot be combined with managed Langfuse mode.
