# Reviewed prompt management

Langfuse is the authoring UI. The deployed `src/flint_graph/prompts/prompts.lock`
is the approval boundary and complete offline fallback ([ADR 0044](../adr/0044-langfuse-authoring-and-reviewed-prompt-locks.md)).
The API and model workers compile variables locally. Prompt management sends no
questions, evidence, story text, creator descriptions, reference images or answers.
The ordinary SDK tracing client is never constructed; existing OTel ownership stays intact.

## Optional local authoring stack

From a separate worktree, generate private settings once, then start the separate
native Compose file. This does not join or modify FlintGraph's default stack.
Use a distinct Compose project name, free loopback ports, and dedicated volumes.

```powershell
uv sync --locked --all-groups --extra langfuse
uv run python tools/langfuse/init_local.py --output notes/langfuse-local.env
docker compose -p flint-prompts --env-file notes/langfuse-local.env -f ops/langfuse/compose.yml config --quiet
docker compose -p flint-prompts --env-file notes/langfuse-local.env -f ops/langfuse/compose.yml up -d
```

The UI defaults to `http://127.0.0.1:6090`; the S3 endpoint to loopback port 6091.
Override `LANGFUSE_LOCAL_PORT` / `LANGFUSE_LOCAL_S3_PORT` in the private env file if
needed. Web/worker and all dependencies are digest-pinned. Headless initialization
uses `LF_INIT_*` values from that file; do not paste them into commands, reports
or Git. Sign up and product telemetry are disabled. Log in with the private initial
user and create a **Viewer** project API key for runtime reads under Settings → API
Keys. The provisioned full-access key is for initial generic import and authoring
only. Keep author/release keys outside application API and worker environments.
Viewer denies prompt writes, label changes, score/media writes and OTLP ingestion.
The runtime transport additionally blocks every write before sending it.

The qualification fixture used roughly 1.8 GiB at idle/under prompt-read load,
with a total 2.625 GiB configured memory ceiling. These small limits are for local
prompt authoring, not trace ingestion or production sizing. See the measured
[resource receipt](../reports/langfuse-prompt-migration-2026-11-01/qualification.json).
Do not evict owned model workers or existing fixtures to start this optional stack.

## Import, review, deploy and rollback

Supply `FLINT_GRAPH_PROMPT_AUTHOR_PUBLIC_KEY` and
`FLINT_GRAPH_PROMPT_AUTHOR_SECRET_KEY` privately to the CLI process. They are
separate from `FLINT_GRAPH_LANGFUSE_*` runtime credentials. Set
`FLINT_GRAPH_LANGFUSE_BASE_URL` to the intended authoring instance.

```powershell
uv run flint-graph-prompts check
uv run flint-graph-prompts seed --label staging
uv run flint-graph-prompts pull --label staging --source-revision <reviewed-source-sha> --evaluation-record <evaluation-report-path> --output notes/candidate.json
uv run flint-graph-prompts diff notes/candidate.json
uv run flint-graph-prompts lock notes/candidate.json --output notes/proposed-prompts.lock
uv run flint-graph-prompts --lock notes/proposed-prompts.lock check --previous src/flint_graph/prompts/prompts.lock
```

`seed` imports only missing, empty names at version 1. Re-running is idempotent;
it refuses existing divergent versions. It never overwrites authored work. Edit
instructions/config in Langfuse and increment `config.flint_graph.catalog_version`
for every changed entry. Keep declared variable/output schemas and policy metadata
in `config.flint_graph`; actual authored configuration lives in `config.value`.
Prompt variables use `{{name}}`; exact keys and declared types are checked locally.
Inserted text is substituted once. Linked includes, remote schema references and
arbitrary message roles cannot enter the runtime through this catalog.

Review the complete candidate diff and evaluation evidence with a maintainer
other than its author. Commit the proposed lock, preserving all existing bundles
and version history. `check --base-ref <base-sha>` verifies committed changes against
that Git revision; CI does this as well. `lock --activate` changes the packaged
fallback; omit it to stage a preapproved candidate for later label activation.
Deploy the approved lock to the API and prompt-calling workers **before** moving
labels. Publication of exact numeric versions is explicit:

```powershell
uv run flint-graph-prompts promote --label production --bundle <approved-bundle-sha256> --actor <release-actor> --reason <review-or-incident-reference> --receipt notes/promotion.jsonl
```

