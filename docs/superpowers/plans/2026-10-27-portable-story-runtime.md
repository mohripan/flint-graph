# Milestone 30 implementation plan

Approved design: [portable story runtime](../specs/2026-10-27-portable-story-runtime-design.md).
User approved continuation on 2026-10-27 and authorized one read-only review
sub-agent. The referenced writing-plans skill is unavailable; this repository
plan is the fallback. No additional approval is required within this scope.

## Boundaries and preservation

Implement #117–#121 in focused commits on the existing default branch, without
co-author trailers. Stage explicit paths only. Preserve unrelated #109 files,
including the modified CI workflow. Keep application databases, private documents,
workspace/index configuration and model selection unchanged.

The approved test seams are local package loading/validation, deterministic
player actions and save/load, CLI operations and safe export, real Godot playback,
and actual browser input. Tests observe public outputs/errors/files rather than
private helper calls. Use red → green vertical slices at each seam.

## 1. Package contract and original fixture (#117)

- Introduce immutable package/asset/diagnostic values and one strict loading
  boundary. Reject duplicate keys and malformed/oversized JSON before semantic
  validation; validate references, typed values, conditions and limits.
- Validate local paths, symlinks/reparse boundaries, allowed file inventory,
  PNG signatures/structure/dimensions/hashes and bounded reads. Preserve original
  inputs. Package identity includes canonical story and notices/asset byte hashes.
- Add an original short mystery, independent literal canonical/hash goldens,
  three route definitions and rights notices. Describe structural warnings as
  structural, not state-space reachability proof.
- Document exact v1 fields and public loader errors; request reviewer feedback,
  run focused plus required backend regression gates, commit/push and close only
  if #117 acceptance passes. Engine qualification is explicitly later.

## 2. Reference player and saves (#118)

- Write a route test first, implement the minimum public player interface, then
  extend through choices, conditions and automatic set/branch transitions.
- Exercise checked arithmetic, atomic node failures, invalid actions, transition
  bounds, convergence, plain presentation and three independently expected ends.
- Add strict revision-bound save/load at settled nodes, preserving running state
  on invalid saves. Produce normalized traces and explicit local CLI operations.
- Verify a real filesystem/CLI session without an API/database/model, document
  and review, then commit/push/close with actual evidence.

## 3. Toolchain and source exporter (#119)

- Inspect official release metadata, select one stable Godot 4 engine and matching
  export templates, verify upstream checksums and record SHA-256s. Downloads are
  task-local/explicit, never global or an offline-test side effect.
- Test fresh-directory export and failure preservation before implementation.
  Package only trusted runtime files and allowed source assets; no input scripts.
- Add a fixed engine template, versioned manifest and reproducible content hashes.
  Reject existing nonempty targets, ownership/path ambiguity and unsupported inputs.
- Qualify real import/export tooling, record exact versions/commands and limits,
  review and commit. Do not close until issue-specific criteria pass.

## 4. Godot player parity (#120)

- Implement the same bounded pure state transitions in reviewed GDScript and a
  small keyboard/mouse UI. Rendering derives from the current node; choice/end
  screens never inherit prior visuals.
- Run all fixture routes, save-at-choice, convergence, incompatible-save and
  fault cases in the real pinned engine and compare normalized reference traces.
- Add opt-in native integration tests with meaningful skip reasons; record live
  output and reviewed source before committing/closing.

## 5. Actual browser qualification (#121)

- Export/serve the real single-threaded Compatibility-renderer game. Test real
  controls and visible text/portraits, keyboard, choice routes, local save/load
  and reload, errors, scrolling and 1280px/390px layouts.
- Use the installed browser skill, preserve user browser sessions and existing
  frontend processes. Capture screenshots and route/state evidence under notes.
- Write the developer/export guide and a dated delivery report. Run applicable
  repository gates. Close M30 only when all focused issues and live proof pass.

## Ongoing review and evidence

The one reviewer inspects package/security and state/hash parity, then changed
implementation and coverage. Resolve material findings before shipping. Log exact
passed/failed/skipped commands; do not equate fixtures with model quality or
structural reachability with exhaustive state exploration. After M30, continue
into the eligible M31 focused design and implementation under the user's standing
instruction, without silently expanding the approved engine/runtime scope.
