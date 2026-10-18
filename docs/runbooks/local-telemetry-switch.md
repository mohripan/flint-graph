# Preserve settings when switching local telemetry

Scope: ADR 0033 / #108. Fixed standard local `flint-graph` Compose project only.
This recreates application processes when explicitly applied, so expect a brief
API interruption and use a quiet development window. It does not drain in-flight
jobs or provide zero-downtime deployment. Do not use it for production.

## Prepare the destination first

Start and qualify **only named telemetry services** using the existing
[Phoenix runbook](ai-observability.md) or [Jaeger gateway runbook](jaeger-gateway.md).
Match the desired mode exactly:

| Mode | App endpoint | Required tools / actual gateway command |
| --- | --- | --- |
| `base` | `http://observability:4317` | Healthy LGTM; no gateway required |
| `phoenix` | `http://otel-gateway:4317` | LGTM + Phoenix; shared config only |
| `jaeger` | `http://otel-gateway:4317` | LGTM + Jaeger; shared + Jaeger exporter + `jaeger-only` |
| `combined` | `http://otel-gateway:4317` | LGTM + Phoenix + Jaeger; shared + Jaeger exporter + `jaeger-phoenix` |

For example, prepare combined mode with the explicitly selected environment
variable and four Compose files from the Jaeger gateway runbook. Changing that
variable alone does not reconfigure a running gateway. The helper checks its
actual command, not the operator shell's requested selection. Backend process
health is a preflight, not trace delivery proof; run synthetic delivery tests.

## Preview, apply, check

From the repository root:

```powershell
uv run flint-graph-telemetry --mode combined
# Inspect the preview; no process has changed yet.
uv run flint-graph-telemetry --mode combined --apply
```

The helper inspects the existing API, worker, relay and cleanup separately. It
preserves their immutable image IDs, full environment, command/entrypoint,
working directory and user, changing only the OTLP endpoint. It renders all
proposed environment/process settings before rollout and verifies them after
each app-only recreation. No build/pull, provider fallback, model download,
migration or data-service recreation is requested. API is recreated last.
Environment values and Docker output/errors are not printed or saved to files.

Read-only checks after switching:

```powershell
Invoke-WebRequest http://localhost:8000/health/live
Invoke-WebRequest http://localhost:8000/health/ready
# Use the existing workspace and system/search readiness APIs to compare the
# selected provider/model/dimension/index and coverage; do not create a new index.
```

The frontend remains on <http://localhost:5173>. An interrupted API request may
need a user retry; do not label an unfinished answer successful. Run the
explicit gateway smoke from its runbook to confirm selected destinations.
Cross-service ingestion/query trace qualification remains #107.

Unsupported custom mounts, extra hosts, guarded resource/security settings,
port bindings, networks and restart policies fail before mutation. The helper
does not silently convert a customized development stack to base defaults.
Only local Docker sockets/named pipes and apps with explicit `FLINT_GRAPH_ENV=local`
and already enabled tracing are supported. It does not enable tracing in a
previously uninstrumented process. No remote Docker/production mode is accepted.

## Restart and rollback

A normal Docker restart preserves the selected container configuration; it
does not switch modes. Use a quiet window and inspect recovery. The opt-in
automated rehearsal intentionally performs app recreation/restart/base rollback:

```powershell
$env:FLINT_GRAPH_TELEMETRY_SWITCH_INTEGRATION='1'
$env:FLINT_GRAPH_TELEMETRY_VERIFY_WORKSPACE='YOUR-EXISTING-VERIFICATION-WORKSPACE-UUID'
uv run pytest tests/integration/test_telemetry_switch_live.py -q -s
Remove-Item Env:FLINT_GRAPH_TELEMETRY_SWITCH_INTEGRATION
Remove-Item Env:FLINT_GRAPH_TELEMETRY_VERIFY_WORKSPACE
```

It requires all apps initially in base mode, plus a qualified running combined
gateway. It only reads the supplied workspace's public API metadata and makes
no query/provider call, upload, index switch or private document read. Assertions
compare full environment values in memory without printing them on failure.

For an explicit base rollback:

```powershell
uv run flint-graph-telemetry --mode base
uv run flint-graph-telemetry --mode base --apply
```

Do not stop the old destination until all apps point at the new one. On partial
failure the helper reports phase and completed services, returns nonzero and
does not claim automatic/atomic rollback. Inspect services; prepare the previous
telemetry mode, preview it and explicitly apply it. A failed Compose operation
may have partially changed its target even when not in the completed list.
Rollback preserves current non-telemetry settings; there is no secret-bearing
backup file to restore earlier external operator changes from. Replaced/stopped
or otherwise unsupported containers may need manual repair before retrying.
Never reset providers, re-bootstrap an index or delete volumes to switch telemetry.
