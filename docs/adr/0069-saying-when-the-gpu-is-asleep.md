# ADR 0069: Saying when the GPU is asleep

- Status: accepted
- Date: 2026-11-07
- Issue: #201 (Milestone 42, #195)

## Context

The first cloud deployment runs a GPU that stops when idle and starts when work is queued. A first
request then waits a few minutes. Without a message that looks broken. The user asked for a message
wherever people generate, in chat as well as images: a little silly, and true.

The controller that starts the machine (#197) does not exist yet, and a laptop has no such thing.
Both need a true answer, and the message must never promise a wake-up nothing will perform.

## Decision

`GET /v1/narrative/gpu` answers from what the machine is doing:

- Each GPU worker keeps a row fresh in `narrative_gpu_status` while it runs (`gpu_heartbeat`). A worker
  silent for 60 s counts as gone. This needs no cloud API and works the same everywhere.
- The controller writes its own row with `record_gpu_state`: `stopped`, `starting`, `ready`,
  `stopping` or `unavailable`, with a detail such as `no_capacity` or `daily_cap`.
- `FLINT_GRAPH_NARRATIVE_GPU_SLEEPS` says a controller exists. `gpu_view` is a pure function of those.

| Situation | State | What people read |
| --- | --- | --- |
| Every worker this server uses is up | `ready` | Nothing |
| Sleeps, controller says stopped | `asleep` | "The GPU is taking a nap." |
| Sleeps, starting, or up with a worker still loading | `starting` | "Waking the GPU… it is not a morning person." |
| Sleeps, stopping | `stopping` | "The GPU was just dozing off." |
| Sleeps, no capacity | `unavailable` | "No GPU is free right now." |
| Sleeps, daily cap reached | `unavailable` | "The GPU has clocked off for today." |
| Sleeps, controller silent for 5 minutes or never seen | `unavailable` | "The GPU won't wake up." |
| Does not sleep, worker not running | `off` | "The picture worker isn't running." |

Every message says the request stays in line, and the ones about waking say why the GPU is off: to
save money. A wake-up time appears only if `FLINT_GRAPH_NARRATIVE_GPU_WAKE_SECONDS` was set from a
measurement; otherwise it says "a few minutes".

`waiting` lists only work this server is set up to run, so a server without voices never mentions
them, and a hosted assistant never waits for a GPU.

The Studio reads this once, for all views, every 20 s while the tab is visible:

- on a generation card;
- on a chat message that is waiting, and above the composer once someone starts typing;
- on an action that is queued or pending;
- at the top of Assets and Characters.

Writing, editing and playtesting say nothing and never wait.

## Alternatives

- **Ask Temporal for each queue's pollers.** It needs no table, but ties a page's reading to Temporal,
  and a laptop's API would need a new client. Rows also give the controller one place to write.
- **Ask EC2.** Only true in the cloud, and it would put cloud credentials near the API, which #197
  forbids.
- **A waiting reason on each job, as #192 plans.** That is the fuller design, for per-job queue
  positions. This is the honest message that does not need the GPU broker first. It reads no job.

## Consequences

- Setting `NARRATIVE_GPU_SLEEPS` without a controller shows "The GPU won't wake up", which is correct:
  nothing would wake it. #197 and #198 are still needed for the GPU to actually sleep.
- The worker's heartbeat should stay on the GPU host when #196 moves relaying to the always-on tier.
- A worker enabled in settings but never deployed reads as waiting, for that kind of work only.
