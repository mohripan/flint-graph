# Evaluation contract

> Status: Proposed (Milestone 09). Defines the dataset schema, metric definitions, experiment
> and report formats, and threshold/baseline semantics for the AtlasRAG evaluation platform.
> Implementation target: `src/atlas_rag/evaluation/` + the `atlas-eval` CLI, with data under
> `evals/`. See ADR 0010.

## Principles

- **Provider-neutral.** The harness evaluates the pipeline through the same provider-neutral
  contracts the runtime uses (`EmbeddingModel`, `AnswerGenerator`, `SupportChecker`, retrieval
  services). Swapping providers is a configuration change, not a code change.
- **Reproducible.** The golden corpus is ingested deterministically. Under a deterministic
  configuration a run is network-free and byte-stable, so it can gate PRs.
- **File-based and versioned.** Datasets, experiment definitions, reports, and baselines are
  files in the repo, reviewable in PRs alongside the change that moves a metric.
- **No silent truncation.** Any bound on coverage (query count, top-k, sampling) is recorded in
  the report.

## Layout

```
evals/
  datasets/<name>/
    corpus/                 # source documents for the fixed golden corpus
    queries.jsonl           # one labeled query per line (schema below)
    dataset.yaml            # dataset metadata (name, tenant, corpus manifest, version)
  experiments/<name>.yaml   # experiment definition (configs + retrieval modes + thresholds)
  reports/<name>/
    <config>.json           # per-query results + aggregate metrics for one config
    comparison.md           # human-readable side-by-side (ablations / model comparisons)
    baselines.json          # accepted metric values per (dataset, config)
```

## Dataset schema

### `dataset.yaml`

```yaml
name: acme-smoke
version: 1
tenant: eval-acme                 # dedicated eval tenant
corpus_dir: corpus/               # ingested reproducibly into `tenant` before a run
description: >
  Small factoid + multi-hop + abstain golden set over the Acme corpus.
```

### `queries.jsonl` (one JSON object per line)

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable query ID. |
| `query` | string | The user question. |
| `query_type` | enum | `factoid` \| `multi_hop` \| `entity` \| `abstain_expected`. |
| `expected_answer` | string \| null | Reference answer; `null` when `expect_abstain` is true. |
| `expect_abstain` | bool | True when the corpus does not support an answer. |
| `relevant_chunk_ids` | string[] | Chunk IDs that should be retrieved (retrieval metrics). |
| `relevant_entity_ids` | string[] | Entity IDs relevant to the query (graph retrieval). |
| `must_cite_sources` | string[] | Source IDs the answer must cite, when applicable. |
| `notes` | string | Optional human note (why this case exists). |

IDs refer to the deterministically-ingested corpus and are stable across runs.

## Metrics

### Retrieval (require relevant-id labels)

- `recall_at_k`, `precision_at_k` — for configured k values.
- `mrr` — mean reciprocal rank of the first relevant result.
- `ndcg_at_k` — rank-weighted gain.
- `hit_rate` — fraction of queries with at least one relevant result in top-k.

### Faithfulness

- `supported_claim_ratio` — supported claims / total claims (aggregate).
- `unsupported_claim_count` — count of surviving unsupported claims (should be ~0).
- `citation_validity` — fraction of citations resolving to a packed context record (asserted
  invariant; any failure is a hard error, not just a low score).
- `citation_correctness` — fraction of cited records that actually support their claim
  (judge-scored under a real config; lexical under deterministic).
- `abstention_precision` / `abstention_recall` — over `expect_abstain` labels.

### Answer correctness

- `answer_match` — normalized/exact match for short factoids; LLM-judge equivalence otherwise.
- `abstention_accuracy` — abstained exactly when `expect_abstain` is true.

### Operational

- `latency_ms_p50`, `latency_ms_p95`.
- `input_tokens`, `output_tokens` (when reported by the provider).
- `estimated_cost_usd` — from token counts and the config's model pricing.

## Experiment definition (`experiments/<name>.yaml`)

```yaml
dataset: acme-smoke
configs:                          # named provider/pipeline configurations
  deterministic:                  # the offline, PR-gate config
    embedding_provider: deterministic
    query_answer_provider: deterministic
    query_support_provider: deterministic
  claude:                         # the live, nightly config
    embedding_provider: openai_compatible
    embedding_model: text-embedding-3-small
    query_answer_provider: anthropic
    anthropic_answer_model: claude-opus-4-8
    query_support_provider: anthropic
retrieval_modes: [lexical, vector, graph, fused]   # ablation matrix (optional)
k_values: [1, 5, 10]
thresholds:                       # per-metric regression tolerances vs baseline
  supported_claim_ratio: { min: 0.80 }
  abstention_recall:      { min: 0.90 }
  recall_at_5:            { min: 0.70 }
  answer_match:           { min: 0.60 }
```

A configuration named `deterministic` is expected to be network-free and reproducible; it is
the one the PR gate runs. Configurations naming real providers require credentials and run only
in the live gate.

## Report format

`reports/<name>/<config>.json` contains:

- `dataset`, `config`, `run` metadata (git SHA, timestamp injected by the caller, coverage:
  query count, k values, any applied bound).
- `per_query`: for each query — retrieved IDs, generated answer, surviving citations, per-claim
  support decisions, abstained flag, and the computed metrics.
- `aggregate`: the metrics above rolled up across the dataset.

`comparison.md` renders ablations (per retrieval mode) or model/prompt comparisons (per config)
as a side-by-side table with metric and cost deltas.

## Baselines and thresholds

- `baselines.json` stores accepted aggregate metric values per (dataset, config).
- A run fails when any thresholded metric regresses beyond its tolerance relative to the
  baseline (or a fixed floor, when `thresholds` sets `min`/`max` directly).
- Baselines are updated only via an explicit `atlas-eval --update-baseline` action, reviewed in
  the PR that changes them. Baselines never move silently.

## CI gates

- **PR gate:** run the `deterministic` config over the golden set inside `make check`. Offline,
  hermetic, fast; enforces fixed thresholds. A regression fails the build.
- **Live gate (nightly / pre-release):** run the real-provider config(s) over the full golden
  set, gated behind credentials supplied as CI secrets. Emits reports, checks regression
  baselines, logs per-run cost. Never runs in the PR path.
