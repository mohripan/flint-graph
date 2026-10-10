# Chat keyboard qualification — 2026-10-11

Scope: [#101](https://github.com/mohripan/flint-graph/issues/101), a bounded
follow-up to the first thread UI (#99), under [ADR 0028](../adr/0028-capability-gated-conversation-thread-ui.md).
No backend, provider, permission, memory or schema change.

## Observed gaps and changes

The live public-thread axe-core 4.12.1 audit initially reported zero automated
violations and one **serious incomplete** `aria-prohibited-attr` check at both
1280px and 390px. The keyboard-focusable transcript div had a label but no
naming-capable role. Those are distinct audit categories; the incomplete result
was not treated as a pass or mislabeled a violation.

The transcript is now a named, focusable region, not a live history log. Explicit
history selection focuses the loaded heading after mobile history closes.
New chat focuses the composer without creating server work. Passive saved-thread
restoration does not steal focus. Rename Save/Cancel returns focus to Rename.
Keyboard citation activation focuses that turn's evidence; the next Tab reaches
its full-excerpt disclosure. Existing reduced-motion citation scrolling remains
in place. Focus changes use `preventScroll` so unrelated content is not moved.
The shared citation panel's legacy standalone behavior is preserved.

Each behavior had a failing DOM/keyboard regression before implementation. The
new `npm run test:chat-a11y` uses a pinned isolated agent-browser session and
external HTTP fixtures, not React internals. It verifies keyboard activation,
desktop/mobile selection, quiet restoration, no selection/New-chat writes or
streams, title-only rename and repeated c1 labels remaining turn-scoped.

## Live verification

The actual frontend/backend reopened public FinQA conversation
`a1a002b0-6489-4687-99de-0f9ab345d70e` in workspace
`2eab2f78-208e-4eb9-97a2-087e40af0525`. Explicit selection focused its heading.
Keyboard activation of the second answer's citation focused its own authorized
evidence; Tab/Enter opened the full excerpt. New chat then focused the composer
and cleared the visible turns. No write or SSE execution request was issued.
This inspected existing real-model answers; it did not run another model-quality
capture or attest new inference performance.

Fresh axe audits, including expanded actual evidence, reported zero violations
and zero incomplete checks at both widths for the selected WCAG 2 A/AA tags.
Desktop/mobile screenshots were inspected: full evidence stays in the primary
transcript scroller and the composer remains visible without horizontal document
overflow. Original incomplete audit artifacts are preserved separately from the
post-fix results under gitignored `notes/`. The frontend remains on localhost:5173;
the deployed API is the separately verified #100 build. Private corpus, workers,
volumes, configured models and optional telemetry services were left unchanged.

## Commands and qualifications

Passed:

- Frontend `npm test`: 10 tests; `npm run typecheck`; `npm run build`.
- `npm run test:chat-a11y`; complete `npm run test:conversations`;
  `npm run test:browser`; focused `--discovery-only` development rerun.
- Actual public-thread keyboard/reopen/source checks and desktop/mobile axe audits.
- `uv run pytest -q tests/integration/test_conversations_api.py --tb=short`:
  28 passed, two SQLite-only concurrency skips.
- `uv run ruff check .`; `uv run mypy`: clean, 160 source files.
- `uv lock --check`; deterministic Acme evaluation gate;
  `docker compose config --quiet`; `git diff --check`.

The first new keyboard fixture had an overly broad route, corrected before the
genuine failing focus assertion. The existing full suite also failed once while
filling Rename before its form appeared; explicit enabled-control/form waits were
added, then the focused and unfiltered suites both passed. Browser diagnostics
were run before retrying unexpected failures; no destructive repairs were used.

Not repeated for this frontend-only slice: the full backend/PostgreSQL suites and
offline migration SQL already passed in #100 earlier in this session. No fresh
inference, private-corpus query, external OIDC-browser deployment, paid service,
remote nightly activation or load benchmark was run. No manual assistive-technology
certification, all-state accessibility audit, new status live-announcement policy,
retention/deletion or complete #73 acceptance is claimed. CI outcome is recorded
in the issue after push. Broader #73/#74/#75/#62 work stays open.
