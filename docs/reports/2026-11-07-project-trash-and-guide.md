# Project trash, rename, a first-time guide and Studio polish

Feedback after using the updated Studio, delivered together. See
[ADR 0073](../adr/0073-project-trash-and-permanent-delete.md) for the trash.

## What changed

- **Trash.** Project cards have Move to trash. The Trash lists those projects with Restore and Delete forever. The
  warning counts what will be lost and refuses while the project is still working.
- **Rename** on project cards. The name is the Studio's own; the title players see stays under Details.
- **First-time guide.** Five steps above the project list until dismissed, and a Guide page in the sidebar afterwards.
  Dismissal is per browser, in `localStorage`, so a new device shows it once more.
- **Generation card** in the Studio's own style: paper, gold edge, serif title, price at the top, quiet details and
  compact buttons. It used to follow the example closely. Its server quote, price and behaviour are unchanged.
- **All projects** has no box and a larger font.
- **Assets** groups the options from one Generate into a set under a heading such as "Kaito · Sprite, 4 options, Nov 7",
  instead of scattering repeats of "kaito sprite 1" through the grid. Uploads keep their place between the sets.
- **Your own credits.** See [ADR 0074](../adr/0074-a-balance-on-your-own-server.md). A balance at the top of the page and
  a Usage page in every mode.

## Real proof

Real browser and real PostgreSQL and MinIO, on an isolated stack in invite mode with a real key:

| Project | Rows before | After | Files before | After | Bucket |
| --- | --- | --- | --- | --- | --- |
| The Third Ferry: 3 revisions, 8 real generated sprites, a real conversation | 93 | 0 | 16 | 0 | 43 to 27 |
| A Name of Your Own: a real 0.12.0 release with its artifacts | 36 | 0 | 3 | 0 | 27 to 24 |

Each bucket drop is exactly that project's files, and the other projects stayed. In the browser: the guide showed,
stayed dismissed after a reload and reopened from the sidebar; rename, trash, restore, Keep it and Delete forever
all worked, and the warning read "3 saved revisions, 8 pictures, voices and music files, 2 characters, 1 conversation".
Browser console problems: none. The second row went through the API rather than the browser.

The stack ran only the API and frontend, because an earlier full stack was stopped when the machine ran low on memory.
So jobs were not running during this run; the refusal while working is covered by tests.

## Tests

`tests/integration/test_narrative_project_trash.py` runs on SQLite and on PostgreSQL with the real migrations and
triggers, and covers restore, refusal outside the trash and while working, a failure midway followed by a retry,
roles, other workspaces, full projects, and the logs still refusing changes.
`tests/unit/test_narrative_project_purge.py` holds the code to the schema and tests storage paging, failures and
that only real IDs can become a prefix. `frontend/tests/narrative-trash.test.mjs` covers the warning and the guide.

An early version failed in two ways the tests caught: a guard based on a PostgreSQL session setting could not work
in the ordinary SQLite run, so it became the durable `purge_started_at` rule, and SQLite's row-by-row key checks led to
clearing self-references and deleting revisions newest first.

## Verification

The balance was checked in a real browser in open mode: the pill showed 500, a card said "10 credits · you have 500",
pressing Generate took it to 490, and Usage opened from the pill. Assets showed "Background, 4 options · Nov 7" as a set.

```powershell
uv run pytest                     # 2484 passed, 149 skipped, 1 failed (below)
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run flint-graph-prompts check --base-ref origin/master
docker compose config -q
cd frontend; npm test             # 216 passed
cd frontend; npm run build
```

The one failure, `test_query_stream_cancellation_marks_run_cancelled`, ran while other checks were using the machine. It
cancels a task partway through, passed 5 of 5 alone and passed in its whole file (39 passed, 2 skipped), and no query
code changed here. An earlier full run of the trash work had no failures (2477 passed, 149 skipped).

`alembic upgrade head --sql` and the downgrade to 0054 pass with `FLINT_GRAPH_ENV=test`. The access and trash tests also
passed on real PostgreSQL with the real migrations (26 passed). Not run: the real-engine suites, because nothing in the
player or format changed.

## Not done

- A project with a job stuck in the queue cannot be deleted until that job ends (see the ADR).
- Restoring or deleting a project from anywhere but the Trash, and renaming from inside an open project.
- Phone layout was looked at for the card only.
