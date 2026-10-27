# Milestone 30: portable story runtime and Godot proof

Date: 2026-10-27. Status: proposed implementation contract; awaiting written-spec
review. The authored-game/Godot product direction is approved. No narrative runtime
is implemented by this document.

## Scope and success

Deliver one bounded foundation: validate a local story package, execute its state
machine, and export a trusted editable Godot project that plays the same routes.
Use original text and simple original/CC0 placeholder assets. No API/database
migrations, studio UI, LLM calls, source adaptation, image generation, arbitrary
code generation or automatic hosting belongs in this milestone.

The product vision and later work are in
[the narrative studio brief](../../product/narrative-game-studio.md).
This slice is complete only after real Godot execution and a served browser build
match the reference runtime; producing plausible project files is insufficient.

## Component boundaries

| Proposed location | Responsibility |
| --- | --- |
| `src/flint_graph/narrative/` | Provider/DB-independent package models, validation, transition semantics, save contract |
| `src/flint_graph/narrative/export/` | Deterministic manifest/build preparation and safe Godot source packaging |
| `src/flint_graph/cli/narrative.py` | Explicit local validate/play/export operations, version/help and safe diagnostics |
| `runtimes/godot/` | Reviewed GDScript interpreter, UI, save/load and fixed project template |
| `tests/fixtures/narrative/` | Original mystery, expected route traces, invalid packages, asset notices |
| `tests/unit/` and `tests/integration/` | Semantics/validation tests and opt-in native engine/browser conformance |

These are planned new modules, not claims about existing files. Do not import
SQLAlchemy, model providers, Temporal or retrieval services into the pure runtime.
Do not widen the current conversation APIs to accept game execution requests.

## Package version 1

The source package is a directory with `story.json`, `assets/` and `NOTICES.txt`.
The JSON object contains schema version `1`, a stable story ID, title, language,
entry node ID, characters, variable declarations, nodes and an asset manifest.
Line and choice records have stable text IDs distinct from editable display text,
to preserve a path to later localization. V1 ships one language per package.

Stable IDs use `[a-z][a-z0-9_-]{0,63}`. Unknown fields, duplicate JSON keys,
non-finite numbers, invalid UTF-8, NUL and unsupported schema versions are errors.
Array order determines display order; map order never changes execution. Text is
plain Unicode, not HTML, executable markup or template expressions. Escape engine
rich-text syntax or disable rich-text processing in the runtime UI.

Variables are booleans, signed 32-bit integers, or declared finite string enums.
Each has a type and initial value. No floating point, dynamic variables,
JavaScript/GDScript expressions, clocks, network input or random decisions in v1.
Integer overflow is a controlled transition error, not wraparound or coercion.
Relationship scores and inventory flags can be expressed with these variables.

Five node types define the initial language:

| Type | Behavior |
| --- | --- |
| `line` | Display speaker ID or narration, text ID/text, optional approved background and portrait asset IDs; advance to one target |
| `choice` | Display ordered options with IDs, labels and optional conditions; selected visible option moves to its target |
| `set` | Atomically apply ordered typed literal assignments or integer increments; move to one target |
| `branch` | Evaluate a condition against current state; move to its true or false target |
| `end` | Record a stable ending ID; no successor |

A missing line visual clears that visual slot; this avoids hidden carry-over
state. V1 stages one portrait and one background, with no animation/audio/camera
commands. Choice conditions are evaluated on entering the choice; no visible
options is an explicit `no_available_choices` fault, never a frozen screen.
No effects are hidden in dialogue or option text. Use explicit `set` nodes.

Conditions are typed data trees: equality/inequality on matching declared types,
integer comparisons (`lt`, `le`, `gt`, `ge`), `all`, `any` and `not`. Compare a
declared variable to a typed literal; no implicit conversions. `all`/`any` take
one or more children. Evaluation is pure; conjunction/disjunction use ordered
short-circuiting without side effects. Equality on strings is exact and
case-sensitive, with no implicit Unicode normalization.

Initial defensive limits: 5 MiB `story.json`, 10,000 nodes, 256 variables,
32 options per choice, 16,384 Unicode code points per display text, condition
depth 8 and 64 condition nodes per expression, 256 assets, 10 MiB per PNG and
100 MiB total package bytes. PNG dimensions are at most 4096 per axis and
16,777,216 pixels. Limits apply before costly decoding/materialization, with
lower preview/build memory and process limits enforced separately. These are
supported-format caps, not a performance promise; changing them needs tests.

## Validation, state and deterministic execution

Validate schema/types/limits, unique IDs, declared references, node requirements,
entry/ending presence, asset hashes/paths and typed condition/assignment rules.
Report structured codes, node IDs and field locations without absolute host paths
or secrets. Reject a package with blocking errors before engine generation.

Report structural unreachable nodes and cycles as warnings. Structural graph
reachability ignores conditions and is not proof that an ending can be reached.
Bounded state exploration reports visited states, tested routes, covered endings,
limits and unexplored states. Sampled success must never be labeled exhaustive.

Execution state is package content hash, current settled display/terminal/fault
node ID, typed variables and ending/fault status. Entering a node executes automatic `set` and
`branch` transitions until a line, choice, end or fault. Limit automatic
transitions to 1,000 per player action to stop non-interactive cycles. Apply a
set node on a copy of state; failure leaves the pre-node state intact. A line
advance and visible choice selection are the only player transition actions.
An invalid/stale option ID changes no state. Re-entering a set via a real loop
applies its effects again; redisplaying a paused node does not.

