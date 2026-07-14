# Milestone 09: Real models by default + evaluation platform

## Status

Complete. Phases 1 through 8 are implemented.

## Goal

Milestone 09 turns the query path from a deterministic smoke-test answerer into a runtime that
can use real models by default outside tests, while adding the evaluation harness needed to
measure model, prompt, retrieval, and grounding changes.

The milestone preserves the offline invariant: `env=test` resolves to deterministic providers,
and the PR quality gate runs without network services or model credentials.

## Implemented Phase 1 Adapters

`src/atlas_rag/infrastructure/anthropic.py` adds Anthropic answer generation, streaming answer
generation, and support checking behind the existing provider-neutral protocols. The adapters
return `AnswerDraft`, `GeneratedAnswer`, and `SupportCheckResult` objects; SDK types stay at the
infrastructure edge.

## Implemented Phase 2 Configuration

`src/atlas_rag/config.py` resolves provider defaults by environment. Tests stay deterministic.
Local defaults to Ollama embeddings and Anthropic answer/support providers unless explicitly
overridden. Staging and production default to OpenAI-compatible embeddings plus Anthropic
answer/support providers. Missing credentials fail fast with clear validation errors.

## Implemented Phase 3 Real Embedding Defaults

Real embedding providers reuse the existing embedding adapters. `local` resolves to
`ollama`/`nomic-embed-text` with 768 dimensions; `staging` and `production` resolve to
`openai_compatible`/`text-embedding-3-small` with 1536 dimensions. Changing the embedding
provider, model, or dimension still requires a new retrieval index version and backfill.

## Implemented Phase 4 Evaluation Core

`src/atlas_rag/evaluation/` provides dataset loading, metric computation, experiment execution,
report I/O, baseline comparison, and threshold checks. The core is provider-neutral and can
score recorded evaluations or any injected query evaluator.

## Implemented Phase 5 Golden Dataset

`evals/datasets/acme-smoke/` contains a small fixed corpus and labeled queries covering
factoid, multi-hop, entity, and abstain-expected cases. Labels use stable document external IDs
and canonical entity names rather than pipeline-assigned UUIDs.

## Implemented Phase 6 CLI And Comparisons

`atlas-eval` scores recorded evaluations, writes reports, updates baselines explicitly, and
compares multiple configurations side by side. Experiment definitions live under
`evals/experiments/`; reports and accepted baselines live under `evals/reports/`.

## Implemented Phase 7 Quality Gates

The offline deterministic gate is committed as:

```bash
make eval-gate
```

`make check` now runs lint, typecheck, tests, and the eval gate. GitHub CI runs the same offline
gate on pull requests and pushes. A separate scheduled/manual `Live Eval` workflow is
secrets-gated and expects a live-captured `live-claude` recording before checking thresholds and
baselines, so PRs remain free and offline.

## Implemented Phase 8 Docs And Verification

Completed documentation:

- ADR 0009 accepted: real models by default with offline-safe env-aware defaults.
- ADR 0010 accepted: evaluation platform and quality gates.
- `docs/architecture/evaluation-contract.md`.
- `docs/runbooks/real-models-developer.md`.
- `docs/runbooks/evaluation-developer.md`.
- `docs/runbooks/evaluation-qa-guide.md`.
- README and AGENTS handoff updates.

Manual verification results are recorded in `notes/milestone-09/01-manual-verification.md`.

## Current Invariants

- `env=test` resolves answer, support, and embedding providers to deterministic values.
- The full automated suite and `make eval-gate` run without live model services.
- Selecting Anthropic providers without `ATLAS_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY` fails
  at startup.
- Selecting `openai_compatible` embeddings without base URL and API key fails at startup.
- Evaluation baselines move only through an explicit `atlas-eval baseline update` command.
- The PR eval gate uses committed deterministic recorded evaluations.
- The live eval workflow is scheduled/manual and secrets-gated; it is not part of PR CI.
- Changing embedding model or dimensions requires a new retrieval index version and backfill.
