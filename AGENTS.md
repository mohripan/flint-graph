# Agent Handoff Guide

## Active product direction (2026-10-27)

The user approved an authored narrative game studio with Godot/GDScript export
first. Read `docs/product/narrative-game-studio.md`, ADR 0035 and the active section
of `docs/ROADMAP.md` before selecting work. Milestones 30–38 supersede the older
automatic research/financial queue; historical deliveries and security invariants
remain valid. The M30 written spec was approved for implementation on 2026-10-27;
the user authorized one review sub-agent and autonomous continuation. Preserve
the unrelated uncommitted #109 trace-probe work; do not stage, discard or resume it
as part of the product pivot. M30 package loading, reference playback/saves and
Godot source export/player and real browser qualification are delivered.
M31 #123 studio editor and isolated local Godot preview are live qualified with
green CI/container smoke. #124 now has qualified ledger/lifecycle APIs, execution
fences/private input loading, bounded USTAR/ZIP codecs, explicit Linux image
preparation, trusted Godot child/watchdog and standalone host runner. Actual
PostgreSQL recoveries, native export/tamper rejection, absent-worker watchdog and
real host-task cancellation passed. Read the M31 progress/release contract and
`docs/reports/2026-10-30-narrative-build-runner.md` plus linked child/execution
reports for exact scope. Immutable storage/publication and authorized downloads
are now qualified too (real MinIO, PostgreSQL and17 HTTP calls with actual engine
build/downloaded-source import): read `docs/reports/2026-10-30-narrative-release-publication.md`.
The relay/workflow/activities now pass connected real Temporal/PostgreSQL/Godot/
MinIO/authorized-download qualification; see
`docs/reports/2026-10-30-narrative-temporal-worker.md`. Separate operator worker/
relay processes, periodic closed-run recovery and fair bounded expired cleanup
now have real process-kill/restart, active-cancel/retry and natural-expiry proof:
`docs/reports/2026-10-30-narrative-build-recovery.md`. Owned worker/relay receipts
are in ignored `notes/narrative-worker-owned.json` / `narrative-relay-owned.json`;
preserve their private root/queue across restarts. The Studio Releases dialog and
the live author→save→build→download→play proof complete #124/M31:
`docs/reports/2026-10-30-narrative-releases-ui.md`. That proof found that build
children need a bounded writable `/tmp`; otherwise Godot packs an empty
`project.binary` and the browser build black-screens. The host now requires the
`/tmp` tmpfs and rejects such packs. The owned local API admits releases with the
existing builder pins. Preserve private owned fixtures.
On 2026-10-30 the user made chat-driven creation the primary workflow
([ADR 0038](docs/adr/0038-conversational-authoring-through-reviewed-proposals.md),
#168): a Studio Assistant panel proposes bounded story edits that become revisions
only on acceptance. It runs as fenced Temporal jobs via the opt-in
`narrative_assistant_worker` with local Ollama by default; read
`docs/reports/2026-10-31-narrative-assistant.md` and
`docs/runbooks/narrative-assistant.md`. The owned assistant worker receipt is
`notes/narrative-assistant-owned.json`. #171 moved the assistant to a full-page
Studio view whose turns stream steps, thinking and reply text from durable
PostgreSQL events (migration 0023, IDs-only Temporal history); Ollama `think` is now
explicit and budgeted. Read `docs/reports/2026-10-31-assistant-live-turns.md`.
On format 2 the assistant (prompt v2) edits sprites, framing, colours, stage nodes,
expressions and the theme, uses library files by ID, and suggests image jobs that
the creator starts with Generate: `docs/reports/2026-10-31-assistant-v2-tools.md`.
Prompt v3 asks for missing character names, outfits and image intent before proposing;
transparent sprites default to high resolution. Accepted image suggestions now resolve
to durable server jobs by proposal ID and original operation index. Assets discovers
background jobs across views, and inherited stage image pickers show their effective
images. Read `docs/reports/2026-10-31-assistant-image-actions.md`; no migration or runtime
bump is involved. Existing owned API/assistant processes need an owner-managed reload
to use the new endpoints/prompt; never restart another session's processes.
Expressions (ADR 0041 slice A, migration 0026) repaint only the face of an approved
base sprite as `character_expression` image jobs, so expressions swap on stage without
jitter; read `docs/reports/2026-10-31-character-expressions.md`. Poses (slice B) are
planned. Slice C (migration 0030) draws event CGs of one or two characters from an approved
image of each through a pinned IP-Adapter Plus (ViT-H): Assets → CGs → Generate CGs,
`scene_art` image jobs, opaque 1344×768 candidates. The image worker needs the optional
`FLINT_GRAPH_NARRATIVE_IMAGE_IP_ADAPTER_*` pin; read `docs/reports/2026-10-31-scene-art-cgs.md`.
Two-character CGs are experimental (7 of 12 seeds keep both looks; eight candidates per
Generate); M40 #185 owns improving that baseline.
Downloaded local generation models
(Animagine XL 4.0, Kokoro-82M, ACE-Step 3.5B) are verified under ignored
`notes/models/`; no generation pipeline exists yet. The Studio rail is now a
Godot-style scene hierarchy (#169): scenes are line chains projected from the node
graph, folders live in an editor-only versioned layout (migration 0021), and a
script editor edits a whole scene. Long-form limits (10k nodes / 5 MB) are #172;
read `docs/reports/2026-10-31-scene-hierarchy.md`. Character creation (#170 first
slice, ADR 0039, migration 0022) generates portraits locally with Animagine XL 4.0
through the opt-in `narrative_image_worker` and an isolated child in
`runtimes/imagegen` (its own uv lock, CUDA 12.8); read
`docs/reports/2026-10-31-character-creation.md` and
`docs/runbooks/narrative-image-generation.md`. Portraits are editor metadata until
the #128 export binding puts them in playtests and releases. The owned image worker
receipt is `notes/narrative-image-owned.json`. ADR 0040 plans the visual novel stage,
theme and story package v2 in four slices. Read the design's "Review changes"
section before starting slices 2–4. Slice 1, the asset library (uploads with rights
declarations and generated backgrounds, migration 0024), is delivered; read
`docs/reports/2026-10-31-asset-library.md`. Slice 2, story package v2, is delivered
behind `narrative_package_v2_enabled`, which is off: the format, reference player,
saves, asset binding by SHA-256, server-built NOTICES and the explicit upgrade. Read
`docs/reports/2026-10-31-story-package-v2.md`. Slice 3 (runtime 0.3.0) plays v2
everywhere: Godot `vn_view.gd`, playtests with transferred asset bytes and a revision
asset endpoint, and release builds with assets; read
`docs/reports/2026-10-31-vn-stage-runtime.md`. Slice 4 (Studio editors: Look tab, scene
stage panel, line expressions, character sprites, upgrade button) completes ADR 0040; the
flag now defaults on and new projects start on v2. Read
`docs/reports/2026-10-31-vn-studio-editors.md`; editor logic is in
`frontend/src/narrative/stageModel.ts`. Runtime 0.4.0 adds stage framing (character size and
top, free horizontal placement); read `docs/reports/2026-10-31-stage-framing.md`. Character jobs can
ask for high resolution (2× hires fix: Lanczos upscale plus a light img2img repaint, migration 0027,
on by default for sprites); read `docs/reports/2026-10-31-high-resolution-sprites.md`. Owned playtests need
`VITE_FLINT_GRAPH_PREVIEW_ORIGIN` on the frontend dev server.
The whole local Studio now starts with `uv run python tools/narrative/studio.py`
(API, four workers, playtest server, frontend), configured by the git-ignored
`studio.local.env` (template `tools/narrative/studio.env.example`; this machine's copy
holds the owned fixture settings, so never print it). It replaces the
`notes/narrative_owned_process.py` and `notes/serve-main-studio-api.py` starts. The owned PostgreSQL, MinIO and Temporal
fixtures now use Docker volumes with fixed ports
(`notes/persist-narrative-fixtures.py`). The earlier tmpfs fixtures lost all data on
a Docker restart.
Runtime 0.5.0 adds event CG overlays and an independent local gallery (#161 presentation,
[ADR 0042](docs/adr/0042-event-cgs-and-gallery.md)). Format 2 stage nodes use optional
`cg` (image ID, null clears); saves missing it load null. Gallery unlocks persist by
story ID outside slots in exports and stay in memory in playtests. The Studio stage
panel picks CGs and previews the overlay; Assets → CGs browses and uploads the image
library with a dedicated CG panel. See
`docs/reports/2026-10-31-event-cgs.md` for parity, private builder/preview and real
release qualification. CG generation from a character's approved image is ADR 0041 slice C.
[ADR 0043](docs/adr/0043-asset-folders-and-line-voices.md) adds editor-only asset folders
(migration 0028; automatic groups by kind and character) and voiced lines on runtime 0.6.0
(0.6.1 plays the first voiced line in playtests and adds a web start screen when sound is blocked):
format 2 `audio` assets (canonical WAV) and an optional line `voice` (full or a
vocalization such as "fufu"; silent by default), played by all four implementations with a
player Voice slider. Clips come from Kokoro-82M on the GPU (CPU fallback) through the opt-in
`narrative_voice_worker` and the isolated `runtimes/voicegen` child (migration 0029; a
Kokoro voice per character profile), or from WAV uploads. Read
`docs/reports/2026-10-31-asset-folders-and-line-voices.md` and
`docs/runbooks/narrative-voice-generation.md`; the launcher's `voice` service needs the
voice settings in `studio.local.env`.
M31 #122 adds authorized immutable text revisions
with recoverable conflicts; read `docs/milestones/31-authored-narrative-studio.md`
and the M30 report for actual progress before claiming a complete authoring product.

## Project Snapshot

#134 now has the Langfuse authoring/reviewed-lock decision contract in ADR 0044,
`docs/architecture/prompt-catalog-inventory.md` and the ADR 0029 prompt-management
threat addendum. `docs/reports/2026-11-01-langfuse-prompt-contract.md` records the
compatibility qualification: server 4.72.0 / isolated SDK 4.15.0 with existing
OTel 1.43.0. No Langfuse service, runtime resolver, dependency or prompt migration
is enabled by that delivery; #135–#140 remain implementation work. Image content
policy is inventoried for a coordinated typed-config migration, not relaxed or
replaced here. Keep #79 trace export separate from prompt management.

The user added #133–#167 on 2026-10-30: M35 prompt management, M36 context
engineering, M37 controlled memory, M38 package-v2 visual novel presentation,
plus shared conversations and narrative assistant/art work. Read the updated
`docs/product/narrative-game-backlog.md` dependency map. #124's bounded v1
release work is delivered; #134/#135 precede #126, while #140 follows #126. Package v2
requires #124/#128/#157 and preserves existing v1 releases/saves. Planned issues
are not delivered functionality; the final #132 game should exercise M38 parity.

FlintGraph is an early GraphRAG platform. Through Milestone 13 it implements the ingestion control plane, a real Temporal-backed content pipeline, provenance-rich staged extraction proposals, a resolved knowledge graph with reviewable reversible merges, rebuildable retrieval indexes, LangGraph-backed query orchestration with streamed, faithfulness-checked, citation-bearing answers and provenance APIs, real-model defaults outside tests, an offline evaluation quality gate, document lifecycle cleanup, an OIDC-backed workspace access boundary for MVP use, and controlled-deployment public API hardening.

Implemented path:

```text
API intake -> immutable raw object in MinIO
    -> durable ingestion job + outbox message
    -> outbox relay -> Temporal ingestion workflow
    -> worker: verify hash -> parse -> chunk -> extract staged proposals
    -> verify exact evidence spans + persist extraction run/invocation/staged records
    -> proposal candidates
    -> per-tenant staged resolution (auto attach / review / new entity)
    -> aggregate relationships
    -> project resolved graph into Neo4j
    -> index chunks into PostgreSQL embeddings + Neo4j vectors + OpenSearch lexical records
    -> primitive lexical/vector/neighborhood retrieval APIs
    -> LangGraph query run -> classify/link/retrieve/fuse/rerank/pack
    -> draft answer -> repair citations -> support check -> abstain/finalize
    -> persisted SSE events + inspectable query run + answer provenance
    -> offline golden-dataset eval gate + optional secrets-gated live eval
    -> OIDC-authenticated workspace users with role-scoped MVP setup and app flows
    -> explicit CORS/trusted-host/TLS/request-limit/SSRF/rate-limit deployment boundary
```

PostgreSQL is the system of record for the control plane, identity, workspace membership, extraction provenance, staged proposals, resolved graph, retrieval index versions, embeddings, coverage, backfill state, query runs, query events, candidates, context packs, answer metadata, answer claims, support decisions, and answer provenance. Neo4j and OpenSearch are idempotent, rebuildable projections. MinIO stores immutable raw and derived artifacts. Evaluation datasets, recorded evaluations, reports, and baselines are file-based under `evals/`. The API serves workspace, document/job, graph, review, audit, setup/readiness, index inspection, backfill, lexical search, vector search, graph-neighborhood, query-run, query-event, SSE query streaming, answer-provenance, and citation-provenance endpoints; dedicated extraction inspection endpoints are deferred.

Earlier milestones (durable dispatch, content pipeline) remain in place; see `docs/milestones/`.

## Ground Rules

- Document durable decisions and completed milestone behavior under `docs/`.
- Use `notes/` for scratch planning, manual test notes, and working handoff context. `notes/` is gitignored.
- Add or update tests before changing implementation behavior.
- Prefer focused changes that preserve the current modular shape.
- Do not treat `X-Tenant-ID` alone as authentication. In OIDC mode it is a workspace selector that must be authorized through server-side membership.
- Do not revert unrelated user changes in the working tree.

## Useful Commands

```powershell
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
docker compose up --build
docker compose down -v
```

Convenience make targets exist for Unix-like shells:

```bash
make test
make lint
make typecheck
make eval-gate
make check
make relay
make worker
```

On Windows PowerShell, running the `uv` and `docker compose` commands directly is usually clearer than relying on `make`.

## Local Services

Docker Compose exposes:

- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Temporal Web UI: `http://localhost:8233`
- Grafana: `http://localhost:3000`
- Neo4j browser: `http://localhost:7474` (user `neo4j`, password `flintgraphpassword`)
- PostgreSQL host port: `localhost:55432`
- Temporal gRPC host port: `localhost:7233`
- Neo4j Bolt host port: `localhost:7687`
- OpenSearch: `http://localhost:9200`

The `temporal` compose service uses `temporalio/temporal:latest` with `server start-dev --ip 0.0.0.0 --namespace default`. Temporal's development server includes a Web UI by default.

## Key Files

- `src/flint_graph/api/routes/documents.py`: document, ingestion job, cancellation, and job event endpoints.
- `src/flint_graph/application/services/ingestion_jobs.py`: transactional document-version/job/event/outbox creation.
- `src/flint_graph/application/services/job_transitions.py`: explicit job state transition rules.
- `src/flint_graph/application/services/job_cancellation.py`: API-side cancellation and cancellation outbox creation.
- `src/flint_graph/application/services/outbox.py`: outbox append helper and trace-context capture.
- `src/flint_graph/application/services/outbox_relay.py`: pending outbox polling and Temporal dispatch.
- `src/flint_graph/infrastructure/temporal.py`: Temporal client adapter.
- `src/flint_graph/workflows/ingestion.py`: `IngestDocumentWorkflow`.
- `src/flint_graph/worker/activities/ingestion.py`: worker activities that mutate job state.
- `src/flint_graph/processes/outbox_relay.py`: long-running relay process.
- `src/flint_graph/processes/ingestion_worker.py`: long-running Temporal worker.
- `src/flint_graph/infrastructure/db/models.py`: SQLAlchemy models.
- `migrations/versions/0002_outbox_messages.py`: outbox migration.
- `docs/runbooks/durable-ingestion-dispatch.md`: durable dispatch runbook.
- `docs/architecture/object-storage-contract.md`: future object-storage contract.
- `docs/adr/0003-transactional-outbox-and-temporal.md`: durable dispatch ADR.

Milestone 04 knowledge graph:

- `src/flint_graph/application/entity_resolution/`: pure normalization and scoring.
- `src/flint_graph/application/services/candidate_generation.py`: pg_trgm blocking.
- `src/flint_graph/application/services/resolution.py`: banded resolution + advisory lock + relationship aggregation.
- `src/flint_graph/application/services/entity_merge.py`: soft merge with undo log + unmerge.
- `src/flint_graph/application/services/review.py`: review-queue decisions.
- `src/flint_graph/application/services/graph_projection.py`: Neo4j projection/reconcile.
- `src/flint_graph/workflows/resolution.py` and `src/flint_graph/worker/activities/resolution.py`: per-tenant resolution workflow/activities.
- `src/flint_graph/api/routes/graph.py`: entity, review, merge/unmerge, and audit endpoints.
- `src/flint_graph/infrastructure/neo4j.py` and `neo4j_migrations.py`: Neo4j client and Cypher migration runner.
- `migrations/versions/0005_knowledge_graph.py` and `migrations/neo4j/`: graph schema.
- `docs/milestones/04-knowledge-graph.md`, `docs/adr/0004-postgres-authoritative-resolution-neo4j-projection.md`, `docs/architecture/knowledge-graph-contract.md`, `docs/runbooks/knowledge-graph-*.md`.
Milestone 05 provenance-rich extraction:

- `src/flint_graph/application/extraction_proposals.py`: provider-neutral proposal models and deterministic provider.
- `src/flint_graph/application/extraction_evidence.py`: exact quote evidence resolver.
- `src/flint_graph/application/services/provenance_extraction.py`: transactional extraction run, invocation, evidence, staged-record, and manifest persistence.
- `src/flint_graph/application/services/proposal_candidate_generation.py`: non-destructive proposal candidate generation.
- `src/flint_graph/application/services/staged_resolution.py`: canonical resolution over staged proposals.
- `src/flint_graph/infrastructure/ollama.py`: Ollama proposal adapter at the infrastructure edge.
- `migrations/versions/0006_provenance_extraction.py` and `0007_staged_resolution_state.py`: provenance and staged-resolution schema.
- `docs/milestones/05-provenance-rich-extraction.md`, `docs/adr/0005-staged-extraction-proposals-before-canonical-resolution.md`, `docs/architecture/extraction-proposal-contract.md`, `docs/runbooks/provenance-extraction-*.md`.

Milestone 06 retrieval indexes:

- `src/flint_graph/application/embeddings.py`: provider-neutral embedding contract and deterministic model.
- `src/flint_graph/infrastructure/embedding_factory.py`: shared embedding model construction.
- `src/flint_graph/infrastructure/embeddings.py`, `ollama.py`: embedding adapters.
- `src/flint_graph/application/services/retrieval_index_versions.py`: index-version transitions.
- `src/flint_graph/application/services/indexing.py`: document-version indexing, coverage, and projection replay.
- `src/flint_graph/application/services/index_backfill.py`: backfill job state and eligibility.
- `src/flint_graph/application/services/retrieval.py`: primitive retrieval API service layer.
- `src/flint_graph/application/services/lexical_projection.py` and `vector_projection.py`: projection record/query builders.
- `src/flint_graph/api/routes/retrieval.py`: index, backfill, lexical/vector search, and neighborhood endpoints.
- `src/flint_graph/workflows/indexing.py`, `backfill.py`: retrieval indexing and backfill workflows.
- `src/flint_graph/worker/activities/indexing.py`, `index_backfill.py`: worker activities.
- `src/flint_graph/processes/retrieval_index_reconcile.py`: projection reconcile command.
- `migrations/versions/0008_retrieval_index_ledger.py`, `0009_document_index_coverage.py`, and `migrations/neo4j/0002_chunk_vector_indexes.cypher`: retrieval schema.
- `docs/milestones/06-retrieval-indexes.md`, `docs/adr/0006-rebuildable-retrieval-indexes.md`, `docs/architecture/retrieval-index-contract.md`, `docs/runbooks/retrieval-index-*.md`.

Milestone 07 query orchestration:

- `src/flint_graph/application/query_orchestration.py`: provider-neutral query contracts and deterministic providers.
- `src/flint_graph/application/services/query_runs.py`: query-run ledger and event persistence.
- `src/flint_graph/application/services/query_planning.py`: deterministic classification and entity linking.
- `src/flint_graph/application/services/query_orchestration.py`: LangGraph query runtime.
- `src/flint_graph/application/services/query_fusion.py`: candidate fusion and reranking persistence.
- `src/flint_graph/application/services/query_context_packing.py`: citation-ready context packs.
- `src/flint_graph/application/services/query_answering.py`: answer events, citations, and completion.
- `src/flint_graph/api/routes/query.py`: query-run, event replay, and SSE streaming endpoints.
- `migrations/versions/0010_query_run_ledger.py`: query-run schema.
- `tests/fixtures/query_orchestration_eval_cases.json`: deterministic query eval fixtures.
- `docs/milestones/07-query-orchestration.md`, `docs/adr/0007-langgraph-query-orchestration.md`, `docs/architecture/query-orchestration-contract.md`, `docs/runbooks/query-orchestration-*.md`.

Milestone 08 grounded answer generation:

- `src/flint_graph/application/query_faithfulness.py`: citation repair, deterministic support checking, and abstention policy helpers.
- `src/flint_graph/application/services/query_faithfulness.py`: draft-to-verified-answer runtime pipeline.
- `src/flint_graph/application/services/query_answering.py`: verified answer event emission, answer-claim persistence, and completion.
- `src/flint_graph/application/services/query_provenance.py`: tenant-scoped answer and citation provenance readers.
- `src/flint_graph/infrastructure/ollama.py`: Ollama answer generation and streaming adapter.
- `src/flint_graph/infrastructure/answer_generator_factory.py`: answer generator and support checker provider selection.
- `src/flint_graph/api/routes/query.py`: query-run, event replay, SSE streaming, provenance, and citation endpoints.
- `migrations/versions/0011_answer_faithfulness.py`: query-run faithfulness columns and `query_answer_claims`.
- `tests/fixtures/query_orchestration_eval_cases.json`: deterministic query and faithfulness eval fixtures.
- `docs/milestones/08-grounded-answer-generation.md`, `docs/adr/0008-grounded-answer-generation-and-faithfulness.md`, `docs/architecture/answer-faithfulness-contract.md`, `docs/runbooks/grounded-answer-generation-*.md`.

Milestone 09 real models and evaluation:

- `src/flint_graph/infrastructure/anthropic.py`: Anthropic answer generation, streaming, and support checking adapters.
- `src/flint_graph/config.py`: env-aware provider defaults and credential validation.
- `src/flint_graph/evaluation/`: dataset loading, metrics, experiment runner, reports, baselines, recorded evaluators, and comparisons.
- `src/flint_graph/cli/eval.py`: `flint-graph-eval` CLI for offline scoring, comparisons, and baseline updates.
- `evals/datasets/acme-smoke/`: fixed golden corpus and labeled queries.
- `evals/experiments/acme-smoke.yaml`: offline/live experiment thresholds.
- `evals/reports/acme-smoke/`: deterministic recorded eval fixture and accepted baselines.
- `.github/workflows/ci.yml`: offline deterministic PR quality gate.
- `.github/workflows/live-eval.yml`: scheduled/manual secrets-gated live eval gate.
- `docs/milestones/09-real-models-and-evaluation.md`, `docs/adr/0009-default-real-models-offline-safe.md`, `docs/adr/0010-evaluation-platform-and-quality-gates.md`, `docs/architecture/evaluation-contract.md`, `docs/runbooks/real-models-developer.md`, `docs/runbooks/evaluation-*.md`.

Milestone 10 local-first usable RAG:

- `src/flint_graph/application/services/search_readiness.py`: tenant-scoped active-index search readiness summary.
- `src/flint_graph/infrastructure/ollama.py`: Ollama answer, embedding, extraction, and support-checking adapters.
- `src/flint_graph/application/services/query_runs.py`: persisted compact query diagnostics in query-run metadata.
- `src/flint_graph/api/routes/retrieval.py`: `/v1/search-readiness`.
- `src/flint_graph/api/routes/query.py`: query creation guard for searchable content.
- `frontend/src/pages/AskPage.tsx`: readiness-gated Ask flow and diagnostics panel.
- `frontend/src/pages/UploadPage.tsx`: backend readiness document status view.
- `docs/milestones/10-local-first-usable-rag.md`, `docs/adr/0011-local-first-ollama-readiness-diagnostics.md`, `docs/runbooks/local-ollama-rag.md`, `docs/runbooks/frontend-e2e-qa-guide.md`.

Milestone 12 MVP bootstrap and access boundary:

- `src/flint_graph/infrastructure/oidc.py`: Keycloak-compatible OIDC token verifier.
- `src/flint_graph/application/services/authz.py`: authenticated principal, user upsert, and workspace role checks.
- `src/flint_graph/application/services/workspaces.py`: workspace and membership service layer.
- `src/flint_graph/application/services/retrieval_bootstrap.py`: idempotent active retrieval-index bootstrap from settings.
- `src/flint_graph/api/dependencies.py`: current-user dependency and tenant viewer/member/admin authorization dependencies.
- `src/flint_graph/api/routes/workspaces.py`: workspace listing, creation, and member-management endpoints.
- `src/flint_graph/api/routes/retrieval.py`: system readiness, active-index bootstrap, active-index backfill, and backfill listing endpoints.
- `frontend/src/lib/auth.tsx`: dev/OIDC frontend auth provider.
- `frontend/src/lib/workspace.tsx`: server-backed workspace selection.
- `frontend/src/pages/SetupPage.tsx`: readiness, index bootstrap, and backfill UI.
- `migrations/versions/0014_identity_memberships.py`: users and workspace memberships.
- `docs/milestones/12-mvp-bootstrap-and-access-boundary.md`, `docs/architecture/security-boundary.md`.

## Current Invariants

- A document belongs to one tenant.
- Tenant-scoped reads return 404 for foreign resources.
- Every new ingestion attempt creates one immutable document version.
- Reusing an idempotency key in the same tenant returns the existing job.
- The initial `job.queued` event and `ingestion.job_queued` outbox message are written in the same API transaction as the job.
- Cancellation writes `job.cancelled` plus `ingestion.job_cancelled` before leaving the API transaction.
- The relay marks an outbox message `published` only after Temporal accepts the start or cancellation request.
- Job state changes go through explicit transition rules and append events.
- The relay prioritizes queued workflow-start messages before cancellation messages when both are available.
- Model output is staged and evidence-verified before it can affect canonical graph state.
- Accepted staged entities, relations, and claims retain at least one verified evidence span.
- Canonical graph mutation happens in deterministic resolution services, not provider adapters.
- Retrieval index versions are explicit and active per global or tenant scope.
- Chunk embeddings are tied to chunk hashes and retrieval index versions.
- Neo4j and OpenSearch retrieval records are rebuildable from PostgreSQL.
- Primitive retrieval APIs always apply tenant filters.
- Query APIs always apply tenant filters.
- Query runs use visible active retrieval index versions.
- Query events are persisted in monotonic per-run order.
- Every answer citation maps to a packed context record.
- Every persisted answer claim carries a support decision.
- Unsupported generated answers abstain rather than serving fabricated citations.
- Query provenance APIs apply tenant filters and resolve from PostgreSQL.
- `env=test` resolves model providers to deterministic values and remains offline.
- Non-test real provider selections validate required credentials at startup.
- Evaluation baselines are explicit reviewed files, never silently updated.
- The PR quality gate uses deterministic recorded evaluations and requires no live model service.
- Query creation requires at least one completed document-version coverage row for the selected active retrieval index.
- Search readiness is derived from PostgreSQL index coverage, not Neo4j or OpenSearch projection state.
- Query diagnostics are a compact derived summary persisted in query-run metadata; query events and provenance remain the detailed inspection source.
- OIDC mode requires a valid bearer token before tenant-scoped API access.
- `env=staging` and `env=production` reject dev auth unless explicitly overridden.
- `env=staging` and `env=production` require explicit public URL, CORS origins,
  trusted hosts, TLS, non-default object-store credentials, and enabled rate
  limiting.
- Tenant-scoped dependencies authorize `X-Tenant-ID` against active workspace membership.
- Workspace roles are ordered as viewer, member, admin, owner.
- Graph review/merge mutations, document deletion/cleanup retry, and retrieval setup/backfill require admin or owner.
- Document creation/upload/intake requires member, admin, or owner.
- Server-backed workspace, document list, setup readiness, backfill list, and query history are available to the frontend.
- URL intake blocks private/local network targets outside local/test unless
  explicitly allowed.
- Oversized uploads and body-bearing requests are rejected before persistence or
  background work.

## Temporal Notes

- Workflow name: `IngestDocumentWorkflow`.
- Task queue: configured by `FLINT_GRAPH_TEMPORAL_TASK_QUEUE`, default `ingestion`.
- Workflow ID: `ingestion-job-{job_id}`.
- Workflow memo stores `trace_context` from outbox headers.
- Workflow start uses duplicate-safe Temporal policies so retrying the relay does not create duplicate workflows.
- Cancellation dispatch uses the same workflow ID and calls Temporal workflow cancellation.
- Indexing workflow name: `IndexDocumentVersionWorkflow`.
- Backfill workflow name: `IndexBackfillWorkflow`.
- Indexing workflow ID: `index-document-version-{document_version_id}-{retrieval_index_version_id}`.
- Backfill workflow ID: `index-backfill-{job_id}`.

## Known Limitations

- Small local extraction models can produce sparse or noisy proposals; the pipeline validates evidence and persists accepted output faithfully.
- Dedicated extraction inspection APIs are not implemented yet; use PostgreSQL queries in the provenance extraction runbook.
- `unmerge` reverses the most recent merge and assumes no conflicting interleaved graph changes.
- Neo4j projection re-reconciles the whole tenant subgraph after each resolution rather than applying deltas.
- Trace context is captured and carried into Temporal memo, but automatic distributed span continuation inside workflows and activities is not complete.
- The local Temporal dev server is not production Temporal.
- The compose Temporal service currently uses the `latest` image tag, which is convenient for early local development but should be pinned before production-like environments.
- OpenSearch near-real-time indexing may require refresh or polling before a just-indexed chunk appears in search.
- Query API SSE execution is request-bound; it is not a durable background workflow.
- Deterministic query and support providers are useful for repeatable smoke tests, not production answer quality.
- Small local answer models can emit malformed or sparse draft claims; citation repair and support checking bound what reaches the persisted final answer.
- Non-test defaults select Anthropic for answer/support, so no-cost local development should explicitly set deterministic or Ollama query providers when no Anthropic key is available.
- The live eval workflow checks a live-captured recording file; capture automation is intentionally separate from the offline PR gate.
- Switching the local embedding provider/model/dimension requires a compatible retrieval index version and backfill before documents become searchable.
- Workspace creation is currently open to any authenticated user; invitation or system-admin bootstrap policy is deferred.
- OIDC group-to-workspace synchronization and SCIM lifecycle management are not implemented.
- The frontend stores the selected workspace ID and locally tracked transient upload jobs in `localStorage`; backend readiness and document/query lists are durable.

## Before Ending A Change

Run the narrowest meaningful verification, and prefer the full set when behavior changed:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
```

Tell the user exactly which commands passed and which were skipped.
