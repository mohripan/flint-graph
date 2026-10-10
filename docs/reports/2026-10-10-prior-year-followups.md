# Bounded prior-year follow-up verification

Tracking: [#97](https://github.com/mohripan/flint-graph/issues/97), parent #62.
Design: [ADR 0027](../adr/0027-bounded-prior-year-followups.md).

## Delivered scope

The conversation ledger now supports deterministic prior/previous-year question
interpretation from the immediately preceding finalized grounded turn. Its
question supplies reference scope only: prior answer text never enters factual
evidence or a model transcript. Original questions remain immutable; resolved
questions, bounded correlation/omission counts and execution-policy fingerprints
are inspectable in tenant-owned run metadata. Fresh retrieval, classification,
linking, reranking, arithmetic, generation and support use the resolved question.

Trust requires matching active index, filters and configured model/prompt/bounds
policy, supported claims and exact active PostgreSQL source identity/text/hash
from the latest context pack. Recheck before generation. Failed, cancelled,
unsupported, legacy, changed/deleted sources and ambiguous history fail closed;
no fallback to an older favorable turn. Limits: one question <=1000 characters,
one explicit year, eight supported claims and eight distinct citations.

New-chat/untrusted follow-ups clarify without retrieval or model calls. Explicit
zero expected calls now attest complete accounting; attempted unknown usage still
remains incomplete. Source changes during retrieval may incur embedding usage
before the generation recheck suppresses answer/support calls. Capabilities are
`prior_year_followups=true`, `chained_conversations=false`.

Initial pure-policy and no-context API regressions failed before implementation.
Changed-filter and latest-pack regressions subsequently exposed two gaps; both
were fixed and checked on real PostgreSQL. External provider fakes exercise fresh
retrieval/generation/support questions, unknown-token accounting and replay.
An external source replacement during retrieval verifies the generation recheck.
Other service/policy cases check no older-turn fallback, cancelled/failed turns,
new-chat isolation, inactive/changed indexes, changed settings, source text/hash,
deleted versions, unsupported claims, bounded/ambiguous years and successive years.

## Live public-corpus checks

Rebuilt only the API, preserving existing provider settings, source data and
worker services. Final image config:
`sha256:e092a1e8ec90410618b5a78ee5a8d0cead3667a5c905b17f34ddf1ece5cea335`.
The existing installed Gemma answer/support model and explicit 8192-token Ollama
window were retained; deterministic 384-dimensional embeddings remain a local
limitation, not qualified production semantic retrieval.

Final fresh conversation: `c2a7aac9-ab96-404f-977f-baf857214be6`.

| Run | Result | Input / output tokens | Local elapsed |
| --- | --- | --- | --- |
| `4fe115d0-0117-4954-bb35-32ed2a8a6af3` | Philip Morris 2017 RRP net revenues excluding excise taxes: $3.6 billion, cited | 5958 / 243 | 9.75 s |
| `1709bb06-abe1-4bb1-8f83-baf7d60517ec` | Original `What about the prior year?`; resolved 2016 question; $733 million, cited | 5508 / 138 | 8.13 s |
| `474d9525-4d28-40db-9ff8-6f7e46a4a95c` | Separate new chat: citation-free clarification | 0 / 0, no invocations | 1.16 s |

Both factual runs have three known invocations, complete usage accounting, zero
unsupported claims and active cited sources. The new-chat run has an explicitly
complete empty ledger. Replay did not add invocations; foreign-workspace run GET
returned 404. The pinned public workspace retained the same 100 completed
document-version coverage rows and active index before/after. No private document
query, restoration, re-upload or mutation occurred. Measurements are local smoke
timings, not throughput or production latency claims; provider cost is unpriced.

Local final recording: `notes/prior-year-followups-live-final-2026-10-10.json`.
An earlier live pair also produced the same cited answers; its observer then used
the wrong provenance response field. The original failed verification report and
runs were retained, and a continuation finished its remaining checks without
re-dispatching those model calls. A separate fresh final run above verifies the
last latest-pack fix in the deployed image.

A fresh 12-question standalone financial nightly capture passed all 12 cases,
useful-answer/citation/abstention checks, tenant isolation and complete accounting:
60,314 input / 2,750 output tokens, p50 9.12 s and p95 13.43 s. Recording:
`notes/financial-nightly-prior-year-runtime-2026-10-10.json` (format 3).
This capture preceded the final conversation-only latest-pack guard; standalone
behavior does not use that guard. Rubric, quality policy, corpus, role-model
fingerprints and baselines were unchanged. No paid service, model download,
external exposure or hardware qualification was introduced.

## Exact checks

- `uv run pytest -q --tb=short`: 911 passed, 15 skipped on the final source.
- PG-enabled memory/conversation/query API/accounting suite: 150 passed, 5 skipped;
  final latest-pack and conversation API focus: 8 passed, 108 deselected (SQLite
  and PostgreSQL). The usual SQLite concurrency and opt-in live tests stay skipped.
- Final memory service focus: 17 passed; fingerprint unit check also passed.
- `uv run ruff check .`: passed.
- `uv run mypy`: passed, 160 source files.
- `uv lock --check`: passed.
- Offline Acme evaluation command from AGENTS.md: passed; baseline unchanged.
- `FLINT_GRAPH_ENV=test; uv run alembic upgrade head --sql`: passed, 1061 lines;
  no schema change in this slice.
- `docker compose config --quiet`, API-only rebuild and `git diff --check`: passed.
- Fresh final multi-turn public API smoke, replay/isolation and 12-case live
  financial capture: passed as described above.
- Frontend HTTP `http://localhost:5173`: 200 and left running. Local frontend
  build/browser suites skipped because this slice changes no frontend files;
  the thread UI remains separate work.

#62, #73, #74, #75 and #82 remain open: no general pronoun memory, summaries,
long-history budgets, retention/cache lifecycle qualification, complete thread UI
or durable background query execution claim follows from this bounded slice.
