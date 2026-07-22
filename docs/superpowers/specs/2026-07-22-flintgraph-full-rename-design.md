# FlintGraph Full Rename Design

## Summary

The project will be renamed from AtlasRAG to FlintGraph across the full codebase. The
rename is intentionally breaking because the project has not been published, has no
public repository, and has no external users depending on the current names.

## Naming Map

| Current name | New name |
| --- | --- |
| `AtlasRAG` | `FlintGraph` |
| `atlas-rag` | `flint-graph` |
| `atlas_rag` | `flint_graph` |
| `ATLAS_` | `FLINT_GRAPH_` |
| `atlas-eval` | `flint-graph-eval` |
| `atlas-rag-api` | `flint-graph-api` |
| `atlas-rag-frontend` | `flint-graph-frontend` |
| `urn:atlas-rag:error:*` | `urn:flint-graph:error:*` |

The Python distribution name will be `flint-graph`, and the import package will be
`flint_graph`. The frontend package name and browser title will use FlintGraph.

## Scope

The rename applies to:

- Python package paths, imports, entrypoints, module docstrings, and build metadata.
- CLI command names and all documentation that references those commands.
- Environment variable prefix and documented configuration examples.
- Docker image defaults, runtime user names, compose service defaults, object-store
  bucket defaults, database default credentials where they are project-specific, and
  retrieval projection default names.
- FastAPI metadata, problem detail URNs, service names, logging/tracing service names,
  and other generated identifiers that currently include Atlas.
- Tests, fixtures, evaluation datasets, CI workflows, and runbooks.
- Frontend metadata, page title, visible project name, and package lock metadata.
- Repository handoff documentation such as `README.md` and `AGENTS.md`.

The rename does not include a compatibility layer for old `atlas_rag`, `atlas-eval`,
or `ATLAS_` names. Existing local Docker volumes, object buckets, database users, or
environment files may need manual cleanup or recreation after the rename.

## Migration Order

1. Rename `src/atlas_rag` to `src/flint_graph`.
2. Update `pyproject.toml` package metadata, Hatch build package path, mypy package
   target, and script entrypoints.
3. Rewrite Python imports from `atlas_rag` to `flint_graph`.
4. Replace public and internal display names from AtlasRAG to FlintGraph.
5. Replace configuration prefix and settings examples from `ATLAS_` to
   `FLINT_GRAPH_`.
6. Update compose, Docker, CI, evaluation commands, docs, frontend package metadata,
   and lockfiles.
7. Update tests and fixtures that assert exact package names, error URNs, source URIs,
   index names, or CLI command text.
8. Run focused searches for leftover Atlas names and classify any remaining hits as
   intentional historical references or required follow-up changes.

## Behavior

Runtime behavior should remain unchanged except for names and identifiers. Tenant
filtering, ingestion, extraction, graph resolution, retrieval, query orchestration,
faithfulness checks, and evaluation semantics must stay the same.

The renamed environment variables are the only supported variables after this change.
For example, `ATLAS_ENV=test` becomes `FLINT_GRAPH_ENV=test`. The application should
not silently read both prefixes because that would preserve the old project identity
and increase configuration ambiguity before the project has external users.

## Verification

After implementation, run the narrowest meaningful verification first and prefer the
full set because this is a broad mechanical change:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
```

Also run repository searches for stale names:

```powershell
rg -n "atlas-rag|atlas_rag|AtlasRAG|ATLAS_|atlas-eval|urn:atlas-rag|atlas" -S .
```

Any skipped verification must be reported with the reason.

## Risks

- Local `.env` and Docker volumes may still contain old Atlas names. The implementation
  should update tracked examples but should not assume existing local state was reset.
- Broad text replacement can accidentally modify historical documentation in misleading
  ways. The implementation should inspect leftover matches and preserve meaningful
  history only when it is clearer than rewriting it.
- Lockfiles and generated metadata can be sensitive to hand edits. Prefer package
  manager commands where practical, and inspect diffs when generated files change.
- Windows path and import renames can leave stale caches. Verification should run from
  a clean shell after the package directory has been renamed.

## Acceptance Criteria

- `uv run pytest`, `uv run ruff check .`, and `uv run mypy` pass.
- The renamed CLI command `uv run flint-graph-eval` is available and replaces
  `atlas-eval` in docs and CI.
- Application imports use `flint_graph` with no remaining `atlas_rag` imports.
- Tracked configuration examples use `FLINT_GRAPH_` variables.
- User-facing product text says FlintGraph.
- Any remaining Atlas references are intentionally documented as historical context or
  removed before handoff.
