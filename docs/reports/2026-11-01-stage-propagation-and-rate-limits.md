# Complete stage analysis and bounded rate-limit state

The review identified a reproducible stage-analysis defect and general rate-state
gaps. These are code-review findings, not evidence of compromise.

## Stage analysis

The previous `stageBefore()` stopped after 200,000 work items without exposing
that propagation was incomplete. A valid-size 10,000-node fixture with 32 staggered
character alternatives and a long shared tail reached only **6,329 nodes** before
that cutoff. The public regression now requires all 10,000 nodes and every
alternative at the ending.

The implementation uses iterative reverse postorder to seed a de-duplicated FIFO.
Forward paths reach joins before their shared tails in acyclic graphs; cycles
requeue changed states until convergence. Dequeue uses a cursor, with occasional
compaction copying no more entries than have been consumed. Retained queue storage
is proportional to graph size; no recursive traversal or per-item `shift()` is
used. Structural joins compare background, CG, position, sprite and horizontal
center directly, copy characters only on change and return the previous object
when nothing changed. There is no serialized-state comparison.

Node inputs only lose precision: a known image/placement/absence can become `?`,
and an unknown value stays unknown at a join. Each reachable node has finitely
many such components. Transfers preserve this order, including slot replacement,
explicit hide/show, expression changes and image clears, so work reaches a fixed
point without a silent cutoff. Explicit stage writes can still produce known
outputs from varying inputs. Analysis follows every structural branch/choice
target, not condition satisfiability; the map is a conservative preview, not a
claim that every structural route is playable for the current variable values.

The regression's observed local runtime was roughly 12 ms after ordering, versus
roughly 597 ms for the old incomplete run; these single-run observations are not
a general latency guarantee. Dense cyclic graphs and large casts still cost more
than linear scripts. No new asynchronous worker or incremental cache is claimed.

Tests also cover loop convergence, hide/show and CG resets, agreeing versus
differing horizontal placement, unreachable nodes and unchanged authored input.
A separate red regression fixed a valid character ID `constructor` being mistaken
for an already-placed character through the object prototype. Story/runtime/save
formats and all concrete players are unchanged; no runtime bump is needed.

## Rate-limit design

Both pools now use expiry-ordered dictionaries and independent caps:
`rate_limit_max_buckets` and the existing `narrative_rate_limit_max_buckets`, each
defaulting to 10,000 and bounded to 1–100,000. Request hits leave window-start order
unchanged; expired prefixes are pruned on traffic without scanning the entire
pool. Admission/state updates occur before the next await. New identities at
capacity receive 429 with `Retry-After`, while active identities retain their
remaining request quotas. No live entry is evicted to free a slot. Expired entries
can remain during complete idle periods, but retained storage stays capped.

One shared public key builder groups dynamic paths under the configured route
prefix, hashes credential/dev/peer identity and canonicalizes workspace UUIDs.
OIDC mode ignores dev headers and normalizes bearer whitespace consistently with
the existing narrative path. Invalid workspace values coalesce. Bucket keys do
not retain authorization strings, unbounded paths or raw workspace headers.
Hashing is not authentication: token rotation can create another pre-auth
identity, and authorization remains downstream.

Counters are **per application process**, reset on restart and are independent
across replicas. No Redis/shared backend is introduced. Existing production
validation still requires explicit opt-in to memory limits; multi-replica
deployment requires qualified ingress enforcement or a future shared backend.
Capacity rejection trades bounded memory for possible delays to new callers
during identity churn. See [deployment hardening](../runbooks/deployment-hardening.md).

HTTP regressions reproduced the missing general cap and the OIDC dev-header/path
identity bypass before implementation. Tests cover saturation without active
eviction, exact expiry, hits not extending windows, independent pool capacities,
normalized identities/workspaces, different credentials/workspaces and two
independent application instances. Public key-builder tests check bounded keys
without raw credentials, including large synthetic headers.

## Terminal stream event drain

The initial full run failed an existing assistant HTTP stream test: all text
arrived, but the final status event was missing. This was a real READ COMMITTED
race, not a timeout assertion to relax. A finish could commit its event/status
between an empty event query and the subsequent terminal-status query, causing
the stream to close without draining that newly committed event.

A deterministic public-endpoint regression forces the real commit at that
boundary and reproduced an empty response before the fix. The API route now
re-reads events after observing a terminal status, then drains them using the
existing cursor/frame/page contract. Historical turns with no events and clients
already caught up still close normally. Core assistant services, workers and
proposal files were not changed. The eight stream/event tests passed after the
fix; the full suite and PostgreSQL variants run again below.

## Local Studio and verification

The configured existing persistent PostgreSQL database was migrated from 0032
through 0033 to 0034, verifying all five look tables, 13 foreign keys, query
indexes and prompt-bundle columns. No real project was opened or edited.

The user then authorized starting the app. The stopped existing storage/Temporal
containers and Ollama were started; the Studio runs from the isolated worktree
using a private configuration that preserves queues, model pins and the original
private build-work root. Main checkout files/configuration were not changed.
API 8101, preview 5192 and frontend 5173 returned HTTP 200. The launcher reported
all API/build/relay/assistant/image/voice/preview/frontend processes ready.
Optional CPU look tagging uses the already-qualified isolated WD environment.

After the stream fix, the full suite passed **1,940 tests / 122 skips**. The
task-owned PostgreSQL group passed **189 / 1 skip**, including both database
variants of the deterministic finish-race test. The only PG-group skip is the
SQLite variant of a PostgreSQL-only admission race. Pinned Godot/preview passed
**33 / 1 skip**. All **123 frontend tests**, Ruff, mypy (274 source files),
SQL generation, Compose configuration, frontend types/build and the offline
Acme evaluation passed. The required gates are repeated after rebase.

The first full run before the finish-race fix had 1 failed / 1,938 passed / 122
skipped; its missing final status event is reproduced and resolved above. A
repeat in progress was stopped before adding the deterministic regression.

```powershell
node --test tests/narrative-stage-model.test.mjs # from frontend
uv run pytest tests/integration/test_rate_limit_state.py tests/unit/test_rate_limit_key.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py -q --tb=short
uv run pytest tests/integration/test_narrative_assistant_events.py -q --tb=short
uv run pytest -q --tb=short
uv run ruff check .
uv run mypy
$env:FLINT_GRAPH_ENV='test'
uv run alembic upgrade head --sql
docker compose config
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

Live fixtures use the task-owned PostgreSQL container and pinned Godot binary;
the user's running Studio is not used as a test fixture. No model rendering or
new export/runtime qualification is claimed by these editor/middleware changes.

```powershell
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
uv run python notes/run-look-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py -q --tb=short
```

The private PostgreSQL wrapper creates/migrates/drops only a random database in
the task-owned `flint-codex-prompt-pg-final` on loopback 6192. Default-suite live
checks remain opt-in. The Godot prepared-builder CG release gate is skipped since
no runtime/export change needs a new builder, preview artifact or release build.
