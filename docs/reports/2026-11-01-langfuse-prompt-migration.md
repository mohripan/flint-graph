# Langfuse prompt migration qualification

Date: 2026-11-01 (Asia/Jakarta). Implements the typed catalog, optional authoring
profile and reviewed-label resolver from ADR 0044 (#135–#137), plus existing
assistant and image defaults. Work is isolated on `codex/prompt-migration` in
`C:/Projects/flint-graph-codex-prompt-migration`. Existing services, containers,
worker queues, real Studio projects and the main checkout were preserved.

## Result and boundaries

Provider answer/support and both extraction builders now render through a typed
catalog. Assistant system/context/repair instructions and image portrait,
expression/background wording, conditioning and the image content policy are
catalog entries too. `prompts.lock` contains complete immutable templates,
variable/output schemas and configuration; no credentials or creator content.
Golden renderings were captured from `b4b6729` **before** changing builders.
The initial migration preserves exact model-visible bytes and default policy
lists. Existing weak delimiters are deliberately unchanged; a future wording or
delimiter-hardening rollout must get a new version and separate quality evaluation.
Application parsers, authorization and generation resource ceilings remain code.

Default operation is locked and offline. Optional Langfuse background reads never
block admission. A complete remote map must match a reviewed deployed bundle;
partial labels, unknown versions, schema/config mismatches and outages retain the
active approved bundle. Reads have a two-second overall deadline, zero generated
SDK retries, four concurrent requests, bounded bodies and GET-only same-origin
transport. The generated async API creates no SDK tracer/exporter/media/score owner.
Existing FlintGraph OTel spans retain ownership and link identity values only.

Migration `0033_prompt_bundles` adds generic content-addressed manifests and
nullable references to query, ingestion/extraction runs, assistant turns and image
jobs. Historical unknown identities stay null. Queued work snapshots at admission;
legacy pending work pins its first execution. Referenced missing/corrupt manifests
stop replay rather than selecting today's defaults. Extraction deduplication now
includes bundle identity. Actual query provider configuration is committed through
the existing usage ledger before provider dispatch; answer/support metadata and
answer provenance carry the same identity. The assistant's historical system/schema
`prompt_sha256` meaning is preserved. Image jobs retain fully constructed prompts
and normalized policy identity. Explicit private TOML overrides remain locked-mode
compatibility only and are never automatically published.

The operator [runbook](../runbooks/prompt-management.md) covers import, review,
publication, rollback, Viewer keys, diagnosis, TLS, backup and retention. New CI
validates retained versions against the PR base and the optional native Compose
file. The default Compose file and unrelated trace-probe workflow were not edited.
No production labels were moved and no owned API/worker was restarted to activate
this code; operators pull/apply the migration and restart their owned deployments.

## Real service and browser proof

The isolated `flint-codex-prompts` stack serves Langfuse **4.72.0 OSS** on loopback
port **6090**, using SDK **4.15.0**, separate PostgreSQL/ClickHouse/Redis/MinIO data,
private generated credentials, disabled public signup and product telemetry. All
images are digest-pinned in `ops/langfuse/compose.yml`; OTel remains 1.43.0.
The initial author and a separate **Viewer** runtime key were created in the UI.
No existing container, volume or Studio project was reused or stopped.

The real CLI seeded the generic catalog, repeated the seed idempotently, pulled a
synthetic changed assistant version, diffed/locked it, checked history, promoted
that approved fixture and rolled it back. The live resolver test held an actual
assistant model call open during promotion: the old call received its original
instructions, and the next call received the approved new instructions. A fake
model kept inference offline; Langfuse reads and label writes used the actual server.
Unreviewed version 3, malformed-schema version 4, a real refused socket, and rollback
all retained/restored the correct approved map. Admission/restart tests separately
exercise durable assistant/query snapshots and corrupted-manifest rejection.

The Viewer key received **403** on prompt creation, label mutation, score/media
writes and OTLP ingestion. The original legacy ingestion probe returned per-event
`400 Event type not accepted` under v4; this was replaced with the real write
endpoints above, so it is not misreported as an authorization proof. Runtime audit
transport observed only prompt GETs with empty request bodies; no tenant payload,
trace ingestion, media or score request left the runtime reader. The UI shows zero
observations on the imported templates. [Catalog screenshot](langfuse-prompt-migration-2026-11-01/catalog.png).

Doctor checks against the real service returned `approved` / valid key / no drift;
a wrong secret returned `invalid_credentials`; a refused loopback socket returned
`unavailable`. All remote cases remain optional with exit 0 and a valid local lock.
A corrupt local lock remains an error. Values and endpoints are omitted from output.
The [public receipt](langfuse-prompt-migration-2026-11-01/qualification.json) contains
image pins, resource samples and redacted doctor results; private keys stay ignored.

## Resource measurement

Four concurrent clients completed **3,553** generic prompt reads over 12 seconds
(about 296/s). These are small local authoring samples, not sustained capacity or
trace-ingestion qualification. CPU is Docker's percent of one logical core. The
idle sample had no synthetic request load; background housekeeping can fluctuate.

| Service | Idle MiB | Loaded MiB | Idle CPU | Loaded CPU |
| --- | ---: | ---: | ---: | ---: |
| Web | 759.4 | 770.7 | 0.43% | 81.76% |
| Worker | 328.4 | 329.2 | 1.57% | 27.67% |
| PostgreSQL | 149.6 | 151.0 | 0.12% | 3.23% |
| Redis | 8.1 | 8.8 | 0.64% | 4.43% |
| ClickHouse | 531.5 | 528.9 | 4.16% | 5.35% |
| MinIO | 77.3 | 75.6 | 42.96% | 5.32% |

Total memory was about 1.81/1.82 GiB; the profile ceiling is 2.625 GiB. Persistent
data occupied PostgreSQL 71,424 KiB, ClickHouse 103,464 KiB plus 2,968 KiB logs,
Redis 360 KiB, and MinIO 320 KiB, excluding image layers. No performance comparison
to a production server is implied. Production retention, restoration and HA remain
operator qualification work; tracing export is still outside this feature (#79).

## Commands and verification

The following commands passed during qualification; final precommit/rebase totals
are recorded below. All scratch launchers are ignored and pass private credentials
only through child environment variables, never command output.

```powershell
uv sync --all-groups
uv sync --all-groups --extra langfuse
npm --prefix frontend ci
uv run pytest -q --tb=short
uv run ruff check .
uv run mypy
$env:FLINT_GRAPH_ENV='test'; uv run alembic upgrade head --sql
docker compose config --quiet
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run --extra langfuse pytest tests/unit/test_prompt_catalog.py tests/unit/test_prompt_migration.py tests/unit/test_prompt_source.py tests/unit/test_prompt_cli.py tests/unit/test_doctor_cli.py tests/integration/test_prompt_snapshots.py -q --tb=short
uv run python notes/run-live-langfuse.py
uv run python notes/check-live-doctor.py
uv run python notes/qualify-cli.py
uv run python notes/measure-langfuse.py
uv run python tools/langfuse/init_local.py
 docker compose -p flint-codex-prompts --env-file notes/langfuse-local.env -f ops/langfuse/compose.yml config --quiet
 docker compose -p flint-codex-prompts --env-file notes/langfuse-local.env -f ops/langfuse/compose.yml up -d
uv build --wheel --out-dir notes/wheel
uv run python notes/check_wheel.py
```

The live wrapper runs `uv run --extra langfuse pytest
tests/integration/test_prompt_langfuse_live.py -q --tb=short` with explicit fixture
flags, author/Viewer keys and loopback URL: **1 passed**. The wheel check opens the
built wheel and validates its included `flint_graph/prompts/prompts.lock`. Browser
qualification used the agent-browser skill with a named `codex-prompt-migration`
session and a separate Edge instance; only that session was closed afterward.

Real PostgreSQL qualification:

```powershell
uv run python notes/run-prompt-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py -q --tb=short
```

**105 passed** across SQLite and PostgreSQL. The launcher creates a fresh random
database, executes actual `alembic upgrade head`, `alembic downgrade
0029_narrative_voice`, `alembic upgrade head`, then runs those tests with PostgreSQL
fixtures and drops only its own database. It reads existing fixture connection
settings in memory and never prints credentials or changes existing application data.
The existing Alembic path-separator deprecation warnings remain unchanged.

Real Godot qualification:

```powershell
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py -k real_web -q --tb=short
```

**32 passed, 2 skipped**, then the template-enabled Web PCK check **1 passed**
(22 deselected). The remaining skipped CG release test requires its own prepared
builder image; this prompt migration changes no Godot runtime/build pins or child
engine code. The default Python run skips explicitly gated GPU/model/Temporal/
export fixtures; they are not counted as live verification. No image model call
was used to claim prompt migration parity.

Initial failures exposed a changed extraction uniqueness assertion and a
wall-clock-sensitive rate-capacity test. The assertion now includes bundle identity;
the rate test controls the middleware clock while preserving the same expiry and
capacity assertions. A real promotion found that the vendor rejects writing its
reserved `latest` label; the CLI now preserves environment labels while omitting
that server-owned label, with a regression test. The initial model-visible schema
extraction was corrected to the old wire schema rather than substituting Pydantic's
parser schema; adapter and golden tests prove the current emitted schema/text.


## First implementation checkpoint

Before the first implementation commit, the final full Python run passed **1,832
with 111 opt-in skips**. Focused catalog/source/CLI/doctor/snapshot tests passed
**58**; the SDK compatibility probe passed **4**. Ruff and mypy passed (257 source
files), offline Acme evaluation passed, both Compose configurations validated, SQL
migration generation passed, and frontend tests/typecheck/build passed (**107**
frontend tests). The wheel contains the validated complete lock.

The expanded final PostgreSQL command was:

```powershell
uv run python notes/run-prompt-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py -q --tb=short
```

It passed **131** checks, plus fresh-database upgrade/downgrade/re-upgrade. The
cross-bundle extraction regression verifies distinct manifests even for identical
model output and idempotence within one bundle. Completed legacy rows are never
assigned invented identities. Document deletion/authorization checks run before
loading an ingestion snapshot, preserving their existing refusal behavior.


## Latest-master integration and final qualification

Rebased onto `e8316ec`, preserving the newly merged CG and expressive/cloned-voice
work, including runtime 0.7.0 and migrations 0030–0032. The prompt migration was
renumbered to **0033** after `0032_narrative_voice_models`. No owner runtime/model
pipeline changes were dropped or edited. The newly added scene-art prompt builder
was then migrated too: `scene_solo`, `scene_pair` and `scene_conditioning` raise the
default catalog to **21 entries**. The old 18-entry artifact is retained. Five
one/two-character outputs, including the unspecified-character case, match the
captured `133a551` builder exactly. A selected-bundle test first failed on the old
hard-coded quality and now passes with scoped conditioning; custom policies are
also scoped at CG admission. A stale explicit lock missing current required names
is refused before admission rather than failing when a new feature first runs.

The final complete Python run passed **1,908 tests with 117 opt-in skips**:
`uv run pytest -q --tb=short`. Ruff passed; mypy passed **266** source files. Frontend
`npm test`, `npm run typecheck` and `npm run build` passed (**116** tests). Native
root and optional Compose validation, SQL migration generation and offline Acme
evaluation passed again. Real Godot/preview/CG conformance, with engine and Web
export templates set as above, passed **33 tests, 1 skipped** (only the explicit
prepared-builder CG release remains gated). The same expanded PostgreSQL command
above passed **131 checks**, now using a fresh task-owned PostgreSQL container and
actual upgrade to 0033, downgrade to 0032 and re-upgrade. It never opened a real
Studio project or altered the owned application database.

During the session all previously running Docker containers were externally
stopped, including the shared fixtures and the first qualification stack. No shared
container was restarted. Final service qualification used fresh task-owned
`flint-codex-prompts-final` containers and a fresh `flint-codex-prompt-pg-final`
fixture (loopback 6192), with new private initialization/Viewer credentials. The
fresh service imported all 21 entries and repeated real promotion/old-call/new-call,
rejection, outage, rollback, doctor and CLI checks successfully. These are the exact
final service commands, with private credentials injected only by ignored wrappers:

```powershell
uv run python tools/langfuse/init_local.py --output notes/langfuse-final.env
docker compose -p flint-codex-prompts-final --env-file notes/langfuse-final.env -f ops/langfuse/compose.yml up -d
uv run --extra langfuse python notes/run-live-langfuse.py
uv run --extra langfuse python notes/check-live-doctor.py
uv run --extra langfuse python notes/qualify-cli.py
uv run --extra langfuse flint-graph-prompts check --base-ref HEAD
```

The live test passed **1** again (6.66 s); the doctor correctly reported approved,
invalid credentials and unavailable; the CLI pull/diff/lock/promote/rollback all
passed against the fresh service. No production labels were moved.
[Final 21-entry UI proof](langfuse-prompt-migration-2026-11-01/catalog-final.png).
Current fixture ownership and private file locations are recorded in ignored
`notes/prompt-service-owned.json`; the public receipt contains no keys. The original
resource sample remains explicitly associated with the earlier stack using the
same pinned images/limits. `npm ci` reported one pre-existing high-severity audit
advisory; this change does not modify frontend dependencies or apply an unrelated
lock upgrade.
