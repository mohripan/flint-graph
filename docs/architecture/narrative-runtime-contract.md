# Reference narrative runtime and saves

M30 / #118. The [package contract](narrative-package-contract.md) validates input.
`Player(load_package(path))` creates one deterministic local session. No API,
database, Temporal workflow or model is required. Godot parity/export and browser
playback remain separate #119–#121 work.

## Actions and presentation

`player.act("advance")` advances a line; `player.act("choose:<option_id>")`
selects an available option at the current choice. Other actions, hidden/unknown
options, and actions after an end/fault raise `PlayerError("invalid_action")`
without changing state. Scripted actions intentionally apply to the current node.

UI callbacks should capture `player.generation` when drawing controls and pass
`expected_generation=captured_generation` to `act`. A stale callback then fails,
including after a loop returns to the same node. This transient session counter
advances after an accepted action or save restoration; it is not serialized as
story state and is not an authorization credential.

On construction or a transition, execute automatic set/branch nodes until a line,
choice, end or fault. At most 1,000 automatic nodes execute per action, including
construction. A set node applies operations in order against a copy and commits
only if every operation succeeds. Signed 32-bit overflow leaves the entire
pre-node variable state intact; completed earlier nodes in the same action stay
committed. Interactive loops can apply a set again; reading a view or restoring
a settled save does not reapply it.

`player.state` returns a fresh object containing `package_hash`, `node_id`,
`variables`, `status`, `ending`, `fault`. Status is `playing`, `ended` or `fault`.
Fault codes are `integer_overflow`, `automatic_transition_limit`,
`no_available_choices`. A valid choice whose conditions expose no options faults
explicitly. Conditions are pure typed comparisons/short-circuit Boolean trees.

`player.view` returns plain node text/text ID, type, speaker ID/display name,
background/portrait IDs and visible option labels/IDs/text IDs. No rich-text or
template evaluation occurs here. Each line derives visuals solely from its
current fields; choices and endings clear previous visuals. Faults show a fixed
message. Returned dictionaries cannot mutate the running state or approved story.

`player.frame(action=None)` returns the normalized cross-runtime trace fields:
`action`, `node_id`, `text_id`, ordered `option_ids`, `variables`, `status`,
`ending`, `fault`. It intentionally excludes renderer pixels, localized display
names, transient callback generations and historical reasoning. Matching fixture
traces proves those routes, not all possible states or story quality.

## Save version 1

`player.save()` returns compact canonical UTF-8 JSON bytes with exactly
`schema_version: "1"` plus the six state fields above. Save identity is bound to
the complete package hash, including notices and assets. Package changes reject
old saves; no migration or cloud synchronization is implied.

`player.load_save(bytes)` validates before any state replacement: strict JSON,
exact field set, schema/package identity, known node, exactly declared variables,
strict Boolean/integer/enum types and bounds, and status/ending/fault consistency.
Playing saves must point to a settled line or nonempty visible choice; ended
saves match that end node; fault saves match the relevant node/condition/overflow
constraints. Restoration redisplays that node without executing automatic nodes.

The save cap is 6 MiB. Variable strings must already occur in the bounded 5 MiB
story's declarations; the additional MiB covers key/metadata and bounded integer
growth. A valid ~2.6 MiB source with 80 large enum variables produces and reloads
a ~1.3 MiB save in regression tests. The original 1 MiB cap was rejected during
review because it failed that valid self-save round trip.

Unknown/malformed/incompatible saves raise `PlayerError("invalid_save")` and leave
both running state and callback generation intact. Local saves are editable player
data, not signed achievements or proof of past actions; validation does not attest
their history. An automatic-limit save cannot prove the historical step count.

## CLI limits and errors

`flint-graph-narrative validate PATH` emits safe JSON. `play PATH --actions FILE`
accepts an explicit UTF-8 JSON array of at most 10,000 actions, at most 80 characters
each and 1 MiB total action input. Scripted normalized frames have a cumulative
8 MiB ASCII-JSON budget, checked before retaining each frame; excess returns
`trace_size_limit` without publishing a partial trace or writing a save. The
final state/view is additionally bounded by the package. This prevents small
action inputs with large enum states from expanding into unbounded output.

`--load FILE` uses the same 6 MiB save cap as the player. `--save-out FILE` creates
a new file exclusively and refuses to overwrite an existing file. Missing parents,
filesystem failures, EOF or interruption return a safe nonzero failure; partial
new files on a host I/O failure are not claimed to be atomic replacements.

`--interactive` prints a terminal-safe text version and accepts Enter or listed
choice numbers, with `q` to stop. C0/C1 terminal controls are visibly escaped,
and numeric parsing is bounded. Its final JSON has `frames: []` and
`trace_complete: false`; it does not claim a complete recorded interactive route.
Scripted output has `trace_complete: true`. Player faults and controlled CLI
errors return exit 1; successful validate/play returns 0. Argparse usage errors
retain standard exit 2. JSON errors never expose absolute paths or input excerpts.