Each conformance trace records input actions, displayed node/text IDs, visible
option IDs, variable snapshots and ending/fault codes. Human text is asserted in
separate rendering checks. Given the same package and actions, the reference
interpreter and Godot runtime must produce identical normalized traces.

## Save and revision semantics

Save JSON has its own schema version `1`, package content hash and the execution
state at a settled line, choice, end or fault. It includes no executable objects,
class names, credentials or file paths. Validate types, bounds, referenced node
and ending consistency on load. An invalid or different-package save fails
without replacing the running session. Restoring a settled state redisplays it
without replaying prior assignments. Package changes invalidate old saves in v1;
there is no silent migration promise. Saves are local player data and are not
trusted achievements or authoritative multiplayer state.

Canonical JSON uses sorted object keys, preserved array order, no insignificant
whitespace or trailing newline, UTF-8 without BOM, unescaped non-ASCII characters,
standard JSON control-character escaping, and decimal integer literals. All
object keys are fixed schema keys or ASCII IDs. No Unicode normalization occurs.
The reference serializer is Python `json.dumps` with `sort_keys=True`,
`ensure_ascii=False`, `separators=(",", ":")`, `allow_nan=False`, encoded as UTF-8.
Shared golden bytes/digests make this testable across tools.

The package hash is SHA-256 of a canonical manifest containing the canonical
`story.json` hash, `NOTICES.txt` byte hash and sorted asset path/hash entries.
Generated timestamps and the package hash itself are outside that manifest.
Godot verifies the stored manifest and consumes exact canonical story bytes,
rather than independently guessing Python serialization. Asset bytes are separately
verified. A build manifest pins package, compiler, runtime, engine and template
versions. Repeated builds have equal content/manifest hashes; byte-identical
archives or native binaries are not promised.

## Godot export and live proof

Use a reviewed Godot 4 stable release, GDScript, Compatibility renderer and a
single-threaded browser export. The engine-toolchain issue must record exact
official release version, platform artifact SHA-256, matching template SHA-256,
license notices and actual local/CI commands before the exporter is qualified.
Do not use an unpinned `latest` engine or download at ordinary test/import time.
This design does not authorize installing an arbitrary engine package globally.

Generate a fresh output directory containing `project.godot`, trusted runtime
scripts/scenes, canonical content, allowed assets, notices and build manifest.
Refuse an existing nonempty target; never recursively replace an arbitrary path.
Import with the pinned engine in an owned temporary workspace, export a browser
build using matching templates, serve it over HTTP, then play real routes. Check
generated artifacts and observed behavior as well as process exit codes. Unknown
Godot CLI flags can be ignored by the engine, so exit status is insufficient.

The same trusted runtime serves preview and downloadable source. Developer
extension points are confined to documented custom UI/scripts in their exported
copy; re-export writes a new project. No reverse sync of arbitrary engine edits.
Do not claim Unity support, universal Godot version compatibility or server-side
custom plugin support from this proof.

## Threat and error boundaries

Source content cannot supply `.gd`, `.tscn`, `.tres`, `.gdextension`, plugins,
custom importers, remote assets, engine commands or arbitrary paths. Only PNG
assets copied to deterministic `assets/<id>.png` names are accepted. Validate
actual file signatures, dimensions, hashes and byte limits. Reject symlinks,
absolute/drive/UNC paths, traversal, case-colliding names and out-of-root files.
V1 accepts a local source directory, not untrusted ZIP extraction. Generated
archives contain only exporter-owned relative paths.

Native integration runs only the trusted template against validated fixtures.
Future hosted builds need stronger isolated-worker/origin controls described in
the product brief; a local process with a timeout is not that sandbox. Failures
return explicit format/reference/state/asset/toolchain/build/timeout codes and
leave the input and any pre-existing output untouched. Temporary cleanup verifies
ownership and resolved roots before deletion.

## Verification and acceptance

Add tests before each behavior implementation. Maintain these separate gates:

1. Offline: schema/condition/type/limit errors, no implicit conversions, overflow,
   atomic set failures, empty choices, automatic-loop bound, deterministic traces,
   invalid actions, asset path attacks and invalid/incompatible saves.
2. Fixture: an original short mystery with three endings and expected action/state
   traces, including a trust-gated reveal and a character-knowledge flag. The
   complete 15–30 minute production example belongs to M34, not this fixture.
3. Native Godot: real import/start, reference/engine trace equality for all fixture
   routes, save/load at a choice, incompatible save rejection and clean exit.
4. Browser: serve the actual engine web export; complete a route using UI input,
   test keyboard choice/advance, inspect visible text/portraits and save/load,
   check 1280px and 390px widths, scrolling, console errors and reload behavior.
   Browser persistence is best-effort local storage, not cloud synchronization.
5. Regression: existing backend/unit/eval/lint/type/migration/Compose gates where
   the implementation touches their boundaries. No network/model calls in normal
   offline tests. Toolchain absence is an explicit native/browser skip and blocks
   M30 completion until a real qualification run is recorded.

Record commands, exact engine/runtime versions, route hashes, screenshots,
observed errors and skipped checks in a dated delivery report. Do not close an
issue or call the runtime shipped from documentation or mocks alone.

## Delivery order and review boundary

Implement separate focused issues: package contract and original fixture;
reference execution/save semantics; pinned engine/toolchain and safe source
export; Godot runtime parity; real browser qualification and developer guide.
The exporter can use a fixed initial UI; designing the authoring studio is M31.

Before implementation, the user reviews this written contract. Subsequent work
uses the approved contract to produce a focused implementation plan, then proceeds
issue by issue with tests and live verification. Existing #109 observability WIP
is unrelated and must not be staged, reverted or accidentally included.
