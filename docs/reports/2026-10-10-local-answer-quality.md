# Fresh local answer-quality rehearsal

This is experimental evidence, not release qualification. The unchanged ten-query
`acme-smoke` v1 corpus was prepared through real public upload APIs and Temporal
ingestion. PostgreSQL coverage and both Neo4j vector/OpenSearch lexical visibility
passed for all six documents. Each capture created new runs and read persisted
retrieval/provenance; no expected-answer-derived source mappings or baseline edits.

Answer/support: local Ollama
`igorls/gemma-4-12B-it-qat-q4_0-unquantized-heretic:latest`.
Extraction and embeddings: deterministic, 384 dimensions. This does not measure
real extraction/embedding quality or Anthropic availability. The prepared workspace
used the existing global index; later workspace-scoped bootstrap does not alter it.

| Revision | Answer match (8 answerable) | Abstention accuracy (10) | Draft supported ratio | Scored rejected draft count* | Latency p95 |
| --- | --- | --- | --- | --- | --- |
| `af5bdb6` | 0.625 | 0.700 | 0.684 | 5* | 13.04 s |
| `2239506` | 0.750 | 0.700 | 0.941 | 1* | 14.60 s |
| `067da21` | 1.000 | 1.000 | 0.905 | 2* | 9.49 s |

\* These are the scorer's `unsupported_claim_count`: rejected draft claims on
non-abstained runs, **not** claims shown in final answers. The renderer omits them.
The strict gate retains this metric; a passing citation/rendering check must not
be misrepresented as passing every quality threshold.

All three captures have citation validity 1.0. All three **fail** the configured
gate: recall@1=0.625, recall@5=0.750 and MRR=0.750 remain below thresholds, with
draft support failures as above. Graph-oriented labels receive no retrieved
canonical entities in this deterministic-extraction rehearsal. A fresh run's
expected text match is a limited overlap metric, not independent human judgement.
One small English corpus and one local model cannot establish broad reliability.

The first capture exposed off-target multi-hop answers and cited no-answer
commentary. Shared answer rules improved draft discipline. The second exposed
support checks judging the entire question instead of each claim and skipping a
claim. Request-specific schema bounds, explicit per-claim semantics, duplicate
judgement rejection and a narrow English context-gap guard address those cases.
The final capture returned the expected Berlin/founder answers for the two
multi-hop queries and abstained for revenue and Initech CEO.

Raw JSONL/manifests/reports remain in gitignored `notes/acme-live-*.json*` for local
inspection, alongside persisted runs in the dedicated evaluation workspace. The
capture CLI rejects overwrite; repeated measurements need distinct output paths.
The runbook describes reproducible preparation/capture/scoring commands. Accepted
recorded baselines are unchanged. Token/cost fields in these captures are unknown;
aggregate zeros from the current scorer must not be read as measured usage or a
claim of zero infrastructure cost.

Next evidence: instrument capture with reported per-call usage/prompt identity,
run real embeddings/extraction, expand adversarial/multilingual coverage, add
question-completeness checks and evaluate strategy-specific fresh captures. The
remaining agent/CAG/delegation milestones are still proposed, not delivered.
