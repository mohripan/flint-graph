# Coordinated source retrieval delivery

Tracking: [#59](https://github.com/mohripan/flint-graph/issues/59).
Decision: [ADR 0022](../adr/0022-bounded-coordinated-source-retrieval.md).

## Diagnosis and implementation

Public cross-report run `57f00cc6-5a5d-421a-93cd-e0a91741de95` contained no
candidates from the required Philip Morris source. Evidence was lost before
fusion/context packing. A competing-source regression failed with only one
canonical evidence record before coordinated retrieval; the corrected fixture
uses a boundary answer provider rather than expecting the single-sentence
deterministic generator to synthesize two facts.

Two/three explicit named possessive clauses now share each lexical/vector
retriever's existing allowance and retain original query intent for generation.
Round-robin ranks, deduplication, clause metadata and source filters preserve
inspectable provenance. Tests cover over-returning/duplicate external results,
three-source remainder allocation, unsupported requests and existing
required/partial failure policy. No agent tree, arbitrary rewriting or new model
call is introduced by the planner itself. Vector retrieval does embed each clause,
so call counts can increase while the candidate allowance stays fixed. Query
embedding usage is not currently written by that adapter to the persisted usage
ledger; real embedding-call accounting/budget qualification is separate work.
The usage figures below describe the recorded answer/support calls with
deterministic query embeddings, not a fully priced inference workload.

The first live candidate implementation still failed the strict cross-report
case: run `6ac0d592-3bfb-4700-ae67-d05b95c9d286` rendered only Devon's figure.
Read-only lexical probes showed that the source-attribution presentation suffix
pushed the correct Philip Morris chunk to rank 10; without it, the same evidence
ranked first. A regression failed before narrowly omitting that suffix from
retrieval clauses. Substantive qualifiers remain; the original question is
unchanged in the run and answer/support inputs.

## Live evidence

Unchanged dedicated public workspace `2eab2f78-208e-4eb9-97a2-087e40af0525`,
100 pinned FinQA report excerpts, retrieval index
`fc8aa4e9-6b7f-4283-99cf-efc850a472e1`:

- Final cross-report run `b07b18db-5c7e-4dce-98e5-a9e6ae2c3bb5` returned Devon's
  November 2007 agreed Gabon sale price **$205.5 million** and Philip Morris's
  2017 operating income **$11,503 million**, with two supported claims and no
  rejected claims.
- Both exact required documents were cited: Devon
  `abfd0ee2-b732-4c6b-a5f6-ec50a4119887` and Philip Morris
  `aaf3b26f-6200-4fd1-bae7-87f9e2073f7b`. The latter's lexical candidates received
  parent ranks 2/4 and rerank ranks 10/7, so reported recall@5 is not a claim that
  both required citations rank in the first five candidates.
- Real Ollama answer/support model remained
  `igorls/gemma-4-12B-it-qat-q4_0-unquantized-heretic:latest`, installed digest
  `2835c50a7b13c1e9c8ab58a4d08368e374ae5f33ce055afb0b8081bc006aef9f`.
  Embeddings remain deterministic fixtures; this does not qualify semantic
  embedding quality or production-scale retrieval.
- API was rebuilt with inspected provider/model settings preserved. No worker,
  telemetry service, source/index, private document or volume was removed.
- Isolated real browser session reopened the saved result from history without
  requesting new inference. Desktop 1280x900 and mobile 390x844 screenshots were
  visually inspected; both values/citations are readable and mobile text wraps.
  Session closed; frontend remains running at port 5173.

## Gates and remaining failures

- `uv run pytest -q`: **774 passed, 13 conditional skips**.
- PostgreSQL-enabled decomposition/orchestration/planning/query API suite:
  **105 passed, 3 conditional skips**; scratch schemas clean up independently of
  the public corpus.
- `uv run ruff check .`, `uv run mypy` (154 files), `uv lock --check`, exact
  deterministic Acme eval gate, Alembic SQL (1,026 lines),
  `docker compose config --quiet` and `git diff --check`: passed.
- Frontend source tests/typecheck/build and the synthetic responsive suite were
  not rerun because frontend code did not change. The real saved-result browser
  checks above passed. An initial browser wait for a search input timed out
  because history is collapsed; explicitly opening history resolved the test
  setup, without changing product code.
- First unchanged 12-case nightly capture remained **failed**, useful-answer
  rate 0.7 and cross-report failure. Final unchanged 12-case capture **passed the
  configured gate**, useful-answer rate **0.8**, support/citation validity and
  abstention accuracy/recall 1.0, must-cite satisfaction 1.0, recall@5 0.95,
  p95 latency **13.488 seconds**, actual usage **59,744 input / 2,682 output
  tokens**, and foreign run/events/provenance probes returning 404.
- Gate success is **not all cases passing**: 8/10 answerable cases and both
  expected abstentions passed. `pm-rrp-2017` and `amex-average` still fail their
  independent assertions; #71 rubric wording review and #70 arithmetic/unit
  validation remain necessary. Model entailment approval is not arithmetic proof.
- Redacted local reports preserve both captures:
  `notes/financial-nightly-coordinated-2026-10-10.json` and
  `notes/financial-nightly-coordinated-final-2026-10-10.json`. No dataset, approved
  source, rubric, threshold or baseline was changed to achieve the gate.

Local compute is unpriced, not free. This fixes the narrow independently labeled
multi-report regression, not arbitrary query completeness, chained conversation,
large-corpus performance or production release qualification.
