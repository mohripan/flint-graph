# A GPU that sleeps

Dispatch now runs on the always-on side, GPU workers can only execute, and a controller starts the machine
when work is queued and stops it when idle. See [ADR 0070](../adr/0070-a-gpu-that-sleeps.md) and the
[runbook](../runbooks/gpu-sleep-and-wake.md). This delivers the code for #196, #197 and #198.

**Nothing here has touched real AWS.** No cloud spend is authorised. The controller's decisions and EC2
calls ran against fakes; the dispatch split ran for real on this machine.

## Verification

### The dispatch split, for real

Real Temporal, PostgreSQL, the real assistant worker and the real local model, as three separate
launchers on an isolated stack, driven in this order:

| Running | Result |
| --- | --- |
| API only | A chat message stays `queued`, in the outbox, not on Temporal |
| API and dispatcher | Same message reaches Temporal and stays `queued`, with no GPU worker anywhere |
| Plus workers in execute-only mode | It runs, and the real model replied |
| Dispatcher stopped, workers running, 25 s | A new message stays off Temporal: the workers really do not dispatch |
| Dispatcher restarted | That message reaches Temporal and is answered |

### The controller, with a fake machine and a real database

- Every transition of `decide`: stopped, queued, booting, up, idle, stopping.
- The whole cycle: a chat wakes it, starting twice is avoided, it stays up through the idle period, stops,
  and a message arriving during the stop waits and wakes it again.
- No capacity backs off, grows, recovers, and tells the Studio.
- The daily cap counts real running time, keeps it stopped, and resets the next day.
- A silent machine gets its boot grace, then is stopped. So is one past its max session.
- The EC2 adapter touches only the one tagged machine, and nothing if two match. It falls back to a second
  type and returns afterwards. Any other refusal is not mistaken for capacity.
- The Studio reads what the controller recorded.

### Commands

- `uv run pytest`: 2372 passed, 140 skipped.
- `tests/integration/test_narrative_gpu_controller.py` and `test_narrative_gpu_dispatch.py` also pass on
  disposable PostgreSQL, which runs migration 0054.
- `uv run ruff check .`, `uv run mypy`, the offline eval gate, `uv run alembic upgrade head --sql` and
  `docker compose config`: pass.
- `npm --prefix frontend test`: 199 passed.

## Limits

- One live start and stop in the user's account (#197), and measuring boot-to-ready time and idle cost
  (#198), are still to do.
- #199 (machine image) and #200 (always-on tier) are still needed before this runs in the cloud.
