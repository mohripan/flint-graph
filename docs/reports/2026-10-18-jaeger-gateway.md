# Jaeger shared-privacy gateway qualification — 2026-10-18

Issue #106, milestone 24, ADR 0032. This delivers a local optional gateway
configuration, not the cross-service application rollout (#107), parent #72,
or production telemetry hardening (#43).

## Changes and red/green evidence

The new optional Compose overlay merges the unchanged shared privacy config,
a bounded trace-only Jaeger exporter, and an explicit two/three-destination
exporter list. The Jaeger-only path has no Phoenix dependency. Metrics/logs
remain LGTM-only. Grafana gets a fixed non-default, non-editable Jaeger
datasource with pruning on optional-file removal.

Deployment seam tests first failed on the missing overlay, then passed after
the assets were added. The native live test first failed when no gateway was
listening; after startup real trace delivery passed. Explicit non-blocking
queue-policy assertions failed before those settings were added, then passed.
The rollback test failed (200 rather than expected 404) before base-only
Grafana recreation, then passed afterward. These asset assertions do not by
themselves prove privacy or runtime isolation; the following native checks do.

## Live checks, synthetic content only

- Collector **0.162.0** native validation passed both merged destination
  configurations. Native validation rejected an unknown mode file and the
  existing syntactically valid unknown-component fixture. No experimental
  config-list append feature was enabled.
- LGTM + Phoenix + Jaeger live suite: **2 passed, 1 skipped in 15.87 s**;
  skipped test is the separately selected rollback check. Same trace
  `aea0a77fb90aa35e999ca56eafc36440`, root `f250e65af8b45f10`, child
  `e03e689525702a4e` was retrieved with exact parentage from all three. The real
  provider telemetry wrapper ran without any provider network request.
- Unique sentinel prompt, answer, evidence, vector, credential, exception,
  event and resource attributes were absent in returned records. Events and
  status descriptions were empty. Grafana's provisioned datasource readback
  and fixed v3 proxy lookup returned the same IDs, with no sentinel payloads.
- Actual Docker pause of the resolved owned Jaeger container stalled its OTLP
  socket. Trace `00e6d695c64c37dc22cd8643cf5d7ea5` reached Tempo and Phoenix in
  **0.875 s** while Jaeger was paused. Native queue capacity was **64 requests**;
  failed-span count increased by **2**, queue and in-flight work drained to
  zero, and Collector logged retry exhaustion / dropping two items. After
  unpause the expired trace returned **404** from Jaeger, rather than falsely
  claiming replay. Fresh trace `f48c8f4fc7ffde13dd38b94cca4afe71` reached all
  three destinations. This is low-volume failure isolation, not saturation or
  capacity certification. No application depended on this gateway yet.
- Phoenix was stopped, only the gateway recreated in Jaeger-only mode, and the
  real destination/privacy test passed (**1 passed, 2 skipped in 1.85 s**).
  Trace `f0daa2332654fe0376685d7e3dfb50ca` reached Tempo/Jaeger without Phoenix.
- Base-only LGTM recreation removed the optional datasource: rollback test
  **1 passed, 2 deselected in 0.15 s**. Jaeger datasource 404, Tempo and operations
  datasource 200. No volume was removed. The triple overlay was subsequently
  restored and the final live suite above passed.
- Own isolated headless browser selected **FlintGraph Jaeger** in Grafana Explore,
  queried the fresh trace, and rendered `gateway.synthetic-parent` with its
  `provider.answer` child. The first editor fill accidentally appended to the
  placeholder and returned 400; native keyboard replace/Shift+Enter corrected
  the automation input and the real trace rendered. Browser diagnostic passed;
  no application/config change was needed. Screenshot inspected under ignored
  `notes/jaeger-grafana-gateway-2026-10-18.png`; own session closed.
- The earlier Phoenix/Tempo real smoke also passed through the selected triple
  gateway (**1 passed in 0.70 s**). Existing Phoenix-only native validation and
  smoke remain in CI before the new qualification steps.

## Application and data boundary

After the interrupted week all project containers were stopped. Existing exact
containers and volumes were started, not replaced/reset. Vite and the existing
Ollama service were restored. Subsequent gateway mode changes recreated only
named telemetry containers. API, worker, relay and cleanup container IDs stayed
unchanged. API still exports directly to `http://observability:4317`; model
settings remained the same Gemma answer/support and deterministic-test
384-dimensional embeddings. No new model/corpus download, inference, workspace
mutation or private document read was used.

Frontend `http://localhost:5173`, API `/health/live` and `/health/ready` returned
**200**. A preliminary `/health` request returned expected 404 (that is not the
health route). Public verification workspace remained **100 documents / 100
ingestion jobs** before/after. Local unauthenticated tools were not exposed
through a new public interface. Existing base LGTM host bindings are unchanged.
Recreating LGTM briefly interrupted local telemetry endpoints, not application
data. Datasource rollback removed only the newly owned Jaeger datasource
configuration; re-enabling it recreated that configuration. Trace volumes were
preserved; expired Jaeger exports are intentionally unrecoverable.

## Commands and gates

Passed locally:

- `uv run pytest -q --tb=short`: **1,036 passed, 20 skipped, 138.21 s**.
  Live/backing-service opt-ins remain skipped in the ordinary offline run.
- `uv run ruff check .`; `uv run mypy` (**161 source files**);
  `uv lock --check`.
- Deterministic Acme evaluation command from AGENTS.md: passed, no baseline edit.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: **1,061 lines**.
- `docker compose config --quiet`; new Jaeger-only and combined AI/Jaeger
  Compose configurations; native positive/negative validation described above.
- Frontend `npm test`: **10 passed**; `npm run typecheck`; `npm run build`.
- `git diff --check`.

CI now also performs the actual triple fan-out/pause, Phoenix-independent mode
and datasource rollback checks, alongside the prior native/backend checks.
Its commit-specific result is recorded in GitHub before issue closure; this
report does not label an unobserved CI run successful.

Not run/claimed: a new model-quality recording, PostgreSQL-only conversation
suite, full application profile rollout/correlation, restart of existing
customer-data services for destructive testing, queue saturation/eviction,
production retention/restore, SMTP, paid inference or remote nightly activation.
The allowlist is not arbitrary-text secret detection: span names, allowed key
values, links, metrics/log bodies and third-party instrumentation still require
#43 review. Shared Collector memory/CPU also means this low-volume result does
not prove isolation under all traffic loads. #72 remains open for #107.
