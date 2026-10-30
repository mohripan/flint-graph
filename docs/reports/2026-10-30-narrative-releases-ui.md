# Narrative Releases UI and end-to-end release qualification

M31 #124 final slice, continuing the [build recovery report](2026-10-30-narrative-build-recovery.md).
The Studio now has a server-backed Releases dialog. A real browser
author → save → background build → reload → download → play proof passed against
the owned local stack. That live proof found that **every browser build published
before this change was unbootable**. The cause is fixed below, and new releases
were qualified across three play surfaces.

## Delivered Releases UI

A **Releases** action beside Playtest opens a native modal dialog in the existing
Studio style. Its contract:

- **Builds come only from saved revisions.** An explicit picker lists saved
  revisions, including the current head and conflict copies. A dirty draft must be
  saved first; the dialog offers that save. Creation keys are kept in studio
  memory per revision, so an ambiguous failure, or closing and reopening, resends
  the same key. A replayed key is reported as "already recorded". A revision whose
  known release is queued or running cannot be rebuilt.
- **Status is server state, so closing or reloading never loses a build.** Lists
  load 25 at a time. A refresh re-reads every loaded row, up to the API cap of 100,
  so older pages stay current. Only the first and older pages decide whether more
  history exists.
- **Only the selected release's item GET is authoritative.** It is polled while
  active, never overlapping, and pauses while the tab is hidden. The list is
  polled only for rows its last refresh returned. Historical or delayed responses
  cannot regress status or attempt number. List, create and retry summaries never
  supply download metadata.
- **Members can cancel and retry; viewers get history and downloads only.** The
  server stays authoritative for both. The attempt selector shows a safe event
  timeline.
- **Downloads are Godot source, Browser build and Release details (JSON).** Each
  one is an authenticated, same-origin, no-store fetch with a byte cap and a single
  allocation. Size, EOF, type and SHA-256 are checked in the browser before a Blob
  exists. Selection and mount scope are re-checked after verification. Blob URLs
  and timers are revoked on close, selection change and unmount. No presigned or
  object-store URL is ever exposed.
- **Late work cannot outlive its scope.** The dialog and its history share one
  request scope. On 401/403, on studio access loss and on project or collection
  changes, the studio invalidates that scope synchronously, before unmount, so
  late item, action, history and Blob callbacks cannot act. Access loss reuses the
  studio's existing cleanup.
- **Keyboard focus stays put.** Activated controls use `aria-disabled` plus
  guards, so focus doesn't drop when a button becomes unavailable. Refresh
  controls never disable. Status lives in an always-present live region. After a
  retry, focus moves to the status message. Phone widths get a single column with
  one dialog scroll area.
- **No source, story or token text goes into localStorage or URLs.**

One reviewer checked the UI. Its three medium findings were fixed: cross-scope
access-loss timing, older-page polling, and `disabled` toggling that dropped
focus. So were its lower-priority items: re-selection cancelling work, a build
response stealing the selection, replay wording, unstable `run` identity,
"load older" reappearing, stale history errors, the live region, initial-load
retry and polling while hidden.

## Defect found by the live proof: empty `project.binary`

The first UI-requested release completed with three hash-verified artifacts, but
its browser build showed a black canvas: `Couldn't load project data`.

- **What was wrong:** its `index.pck` held a **0-byte** `project.binary`. A local
  export of the *same downloaded source* produced a valid 528-byte `ECFG` entry.
- **Reproduction:** running the pinned image with production isolation flags
  printed `ERROR: Couldn't save project.binary at '/tmp/tmpproject.binary'`.
- **Root cause:** Godot's Linux export stages project settings under the fixed
  `/tmp`, ignoring `TMPDIR`. The container root is read-only. Godot still exits 0,
  and the child only rejected script/parse errors.

The fix keeps the pinned image and toolchain unchanged:

- The child now gets a second bounded tmpfs, `/tmp:rw,size=16777216,mode=1777`.
  The host's effective-configuration check requires exactly
  `{/scratch, /tmp}`.
- A host guard, `web_pack_has_project_settings`, parses the bounded Godot 4.7
  pack directory (format 4, unencrypted). It requires a non-empty `project.binary`
  starting with `ECFG` before any artifact ZIP is produced. Otherwise the build
  fails closed with `artifact_invalid`.

Releases published before this change, including the earlier recovery and
publication qualification fixtures, have unbootable browser builds. Their source
ZIPs are fine; the Harbor Bell source was byte-identical before and after the fix.
Published identity is immutable, so build a **new release** of the same saved
revision. The broken first Harbor Bell release is retained as evidence.

## Live qualification (owned local stack)

