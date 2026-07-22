# ADR 0010: Evaluation platform and CI quality gates

## Status

Accepted. Implemented in Milestone 09.

## Context

ADR 0009 makes real models the default runtime. That change — and every future change to a
model, a prompt, an embedding model, or the retrieval mix — alters answer quality in ways that
are invisible without measurement. Today there is no way to answer "did this change make
answers better or worse?" The `evals/` tree exists (`datasets/`, `experiments/`, `reports/`)
but is empty, and `tests/fixtures/query_orchestration_eval_cases.json` provides deterministic
behavior fixtures, not quality metrics over a labeled corpus.

We need a repeatable way to measure retrieval and answer quality against known-good data,
compare configurations, and block regressions in CI — without violating the invariant that the
default test path runs offline.

## Decision

Build an evaluation platform with a provider-neutral core, file-based datasets and reports, and
a two-tier CI gate.

1. **Golden datasets over a fixed corpus.** A reproducibly-ingested eval corpus plus labeled
   queries (expected answer or expected-abstain, relevant chunk/entity IDs, must-cite sources,
   query type). Datasets and reports are files under `evals/`; the schema is defined in
   `docs/architecture/evaluation-contract.md`.

2. **An offline experiment harness** (`src/flint_graph/evaluation/`, driven by an `flint-graph-eval`
   CLI). It runs a dataset through the pipeline under a named configuration (which providers,
   which retrieval mode) against the fixed corpus and emits per-query results plus aggregate
   metrics: retrieval (recall@k, precision@k, MRR, nDCG@k), faithfulness (supported-claim
   ratio, citation validity and correctness, abstention precision/recall), answer correctness,
   and operational (latency, token, cost).

3. **Retrieval ablations and model/prompt comparisons** as first-class experiment shapes: run
   the same dataset across lexical-only / vector-only / graph-only / fused retrieval, and
   across provider configurations (deterministic vs Ollama vs Claude; embedding model A vs B;
   support judge on/off; effort levels), producing side-by-side reports with metric and cost
   deltas.

4. **Baseline-driven regression thresholds.** Accepted metric values are stored per
   (dataset, config) in a baseline file. A run compares against the baseline with per-metric
   tolerances and fails on regression. Baselines change only through an explicit, reviewed
   `--update-baseline` action — never silently.

5. **Two-tier CI quality gates.**
   - *PR gate (every change):* fast, offline, hermetic — the deterministic configuration over
     a small golden set with fixed thresholds. Runs inside `make check`. Preserves the offline
     invariant.
   - *Live gate (nightly / pre-release):* real Claude + real embeddings over the full golden
     set, gated behind credentials as CI secrets. Posts a report and checks regression
     baselines. Gates promotion, not PRs.

## Consequences

- Model, prompt, embedding, and retrieval changes become measurable and comparable rather than
  guessed; the real-model default from ADR 0009 becomes defensible with numbers.
- The PR gate stays offline and free; contributors keep a hermetic test loop.
- The live gate carries real cost and depends on external services; query counts are bounded
  and per-run cost is logged, and it never runs in the PR path.
- Reports and baselines are files in the repo, so quality history is versioned and reviewable
  in PRs alongside the change that moved it.
- Golden datasets require curation and maintenance; coverage is stated explicitly and grown
  over time rather than silently sampled.

## Alternatives considered

### Extend the existing behavior fixtures instead of a metrics platform

`query_orchestration_eval_cases.json` verifies deterministic behavior, not quality over a
labeled corpus, and cannot express recall@k, abstention precision, or cross-config comparison.
Keeping only behavior fixtures would leave quality unmeasured. Rejected; the behavior fixtures
remain, complemented by the metrics platform.

### Run live-model evals on every PR

Highest fidelity per change, but slow, costly, credential-dependent, and it breaks the offline
invariant. Rejected in favor of the two-tier split (offline deterministic on PRs, live nightly).

### A hosted third-party eval service

Faster to start, but it moves tenant corpus content and answer data to an external system,
conflicts with the PostgreSQL-authoritative and security-boundary posture, and couples quality
gating to a vendor. Rejected for the MVP; the file-based, in-repo harness keeps data and history
local and reviewable.

### Store eval runs in PostgreSQL

Considered for queryability, but reports are naturally file-shaped, benefit from living in the
repo (versioned, diffable in PRs), and do not need transactional guarantees. No migration is
planned unless a concrete need for queryable eval history emerges.
