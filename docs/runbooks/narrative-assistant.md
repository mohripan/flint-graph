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
| `FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING` | true | Ollama only: think when the model reports the capability; `false` answers directly |
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

Thinking is the main latency switch. Ollama 0.32 thinks by default on
thinking-capable models when a request does not say otherwise, and thinking
tokens count against the output budget; the adapter therefore always sends
`think` explicitly and budgets thinking separately. On the same request the Gemma
12B QAT model took about 99 s with thinking and 11 s without, both valid. Set
`FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING=false` for faster replies without the
visible reasoning.

## Run

```powershell
uv run python -m flint_graph.processes.narrative_assistant_worker
```

Start the API with the same provider settings so it accepts turns. In the Studio,
open a project and choose **Assistant** in the header (Editor/Assistant switch). The
page lists the project's conversations on the left (a drawer on phones) with
**New chat**, and the chat in the middle. Enter sends, Shift + Enter adds a line.
Save edits before sending; the assistant works from saved revisions.

While a reply runs, the turn shows its steps (reading the story, writing the reply,
drafting changes with an edit count, checking them, fixing problems), the model's
thinking and the reply text as they are produced. Finished replies collapse to
"Worked for …"; open it to see what the assistant did.

## Behavior and limits

- One reply at a time per workspace by default; a second send returns 429.
- Unusable model output is sent back with diagnostics for at most two repairs. A
  proposal that is still invalid is shown as "Can't be used" and cannot be accepted.
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

## Troubleshooting

| Message | Check |
| --- | --- |
| "The local model isn't reachable" | Ollama is running and the base URL is reachable from the worker |
| "The model took too long" | A smaller model, a shorter request, or a larger turn deadline |
| "The assistant isn't configured on this server" | API provider setting is `disabled` |
| Turn stays "Waiting for the assistant…" | Worker process running, Temporal reachable, same task queue on API-side relay and worker |
| A long pause before "Thinking" appears | The model is loading; a different `num_ctx` (for example with thinking on) makes Ollama reload it |
| Steps appear but no text streams | A proxy is buffering `text/event-stream`; the page still shows the stored reply when the turn ends |

On Windows, if the Vite dev server serves an old stylesheet after edits, touch the
file or restart Vite; production builds are unaffected.
