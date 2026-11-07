# ADR 0070: A GPU that sleeps

- Status: accepted
- Date: 2026-11-07
- Issues: #196, #197, #198 (Milestone 42, #195)

## Context

A GPU instance costs about $1 an hour whether it works or not. The first cloud deployment should pay
for it only while something is generating. That needs three things that did not exist:

1. Work must be able to wait while the machine is off. Each GPU worker relayed its own outbox rows, so
   a sleeping machine dispatched nothing, and nothing ever appeared that could wake it.
2. Something must start the machine when work is waiting.
3. Something must stop it once there is none, without cutting a job off.

## Decision

### The always-on tier dispatches

`narrative_gpu_dispatch` runs beside the API, needs no GPU, and runs one pass per second:

- **Actions:** `dispatch_actions` and `reconcile_actions`, first, so a job they admit reaches its queue
  in the same pass.
- **Relays:** every GPU outbox topic: image, pose, voice, style, music and assistant turns. Chat is GPU
  work too, since the assistant stays on a local model (#202).
- **Recovery:** once a minute. It only closes a job after seeing its own run closed, so a job
  waiting hours for a machine is never failed for waiting.

Each step has its own guard, so Temporal being away from one queue holds up no other.

`FLINT_GRAPH_NARRATIVE_GPU_EXECUTE_ONLY=true` makes GPU workers poll their task queues and nothing
else. Their heartbeat stays on, because that is how the Studio knows the machine is up (ADR 0069).

The laptop is unchanged: without these settings, each worker dispatches its own jobs. Both can overlap
during a rollout. Outbox rows are taken with `SKIP LOCKED`, and Temporal's workflow IDs are stable.

A queued job waits in Temporal with no schedule-to-start limit. Its workflow's own execution timeout
still applies: 30 minutes for a chat message or a music track, 2 hours for images. That is plenty for
a cold start. A longer outage fails the job visibly, and it is not refunded (ADR 0059).

### One controller starts and stops the machine

`narrative_gpu_controller` runs on the always-on tier, looks every 15 s, and is the only process
with permission to touch the machine. `decide` is a pure function of what it sees:

| Machine | Work queued or running | Does | Tells the Studio |
| --- | --- | --- | --- |
| stopped | none | nothing | `stopped` |
| stopped | some | starts it | `starting` |
| stopped | some, daily cap reached | nothing | `unavailable`, `daily_cap` |
| pending | any | nothing | `starting` |
| stopping | any | waits, and starts it again once stopped | `stopping` |
| running | some | nothing | `ready` |
| running | none, for under the idle period | nothing | `ready` |
| running | none, for the idle period (5 min) | stops it | `stopping` |
| running | past the max session (4 h) | stops it, raises an alarm | `stopping` |
| running | workers silent past boot grace | stops it, raises an alarm | `stopping` |
| running | daily cap reached | stops it, raises an alarm | `unavailable`, `daily_cap` |
| no such machine, or two | any | nothing, raises an alarm | `unavailable`, `instance_missing` |

The controller looks at the database, not at Temporal, so it also counts presses waiting for a free
slot. Asking EC2 for what is already happening changes nothing, so restarts and overlaps are harmless.

**Capacity.** On `InsufficientInstanceCapacity` it tries the configured second instance type, then waits
30 s, doubling to at most 5 minutes. Jobs keep waiting, and the Studio says no GPU is free.

**Daily cap.** `narrative_gpu_sessions` records each launch and when it was last seen up, so GPU hours
survive a controller restart. The default is 8 hours a day. Per-person credits still apply first.

**A job and a stop can cross.** Stopping only starts from a database with nothing queued or running. If
a job arrives during the stop, it stays queued, and the next look starts the machine again. If a
safety stop interrupts one, the existing retry and recovery fences apply and partial output is never
published.

**Least privilege.** Start, stop and describe on one tagged instance, plus changing that instance's
type if a fallback is configured. Credentials reach only this process, never the API or a browser.
The runbook has the IAM policy.

## Alternatives

- **A watchdog on the GPU host (as #198 first proposed).** It would need its own view of the queue, and a
  stopped machine cannot start itself anyway. One decision-maker has one view of the world and one
  place to test. The operating system's shutdown still stops the workers gracefully.
- **Temporal's task-queue backlog as the signal.** It misses presses waiting for a slot and work the
  dispatcher has not relayed yet, and PostgreSQL is already the source of truth.
- **A scheduled Lambda.** It would also work: a `tick` holds almost no state. The idle clock and retry
  wait are in memory, and losing them only delays a stop or retries sooner. A process is simpler
  beside an API that is always on.

## Consequences

- Not exercised on real AWS: no cloud spend is authorised, so EC2 is a fake in tests. #197 asks for one
  live start and stop in the user's account, which is still to do. Boot-to-ready time and idle cost
  (#198) cannot be measured until then.
- Still needed before this runs in the cloud: the machine image (#199) and the always-on tier (#200).
- A queued job for a kind with no deployed worker keeps the machine up until its workflow times out.
  The daily cap bounds what that can cost.
- A long training run longer than the max session is stopped and retried. Raise the limit before
  offering long runs.
