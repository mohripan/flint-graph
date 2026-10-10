# Platform and developer-experience delivery, 2026-10-10

Added GitHub milestones 24–26 and issues #34–52: three tracking epics and sixteen
focused implementation issues. ADRs 0013–0015 record observability layering,
measured search/inference selection and reproducible developer experience.
Milestones remain open; a local profile is not a production qualification.

Delivered slices: #40 provider OpenInference/privacy, #37 local Alertmanager,
#38 provisioned/unit-correct Grafana, #39 Phoenix/gateway, #51 native CI and live
fan-out/privacy. All commits use the existing default branch `master` and omit
co-author trailers. No provider defaults, application schemas, embedding models
or tenant corpus data were changed by this batch.

## Passed verification

- `uv run pytest -q`: 541 passed, 6 opt-in tests skipped.
- `uv run ruff check .`: passed.
- `uv run mypy`: passed, 144 source files.
- `uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic`: passed; no baseline changes.
- `uv run alembic upgrade head --sql`, with explicit deterministic answer/support
  providers: passed; no new migration required.
- `docker compose config --quiet` and `docker compose --profile metrics config --quiet`: passed.
- `docker compose -f compose.yaml -f compose.ai-observability.yaml --profile ai-observability config --quiet`, also with `--profile metrics`: passed.
- `docker compose --profile metrics run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml`: passed, including nine rules.
- `docker compose --profile metrics run --rm --no-deps --entrypoint amtool alertmanager check-config /etc/alertmanager/alertmanager.yml`: passed.
- `docker compose -f compose.yaml -f compose.ai-observability.yaml --profile ai-observability run --rm --no-deps otel-gateway validate --config=/etc/otelcol/config.yml`: passed.
- All three deliberately invalid native-tool fixtures were rejected as expected.
- `docker compose -f compose.yaml -f compose.ai-observability.yaml --profile ai-observability up -d --no-deps --wait --wait-timeout 180 observability phoenix otel-gateway`: passed.
- `FLINT_GRAPH_AI_OBSERVABILITY_INTEGRATION=1 uv run pytest tests/integration/test_ai_observability_live.py -q` (set/unset through PowerShell): one passed. The same trace reached Phoenix and Tempo with private sentinel attributes/events removed, correct LLM classification and safe ERROR status.
- Local API checks: Prometheus discovered Alertmanager; synthetic alert became
  active then resolved; Grafana confirmed the provisioned 24-panel dashboard and
  default datasource. No email/webhook receiver is present.
- Browser: real Grafana charts loaded against local metrics; Phoenix displayed
  the sanitized smoke project/trace. Screenshots are scratch artifacts in notes/.
  An initial wait for a below-viewport Grafana panel timed out; API/chart checks
  confirmed provisioning, so that wait is not counted as a passed check.

The real Collector smoke initially failed because a syntax-valid event-clearing
expression was invalid at runtime. The final event-filter configuration passed
the real privacy test. This motivated keeping runtime checks alongside syntax.

## Not performed or not delivered

- Frontend npm type/build/browser-suite commands: skipped this batch because no
  frontend source/dependency changes; actual Grafana/Phoenix UI checks ran.
- PostgreSQL/Neo4j live corpus tests, fresh answer quality and load benchmarks:
  not rerun; this batch changes telemetry/configuration, not retrieval behavior.
- SMTP/email/webhook delivery: intentionally disabled; destination, relay and
  credentials still require operator configuration (#41).
- ELK/log shipping, production auth/retention, vLLM adapter/GPU benchmarks,
  large-corpus search tuning and doctor/bootstrap: open issues, not implemented.
- No automatic OpenLLMetry installation, paid inference, model download, GPU
  rental or destructive data cleanup.

## Local handoff

Grafana <http://localhost:3000/d/flint-graph-operations>, Phoenix
<http://127.0.0.1:6006>, Prometheus <http://127.0.0.1:9090>, Alertmanager
<http://127.0.0.1:9093>. New tool services/data volumes remain available. Existing
application provider settings were preserved; API/worker processes still use
their existing direct LGTM endpoint until explicitly recreated with the overlay.
The standalone scrape profile is API-only and requires enabled/token-matched
scraping; it is not yet a fleet-wide alert source. Grafana uses the existing
all-process OTLP metrics. Production telemetry source/missing-data alerts are #43.

Read [AI observability](../runbooks/ai-observability.md),
[operations](../runbooks/operations-observability.md), and
[roadmap](../ROADMAP.md) for configuration, limitations and remaining milestones.