Promotion verifies every numeric version before writing any label and reads the
whole map back. The receipt records intent before mutation, then previous/new
versions and completion. A partial failure cannot activate a mixed map; inspect the
receipt and repeat the exact approved promotion with a new receipt path; existing
receipts are never overwritten. Existing environment labels are
preserved; Langfuse's reserved `latest` label is not written. Rollback promotes the
previous approved bundle and records an incident reason/receipt. Disable remote
refresh to return new admissions to the deployed packaged fallback immediately.
Already admitted runs retain their original persisted manifests.

Shared grounding rules are flattened into each concrete provider template. When
editing a shared rule, update and version its containing templates too. Existing
wrappers are preserved byte-for-byte; delimiter hardening and wording changes need
separate versioned evaluation. Application parsers, permissions, tool capabilities,
budgets, dimensions and resource ceilings remain in code/operator configuration.
Langfuse cannot grant capabilities or introduce provider URLs or credentials.

## Runtime configuration and diagnostics

`FLINT_GRAPH_PROMPT_SOURCE=locked` is the default. Optional refresh uses:

| Variable | Purpose |
| --- | --- |
| `FLINT_GRAPH_PROMPT_SOURCE=langfuse` | Enable managed background reads |
| `FLINT_GRAPH_PROMPT_LOCK_PATH` | Explicit reviewed lock override; otherwise packaged file |
| `FLINT_GRAPH_LANGFUSE_BASE_URL` | Operator-selected origin; staging/production require HTTPS |
| `FLINT_GRAPH_LANGFUSE_PUBLIC_KEY`, `FLINT_GRAPH_LANGFUSE_SECRET_KEY` | Viewer project key; secret is redacted by settings |
| `FLINT_GRAPH_LANGFUSE_PROMPT_LABEL` | Environment label; default `production` |
| `FLINT_GRAPH_LANGFUSE_REFRESH_SECONDS` | Refresh interval, 1–60 seconds; default 60 |

API, ingestion worker and assistant worker start a managed refresh task. Requests
never wait for it. The entire fetch has a two-second deadline, zero SDK retries,
four concurrent reads and a 1 MiB cap per response. Only an exact complete approved
map activates atomically. Missing labels, invalid credentials, unreviewed versions,
invalid config/schema and outages retain the current approved map indefinitely.
`flint_graph.prompts.refresh` counts fixed reason codes without prompt content.

```powershell
uv run --extra langfuse flint-graph-doctor --prompts --json
uv run flint-graph-doctor --prompts --offline --json
```

The prompt-only doctor needs no workspace, model credentials or running Studio API.
Remote failures are optional warnings; corrupt local locks are failures. It reports
reachability/key status and lock drift with no endpoint, key or authored content.
Do not add Langfuse availability to API readiness. A missing SDK extra in managed
mode fails configuration explicitly; install the optional extra in that deployment.

Apply migration `0033_prompt_bundles` before enabling the migrated application.
The generic manifest table is content-addressed; query/ingestion/extraction runs,
assistant turns and image jobs reference it. Existing rows stay null. Old pending
work pins its first execution when claimed. Missing/corrupt referenced manifests
stop replay; they never silently select today's prompts. Query metadata, provider
usage/provenance and existing OTel spans carry identity hashes. Actual provider
config is recorded before dispatch through the existing usage ledger.

The image content policy's shipped negative/blocked lists are catalog defaults.
The old TOML remains an explicit compatibility example/override in locked mode.
`FLINT_GRAPH_NARRATIVE_IMAGE_CONTENT_POLICY` and managed Langfuse mode cannot be
combined. Custom private override files are never discovered or uploaded. Image
jobs retain constructed prompts and normalized policy hashes across retries.
A keyword list and negative conditioning do not certify an image's content.

## Staging operations

Bind only the authenticated TLS reverse proxy externally; restrict upstream UI,
S3 and database/cache ports. Provision operator identities/SSO and separate
organizations for environments where OSS project role overrides are unavailable.
Protected labels and immutable vendor audit persistence are Enterprise features;
Git review and release receipts remain required in OSS. Coordinate ingress and
secrets with #43. Back up PostgreSQL, all S3 buckets, ClickHouse data and the
reviewed lock/receipts together; test restoration and key rotation in a separate
instance. Set retention and quotas explicitly for that deployment. This local
fixture does not qualify HA, production retention or bulk trace ingestion.
