# Financial scope clarification delivery

Tracking: [issue #60](https://github.com/mohripan/flint-graph/issues/60).

The saved public nightly failure selected figures from unrelated reports for
“What was revenue?”. Citation support did not resolve missing company/period
intent. The new narrow English past-tense financial-value rule checks distinct
authorized active/completed documents in the selected index and requests missing
scope before answer/support generation. It persists a versioned policy event and
an abstained final clarification. Explicit valid source selection and a supplied
year are respected. See ADR 0021 for limits, including single-document ambiguity
and the absence of conversation memory.

Tests were added first: missing-policy import, then two provider-call regressions
failed before the generator bypass was implemented. A browser regression failed
before the UI clarification label was added and passed after it. A separate
faithfulness test verifies rejected drafts are not rendered but remain audited.

## Live evidence

Public workspace `2eab2f78-208e-4eb9-97a2-087e40af0525`, unchanged 100-report-excerpt
corpus and index `fc8aa4e9-6b7f-4283-99cf-efc850a472e1`:

- Run `9dff1817-24c3-441e-a445-cf63cdf19220`: bare revenue query clarified in
  1.605 seconds.
- Run `21b9fdac-9899-41c4-9221-48133bec910a`: year-only revenue query clarified in
  1.337 seconds, asking for company/document rather than asking again for a year.
- Both completed with `ambiguous_financial_scope`, `scope-policy`, zero claims,
  citations and provider tokens, no provisional generated text, and persisted
  clarification events. Foreign workspace reads of run/events/provenance returned
  404. No private source or corpus mutation was involved.
- Real browser reopened the saved year-only clarification via GET, displaying the
  clarification on desktop/mobile. Screenshots were visually inspected; scoped
  browser session closed. Vite remains running on port 5173.

## Gates

- `uv run pytest -q`: 752 passed, 12 conditional skips.
- PostgreSQL-enabled query answering/planning/API suite: 95 passed, 3 conditional skips.
- Focused scope/answering/faithfulness suite: 43 passed.
- Ruff, mypy (153 files), lock consistency, exact deterministic evaluation gate,
  Alembic SQL (1,026 lines), Compose and diff checks passed.
- Frontend: 8 tests, typecheck, production build, and responsive/history browser
  checks including saved clarification passed.
- API rebuilt with inspected Ollama settings preserved. Only the API was recreated;
  no models, indexes, raw objects, volumes or telemetry services were removed.
- Fresh unchanged 12-question nightly gate: **failed**, with all 12 captured.
  Ambiguous revenue and unavailable future data both passed; abstention accuracy
  and recall were 1.0. Useful-answer rate was 0.7, supported-claim ratio 0.9545,
  one rejected unsupported draft claim, must-cite satisfaction 0.9 and recall@5
  0.95. p95 latency was 16.555 seconds, usage 60,616 input / 2,696 output tokens,
  and foreign-tenant probes passed. Cross-report synthesis, Philip Morris RRP
  2017, and American Express average failed this fresh run. The gate remains
  red; source/rubric thresholds were not modified. Local report:
  `notes/financial-nightly-scope-2026-10-10.json` (redacted).

No baselines, rubric literals, source labels or thresholds were changed. Rejected
generated claims still count in the strict gate. This fix is not evidence of a
fully production-qualified model, embedding system or chained chat implementation.