Only owned PostgreSQL, MinIO and Temporal fixtures, the prepared Godot 4.7.2 image
and the owned API, worker and relay were used. No model, provider key or user
corpus was involved. The ordinary local API now admits releases with the existing
builder pins. The worker was restarted with the same queue and root to load the
fix.

1. **Author and save.** Created *Harbor bell release QA* in the Studio. Entered an
   original text-only story (two variables, a state-gated option, a branch and
   three endings) through the Source panel. Saved revision 2. Edited the opening
   in the Write form and saved revision 3.
2. **Build and reload.** Opened Releases and built revision 3; the duplicate build
   was blocked while active. A full page reload mid-build showed the same server
   state, and polling advanced Queued → Ready without a reload.
3. **Download.** The in-browser verified download produced its "verified" notice
   after the SHA-256 check. Completion in the desktop pane is controlled by the
   app and is not claimed. Authorized HTTP downloads matched sizes, hashes and the
   attachment, `private, no-store` and `nosniff` headers. The packaged
   `story.json` equals saved revision 3.
4. **Native import.** The pinned engine imported the downloaded source and printed
   the exact `CONTENT_OK:3ecc21b7…` package hash. The fixed release PCK verified
   standalone with `--main-pack`. A copy of the downloaded source re-exported to
   Web; the downloaded bytes stayed unchanged.
5. **Route parity.** Four routes, including the gated one, matched the reference
   player step by step, comparing text, offered options and ended status. They
   were played on three surfaces:
   - the release web build (QA snapshots, keyboard and mouse);
   - the web export rebuilt from the downloaded source;
   - the Studio's isolated saved-revision preview (keyboard-only, with Escape and
     focus return).
6. **Viewer and access loss.** A separate owned API process used a distinct dev
   subject, granted through the owner's members endpoint.
   - As a viewer, the dialog was read-only, with history and downloads only. HTTP
     build, retry and cancel returned 403, and the manifest download returned 200
     with the matching hash.
   - Downgrading member → viewer while the dialog was open made a stale Build
     return 403. The dialog closed, the studio cleared to the project list with the
     access-changed message, and the stored selection was removed. No request
     followed the 403 and no release was created.
7. **Phone width.** At 390×844 the dialog is a single column with no horizontal
   overflow, one scroll area, and no button smaller than 44 px.

Evidence:

- [release proof](evidence/narrative-releases-ui-2026-10-30/release-proof.json)
- [route parity](evidence/narrative-releases-ui-2026-10-30/route-parity.json)
- [access, viewer and mobile](evidence/narrative-releases-ui-2026-10-30/access-proof.json)

Downloads, logs, traces and helper scripts stay in ignored `notes/`.

## Verification

Passed:

- **Frontend:** `npm test` (41 passed, including new release model, intents,
  replay and `no-store` API tests), `npm run typecheck` and `npm run build`.
- **Builder unit tests:**
  `uv run pytest tests/unit/test_narrative_build_runner.py tests/unit/test_narrative_release_artifacts.py`
  gave 67 passed. New tests cover the full fake build's requested `{/scratch, /tmp}`
  tmpfs map, empty-settings rejection and bounded pack parsing (truncation,
  offsets, version, encryption, oversized directory).
- **Real image:** with the explicit image and toolchain pins,
  `tests/integration/test_narrative_build_runner_live.py`,
  `test_narrative_build_child_live.py` and `test_narrative_build_watchdog_live.py`
  gave 5 passed and 1 explicit skip (the 180-second watchdog opt-in). The child
  test now asserts that the real Godot pack carries project settings.
- **Full suite:** `uv run pytest -q --tb=short` gave 1397 passed and 71 explicit
  skips in 237.74 s.
- **Other gates:** `uv run ruff check .`, `uv run mypy` (195 source files),
  `uv lock --check`, the deterministic acme-smoke eval, offline
  `alembic upgrade head --sql` with `FLINT_GRAPH_ENV=test`,
  `docker compose config --quiet` and `git diff --check`.
- **Live:** the owned-stack browser/HTTP/native qualification above.

## Limitations and follow-ups

- **Empty NOTICES.txt logs an engine error.** The runtime bootstrap hashes the
  notices with `HashingContext.update` even at zero length, so Godot logs
  `Condition "len == 0"`. Content verification still passes. The pinned runtime
  is unchanged here; this is a follow-up.
- **Dev auth auto-enrolls unknown subjects.** In dev mode, an unknown subject is
  enrolled as owner on its first workspace access, so viewer checks must
  explicitly downgrade it. Staging and production reject dev auth.
- **No membership-removal endpoint exists.** The QA viewer identity remains a
  viewer in the owned fixture workspace.
- **Screenshot lag in the desktop pane.** Built-in browser screenshots can lag the
  canvas. State was checked with DOM and QA snapshots wherever available.
