# Real narrative Web export qualification

Date: 2026-10-27. M30 / #121. Player source commit `306f04c`, runtime **0.2.0**,
Godot **4.7.2.stable.official.ed1daf0bf**, matching official single-threaded
templates, Compatibility/WebGL2, agent-browser **0.39.0**, Chrome **155.0.8059.39**,
Windows x86-64. This is an authored sample game, not the M31 editor or an AI-quality
demonstration. The story and simple procedural placeholder art are original CC0.

## Observed behavior

`tools/narrative/qualify_web.py` executed the verified real engine, imported source,
checked actual content markers and produced HTML/JS/WASM/PCK for both fixtures.
The source manifest matches the wheel-installed export. No model/account/backend
or external content was required. Public compiled files alone were served over
loopback HTTP. [Artifact hashes](evidence/narrative-2026-10-27/build-hashes.json)
record the actual built files rather than a command-exit-only assertion.

The reusable `tools/narrative/verify_browser.mjs` passed **16 real input steps**:
all three desktop endings; keyboard advance/choice; visible text/art; Save at a
choice; a real page reload and Load back to that choice; mobile main route;
mobile controls within the viewport and at least 44px high; and 70-paragraph
scrolling on both widths, ending with real mouse clicks on Continue. Viewports
were **1280Ã—900** and **390Ã—844**, device scale factor 1.

Browser exception output was empty. Console inspection found no error-level
messages, script errors or content errors and confirmed the actual pinned engine.
The browser exposed WebGL2 and the single-threaded Emscripten build. A separate
manual default-URL check confirmed the QA object was absent before and after
Enter, and visually showed the resulting choice screen.

Retained public evidence: [step summary](evidence/narrative-2026-10-27/browser-summary.json),
[desktop arrival](evidence/narrative-2026-10-27/01-desktop-arrival.png),
[mobile choices](evidence/narrative-2026-10-27/09-mobile-choice.png),
[mobile long passage bottom](evidence/narrative-2026-10-27/12-mobile-long-bottom.png),
[desktop long passage bottom](evidence/narrative-2026-10-27/15-desktop-long-bottom.png),
and [normal mode after input](evidence/narrative-2026-10-27/17-default-no-qa-choice.png).
These screens were visually inspected for readable wrapping, full controls,
visible focus and an actual usable scroll region. Full local screenshots/JSON/
console are in ignored `notes/narrative-browser-reviewed-20261027`; earlier final
screens and normal-mode proof are in `notes/narrative-browser-final-20261027`.

## Browser-discovered failure and correction

The first real web build had a blank canvas despite successful native state/
content checks. Two browser captures reproduced it. Native script probes had
never instantiated the visible UI. Safe diagnostic logs isolated startup stopping
at optional web-only QA setup before UI creation; no JavaScript exception surfaced.
UI creation/render now precedes optional inspection, and data-only browser
interfaces replace eval-based setup. Actual visible startup and input then passed.
No upstream engine defect is asserted. The native UI regression harness also now
constructs the real GameView, but browser execution remains a separate gate.

An expired browser daemon also caused the first synchronous CLI `set viewport`
startup to retain pipes until its timeout. Doctor reported 5 passes and zero
failures; the owned browser was healthy. Opening/warming the session separately
resolved the tooling timeout. It was not recorded as a passing app check.

## Commands, results and scope

- `uv run python tools/narrative/qualify_web.py --engine notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe --templates notes/toolchains/godot-4.7.2/templates --output notes/narrative-web-qualification-20261027`: passed, two real builds and retained logs/hashes.
- `node tools/narrative/verify_browser.mjs` with the explicit owned session, compiled sample/long URLs and new evidence directory: passed, 16 steps. The console-checking final run is `notes/narrative-browser-reviewed-20261027`.
- `node --check tools/narrative/verify_browser.mjs`, `uv run ruff check .`, `uv run mypy`: passed.
- The documented JSON-file `--actions` CLI route also ran to `restored`; reusing an existing qualification output was explicitly refused without overwrite.
- Runtime/native regression and required backend gates: [#120 report](2026-10-27-godot-player.md), 15 real engine tests; 1209 offline tests passed. #121 adds qualification tooling/docs without changing that runtime.
- Player commit [CI](https://github.com/mohripan/flint-graph/actions/runs/40493580682) and [real container smoke](https://github.com/mohripan/flint-graph/actions/runs/40493580674): passed. CI also built/typechecked/tested the unchanged React frontend.

Video was skipped because ffmpeg is absent; dated screenshots and actual input
reports are retained. Physical mobile, Safari, other native platforms, screen-reader
accessibility, production hosting, hosted compiler isolation, AI writing/image
quality and cloud saves were not qualified. New backend/full regression runs were
not repeated for these tooling/docs-only changes; the fresh commit's ordinary CI
remains required. No existing workspace, data service, model configuration or
unrelated #109 WIP was changed.

Follow the [author/export/browser guide](../runbooks/narrative-web-play.md) to
repeat the proof. M31 adds project/revision APIs and the actual authoring editor.
