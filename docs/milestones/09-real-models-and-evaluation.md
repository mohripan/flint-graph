# Milestone 09: Real models by default + evaluation platform

## Status

Planned. Not yet implemented. This document describes the intended scope; ADR 0009 and
ADR 0010 are `Proposed` until the milestone lands.

## Goal

Turn AtlasRAG from a system that *can* orchestrate a grounded, faithfulness-checked answer
into one that produces a *real* answer by default, and give the team the measurement harness
needed to change models, prompts, and retrieval safely.

Two coupled deliverables:

1. **Real models as the default runtime.** Real answer generation and support checking
   (Claude, behind the existing `AnswerGenerator` / `SupportChecker` protocols) and real
   embeddings (OpenAI-compatible or local, behind `EmbeddingModel`). Real providers become
   the default for `local`/`staging`/`production`; deterministic providers remain the
   default for `test` so the suite stays offline and hermetic.

2. **An evaluation platform.** Golden datasets, an offline experiment harness, regression
   thresholds, retrieval ablations, prompt/model comparisons, and CI quality gates.

They ship together deliberately: making a real model the default without a way to measure
quality is an unmeasured gamble. The evaluation platform is what makes the default change
defensible.

## Why now

Through Milestone 08 the query path defaults to deterministic ("smoke-test") providers for
embeddings, classification, reranking, answer generation, and support checking. The
orchestration, faithfulness, and provenance machinery is real; the models are not. A user
asking a question out of the box receives a deterministic non-answer. Milestone 09 makes the
default answer a genuine one — but only behind a harness that can tell whether any given
model/prompt/retrieval change is an improvement or a regression.

## Key constraints

- **Anthropic provides no embeddings endpoint.** Claude covers answer generation and the LLM
  support judge only. Embeddings come from an OpenAI-compatible endpoint or a local model.
  The two concerns are configured and evaluated independently.
- **Changing the embedding model requires a new retrieval index version and a backfill.**
  Chunk embeddings are keyed to `(chunk_hash, retrieval_index_version)`; a real embedding
  model changes both dimensions and vectors. Milestone 06's index-version + backfill
  machinery is the supported path.
- **The offline invariant holds.** The full test suite and the CI eval gate run without live
  model services. This is preserved via env-aware defaults, not by weakening the invariant.
- **Provider SDK objects never enter application contracts.** The Anthropic integration lives
  at the infrastructure edge and returns the existing provider-neutral contracts, exactly as
  the Ollama adapters do.

## Planned scope

- Anthropic answer generator and support judge adapters (`infrastructure/anthropic.py`),
  behind the `AnswerGenerator` / `StreamingAnswerGenerator` / `SupportChecker` protocols.
- Env-aware provider defaults and key validation in configuration.
- Real embeddings as the non-test default, with the documented index-version + backfill path.
- An evaluation library (`src/atlas_rag/evaluation/`) and `atlas-eval` CLI: golden datasets,
  metrics (retrieval / faithfulness / correctness / operational), an experiment runner,
  retrieval ablations, model/prompt comparisons, and baseline-driven regression checks.
- Golden dataset v1 over a fixed, reproducibly-ingested eval corpus.
- CI quality gates: a fast offline deterministic gate on every PR, and a secrets-gated
  live-model eval nightly / pre-release.

## Contracts and decisions

- `docs/architecture/evaluation-contract.md` — dataset schema, metric definitions, experiment
  and report formats, and threshold/baseline semantics.
- ADR 0009 — real models by default with an offline-safe, env-aware default.
- ADR 0010 — the evaluation platform and CI quality gates.

## Expected invariants (to be enforced when implemented)

- The test environment resolves to deterministic providers; the full suite runs offline.
- Selecting a real provider without its credentials fails fast at startup with a clear error.
- Every evaluated answer citation resolves to a packed context record (existing invariant,
  asserted by the eval harness).
- The offline CI eval gate is network-free and reproducible.
- The live-model eval never runs in the PR gate; it is nightly / pre-release only.
- Changing the embedding model is accompanied by a retrieval index version bump and backfill.
- Baseline metric changes are explicit, reviewed changes — never silent.
