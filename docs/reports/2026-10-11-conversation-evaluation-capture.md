# Fresh ordered conversation capture qualification

Scope: #102 under #74/Milestone 27. Opt-in tooling over the existing public
conversation/query API, not general memory or full nightly quality acceptance.
Standalone capture format 2 and nightly defaults remain unchanged. Format 3
records real conversation/turn/run identities, declared limits and observed
context. Original questions execute sequentially without a client transcript.

HTTP-boundary tests cover freshness, tenant/UUID/order/key/question/run checks,
stable index before execution, final reference checks, authorization/conflict
fail-stop, incomplete runs, finite prevalidated bounds, total deadline including
creation/turn execution, and existing offline recording/CLI compatibility.
New behavior had a failing regression before implementation. No automatic POST
retry, saved-chat reuse, cleanup, silent truncation or accepted-baseline change.

## Fresh public API/model evidence

The draft financial-conversation-smoke and financial-conversation-reset datasets
ran through the actual CLI with 90-second turn / 240-second total limits. Each
created a fresh conversation in existing public workspace
`2eab2f78-208e-4eb9-97a2-087e40af0525`, active index
`fc8aa4e9-6b7f-4283-99cf-efc850a472e1`. No private document query, upload,
deletion, index/provider switch or new paid service occurred.

Independent checks used the pinned FinQA revision
`0f16e2867befa6840783e58be38c9efb9229d742`, PM 2017 excerpt page 38,
SHA-256 `f4d992784b64c3c93b3725ab4dad90cd75c51cda2b7aa0855f30fd1b44e72115`.
These are historical excerpts, not complete annual reports or financial advice.
Verified source hash, year, revenue concept, value/unit, citation target and
active provenance separately from the generic offline scorer.

| Run | Observed mode/result | Invocations / input / output / latency |
| --- | --- | --- |
| `905ef45c-75fe-4775-836c-a9cad8c9acd3` | independent; 2017 excluding-excise RRP revenue $3.6 billion | 3 / 5958 / 243 / 21.85s |
| `46c5a573-d168-4733-9583-cac351c28a35` | resolved original prior-year question to 2016; $733 million | 3 / 5508 / 138 / 7.29s |
| `c6728cb1-ab89-4064-8ae7-c919f42b94e4` | fresh-chat clarification; no citations or inherited context | 0 / 0 / 0 / 1.25s |

The two ordered runs belong to conversation
`bfca66e8-43a1-4d20-bfbc-45d88de1a2a0`; reset used
`958728d9-da4c-40fa-8514-e410e5f0b8e6`. Observed policy
`prior-year-scope-v1`, execution fingerprint
`b172d3f619e6ea8a118f88e76dcdfca0665e57d25d4afc51077cac2b64099321`.
Usage accounting was complete; no persisted unsupported claim/invalid citation.
Local answer/support remained Ollama
`igorls/gemma-4-12B-it-qat-q4_0-unquantized-heretic:latest`, digest
`2835c50a7b13c1e9c8ab58a4d08368e374ae5f33ce055afb0b8081bc006aef9f`,
8192 context. Embeddings remained deterministic-test, 384 dimensions. Provider
events are unpriced: generic report cost totals must not be read as attested
monetary zero. No model-quality guarantee follows from these three cases.

Pre/post read-only nightly inspection verified unchanged corpus fingerprint
`92b604cfe21d1b59479b113f1ec4fb1356be42fad29690a8e55ff55d49ce5e29`,
model fingerprint `669a19cae19de22a089a9c681f1e6d37a1d5412ba479ff0de316c3d988749833`
and index/model deployment fingerprint
`a6e090cf13ba3e88a6c5014a1611c0112c4efb4c78038ddee4a7caf65a3debc6`.
Foreign-workspace GET probes remained isolated. Search readiness stayed at 100
completed rows, zero failed/running. Doctor returned exit 0 with explicit dev
auth/deterministic embedding/unprobed-dependency warnings, not a production pass.

API image stayed `sha256:a05ebf29c28354838b53262adf9dcb7ba3bfafaddf9a09cbd9a849b37d0c6c17`
from deployed revision `f9a34da94a7272a54e07cc5194691e7998aeaf6a`; host capture
ran the working #102 code. The two-turn recording preceded the final additive
limits metadata field; the reset recording and HTTP tests verify that field.

The initial live probe failed because existing core containers had stopped.
Compose restart exposed a stale migration-helper image unable to resolve the
already-applied 0016 revision. Existing core/API/worker containers were started
without rebuild/data deletion; API Alembic confirmed 0016 head. Optional telemetry
overlays remained stopped. A verification helper subsequently used a nonexistent
top-level invocation-count field; it was corrected to actual usage-accounting
records and the existing capture was revalidated read-only, not recaptured.
Neither unsuccessful attempt is counted as a passing check.

## Verification

Passed:

- `uv run pytest -q --tb=short`: 971 passed, 15 skips.
- Final `uv run pytest -q tests/unit/test_eval_capture.py tests/unit/test_eval_cli.py --tb=short`: 66 passed.
- PostgreSQL opt-in conversation/query API suite: 136 passed, five skips.
- `uv run ruff check .`; `uv run mypy`: clean, 160 source files.
- `uv lock --check`; deterministic Acme evaluation gate.
- Both fresh conversation recordings loaded/scored via `flint-graph-eval run`;
  independent live assertions above passed separately.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: 1061 lines; no migration change.
- `docker compose config --quiet`; `git diff --check`.
- Read-only pre/post nightly inspection; live doctor; API migration inspection.
- Actual frontend public-thread reopen at 390/1280px with screenshots inspected;
  composer visible, no horizontal overflow, zero mutation/SSE/model requests.
  Frontend remains running at localhost:5173; backend at localhost:8000.

Not rerun for this evaluation-only change: full frontend browser/unit/build or
screen-reader qualification, external OIDC browser/deployment tests, a new 12-case
standalone nightly capture, optional telemetry fan-out, large-history benchmarks,
source deletion, general memory, cost reservations, paid providers or private
corpus tests. Signed-token execution/isolation remains covered by the PostgreSQL
API regression suite. #74/#62/#75/#82 and human rubric review/remote nightly
activation #53 remain open. Detailed public-only artifacts are gitignored under
notes; CI status is reported separately in the issue after pushing.
