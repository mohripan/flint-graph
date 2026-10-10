# Source-consistent RRP plural rubric review

Tracking: [#71](https://github.com/mohripan/flint-graph/issues/71).

Reviewed the pinned FinQA commit `0f16e2867befa6840783e58be38c9efb9229d742`,
PM/2017/page_38 excerpt with immutable source label
`finqa-f4d992784b64c3c93b3725ab4dad90cd75c51cda2b7aa0855f30fd1b44e72115`.
The source itself uses the plural acronym for both tax-exclusive revenue values.
Only the 2017/2016 RRP concept groups gain `rrps`. Numerical equivalents, unit
groups, questions, corpus, dataset version, policy thresholds and accepted
baselines are unchanged. This agent source review is not external human approval;
that requirement for scheduled activation remains open under #53.

Tests first reproduced both plural false negatives and missing report revision
identity (4 failing tests). They now accept the two explicit aliases and existing
singular/hyphenated equivalents, while rejecting wrong tax-inclusive values,
wrong year values, wrong scales/units, unrelated acronym substrings, and the
incorrect American Express average. No generalized plural stemming was added.

New format-2 reports include corpus dataset name/version and canonical JSON
SHA-256 rubric/policy fingerprints. Changing an alias changes the rubric
fingerprint, not corpus identity; changing policy changes its fingerprint.
Mapping-key order does not change the hash. Old reports remain untouched and
cannot be retrospectively treated as fingerprint-attested.

## Separate live verification

Fresh output: `notes/financial-nightly-rubric-plural-2026-10-10.json` (gitignored),
not a rescore or overwrite of a failed recording. Existing API, installed Ollama
model digest and exact 100-document public financial workspace were unchanged.
The client revision changed; no API rebuild was needed. All 12 queries completed;
9/10 answerable cases and both abstention cases passed (11/12 individually).
Gate passed at useful-answer rate 0.9, abstention accuracy 1.0, must-cite 1.0,
reported supported-claim ratio 1.0 and p95 latency 16.455 seconds.
Observed answer/support tokens: 59,744 input and 2,682 output. Local compute
remains unpriced; query embedding usage completeness is separately tracked #94.

RRP 2017 run: `3ab354ec-b019-4476-bcd5-111604df11dc`.
RRP 2016 run: `4a85ddc7-a515-481e-9e58-d44e1b49b453`.
Persisted provenance was read through the authorized public API. Foreign-workspace
run, event and provenance probes returned 404 throughout the fresh suite.
The arithmetic case still fails at run `bea9d2ab-c533-4a07-b879-29134ea98e31`;
LLM support approval does not establish arithmetic correctness (#70).

Rubric fingerprint:
`bf4548f3bafb3dc054548538874f4a62643490cf76934eac36cd83a85633fb1f`.
Policy fingerprint:
`5d574de7251e4aa9eca5ed777ffeec2dec1312fdceff9a337b7e780f478ac5b1`.
The improved score comes from corrected scoring equivalence, not better model
answers; the unchanged model also reproduced the remaining arithmetic error.

## Verification

- `uv run pytest -q`: 787 passed, 13 conditional skips.
- Nightly eval/CLI/workflow focused suite: 36 passed.
- `uv run ruff check .`, `uv run mypy`, `uv lock --check`: passed.
- Existing deterministic Acme evaluation gate: passed; baselines unchanged.
- `uv run alembic upgrade head --sql` with test settings: passed, 1,026 lines.
- `docker compose config --quiet` and `git diff --check`: passed.
- Live 12-case public API capture/provenance/isolation verification: passed gate,
  with the arithmetic case explicitly failing as described above.
- Frontend HTTP availability: 200; development server left running at port 5173.
- PostgreSQL-specific integration rerun, frontend tests/build and browser UI QA:
  skipped for this client-only rubric/report change; no runtime DB/UI behavior changed.

Scheduled remote activation, external human review and accepted live performance
baselines remain pending. No private documents were queried, restored or uploaded.
