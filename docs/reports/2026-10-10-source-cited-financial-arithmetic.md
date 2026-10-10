# Independent source-cited financial arithmetic

Tracking: [#70](https://github.com/mohripan/flint-graph/issues/70).
Design and limits: [ADR 0023](../adr/0023-source-cited-bounded-financial-arithmetic.md).

## Outcome

The bounded payments-volume-per-transaction path now computes with independently
typed source operands and explicit unit scales. It can supply the result before
generation and verifies the returned claim again against its own citations.
Wrong or unverifiable results force whole-answer abstention, even if the ordinary
support ratio would permit two correct premises plus one wrong result. Draft
numbers are not repaired after generation, and a correct calculation cannot
override a support-model rejection.

Verified source values come from the pinned FinQA V/2008/page_17 excerpt at
commit `0f16e2867befa6840783e58be38c9efb9229d742`. Source label:
`finqa-f79869144af77eb6cf9463de8ca2f41e25024565744b72abd82d18e5d7c89a6d`.
The company row and billions-scale headers establish 637/5.0 = 127.4 in
reported money units per transaction. This source review is independent of the
model's arithmetic answer. Currency/report-year interpretation remains subject
to the existing source/support boundary, not independently proved by division.

## Red-to-green verification

Initial service regressions reproduced the model-approval gap; the exact wrong
result was served by an always-approving provider fixture. Persistence tests
then failed because the arithmetic audit did not yet survive database storage.
Preparation/provider-prompt tests likewise failed before introducing the typed
hint. Each behavior was implemented after its regression.

Final focused cases cover correct and wrong unit scales, another company/result,
formatted numbers, multiline/flattened tables, zero denominators, expressions,
missing units, oversized/inexact decimals, uncited/legacy evidence, contradictory
source hashes, wrong result units/entities, negation, non-atomic calculations,
premises-only output, model rejection and the eight-calculation ceiling. They
check exact value/header/entity spans and retention of original claims/judgments.
No expected financial values, document labels or company names are hardcoded
into implementation. No eval rubric, policy, corpus version or baseline changed.

## Final live capture and historical safety replay

Rebuilt only the API with its existing installed Ollama settings preserved.
No worker, projection, telemetry, database-volume or private-document changes.
Intermediate fresh capture `notes/financial-nightly-arithmetic-2026-10-10.json`
passed all 12 cases; retained separately. A final defensive hash/grammar update
was rebuilt before capture, not during a capture. Further red-to-green final
review retained raw model judgments before the commentary guard and refused
premises-only output even when a numerically correct result is model-rejected.
That revision was rebuilt and freshly captured again; all earlier outputs remain.

Final reviewed output: `notes/financial-nightly-arithmetic-reviewed-2026-10-10.json`
(gitignored). All 12 cases captured and passed individually: 10/10 answerable
and both abstention cases. Useful-answer rate 1.0; abstention accuracy 1.0;
must-cite 1.0; reported support ratio 1.0; unsupported drafts 0;
p95 latency 16.458 seconds. Observed answer/support usage: 59,849 input tokens
and 2,575 output tokens. Local compute remains unpriced. Query embedding
invocation accounting remains #94; deterministic embeddings do not demonstrate
real embedding quality. No release-wide quality claim follows from 12 cases.

Rubric fingerprint (unchanged from #71):
`bf4548f3bafb3dc054548538874f4a62643490cf76934eac36cd83a85633fb1f`.
Policy fingerprint:
`5d574de7251e4aa9eca5ed777ffeec2dec1312fdceff9a337b7e780f478ac5b1`.

Final arithmetic run: `f8cec9af-bf7f-4c23-afe0-f714f437fd12`.
Authorized API run/provenance readers confirm three supported claims, the
127.4 result and exact document/version/chunk citation. Both operands' value,
header and entity quotes match their persisted context offsets. The source
chunk hash matches the entire context text. All fresh-suite foreign-workspace
run/event/provenance probes returned 404.

Historical bad run `bea9d2ab-c533-4a07-b879-29134ea98e31` remains unchanged.
A read-only replay inside the deployed API container used its persisted original
model judgments and source evidence, without new model calls or database writes.
The final guard rejected the 127,400 result, retained the two supported premises
for audit and abstained with no final citations. This is a historical guard replay,
not a new live inference quality case or a rewritten successful recording.

The agent-browser skill guided isolated saved-answer inspection (GET/replay, no
new question submission). Desktop 1280x900 and mobile 390x844 screenshots were
visually inspected: wrapped answer and source remain readable, diagnostics
collapsed, no browser errors observed. Evidence is gitignored under
`notes/arithmetic-reviewed-answer-{desktop,mobile}-20261010.png`. The owned browser session
was closed; the frontend development server remains at http://127.0.0.1:5173.

## Gates and remaining work

- Full `uv run pytest -q`: 832 passed, 13 conditional skips.
- Arithmetic focused suite: 43 passed.
- PostgreSQL-enabled answering/orchestration/query API suite: 122 passed,
  3 conditional skips; final answering rerun 33 passed, then final arithmetic
  SQLite/PostgreSQL rerun 4 passed (29 deselected). Reviewed answering rerun:
  33 passed.
- `uv run ruff check .`, `uv run mypy` (155 source files), `uv lock --check`: passed.
- Existing deterministic Acme eval gate: passed; baselines unchanged.
- `uv run alembic upgrade head --sql` with test settings: passed, 1,026 lines.
- `docker compose config --quiet`, `git diff --check`: passed.
- Fresh 12-case live API/provenance/isolation capture, deployed historical guard
  replay and isolated desktop/mobile saved-answer inspection: passed as detailed.
- Frontend tests/typecheck/build skipped: frontend code unchanged; live rendering
  and HTTP availability verified. Hosted provider live calls and real-embedding
  qualification skipped; no paid providers or new models enabled.

Broader arithmetic/structured tables remain #89. OWASP/runtime adversarial policy
remains #80/#81. External human rubric review, remote nightly activation and
accepted live performance baselines remain #53. This milestone remains in progress.
