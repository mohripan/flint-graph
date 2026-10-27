# Portable narrative package v1

Implemented loader foundation: #117, M30. Reference execution, CLI, Godot export
and browser playback are separate #118–#121 work, not capabilities of this loader.
Approved design: [M30 specification](../superpowers/specs/2026-10-27-portable-story-runtime-design.md).

## Local public boundary

```python
from pathlib import Path
from flint_graph.narrative import PackageError, load_package

try:
    game = load_package(Path("tests/fixtures/narrative/lantern_archive"))
except PackageError as error:
    print(error.code, error.location)
else:
    print(game.story["title"], game.content_hash)
```

This synchronous, provider/DB-independent operation reads a source directory into
an immutable byte snapshot. `canonical_story`, `notices` and each asset's `data`
are bytes; assets/warnings are tuples of frozen values. The `story` and `manifest`
properties return fresh dictionaries so callers cannot alter the captured story
behind its identity. Consumers must use captured asset bytes rather than reopen
source paths. The value constructors are library values, not an alternative
untrusted-input validator; external content enters through `load_package`.

## Directory and trust rules

Only `story.json`, `NOTICES.txt`, an optional `assets/` directory and its declared
PNGs are allowed. Unknown files, subdirectories, symlinks, observed Windows
reparse points/junctions, devices and missing declared files are rejected. File
reads are bounded before allocation, use no-follow where available, and compare
file identities around the open. This is a local content snapshot, not an OS
sandbox against an attacker concurrently controlling the host filesystem.

An asset map entry is exactly `{"path": "assets/<id>.png", "sha256": "<64 lowercase hex>"}`.
IDs use `[a-z][a-z0-9_-]{0,63}`. Asset IDs also reject Windows device basenames
`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`. Paths are exact and case
sensitive; absolute, drive, UNC, traversal and alternate-case paths are invalid.
No remote URLs, scripts, custom engine resources or archive extraction are allowed.

`story.json` is at most 5 MiB; a PNG at most 10 MiB; notices at most 1 MiB;
the package at most 100 MiB. Notices are UTF-8 without NUL. Source JSON is UTF-8
without BOM, duplicate keys, non-finite constants, invalid Unicode/surrogates or
NUL, with a maximum nesting depth of 64. Unknown schema fields are errors.
The original source is never rewritten by loading.

## Exact story structure

The root has exactly these fields:

| Field | Contract |
| --- | --- |
| `schema_version` | String `"1"` |
| `id` | Stable ID |
| `title` | Nonblank plain text |
| `language` | Lowercase 2–3 letter base plus optional hyphenated 2–8 alphanumeric subtags |
| `entry` | Existing node ID |
| `characters` | Up to 256 ID-keyed objects, each exactly `{"name": "display name"}` |
| `variables` | Up to 256 ID-keyed declarations below |
| `assets` | Up to 256 ID-keyed path/hash declarations |
| `nodes` | Nonempty ID-keyed node objects, at most 10,000 |

Declarations are exactly `{"type": "bool", "initial": true}`, or
`{"type": "int", "initial": 0}`, or
`{"type": "enum", "values": ["careful", "hasty"], "initial": "careful"}`.
Integers are signed 32-bit; JSON booleans and floats do not count as integers.
Enums have 1–256 distinct nonblank string values, and their initial value must
be a member. All text values are at most 16,384 Unicode code points; text is
preserved without implicit normalization, stripping, markup execution or coercion.

Each node has the required and optional fields listed below; extra fields fail.

| `type` | Required fields in addition to `type` | Optional fields |
| --- | --- | --- |
| `line` | `text_id`, `text`, `next` | `speaker`, `background`, `portrait` |
| `choice` | `text_id`, `text`, `options` | None |
| `set` | `operations`, `next` | None |
| `branch` | `condition`, `if_true`, `if_false` | None |
| `end` | `text_id`, `text`, `ending` | None |

`next`, `if_true`, `if_false` and option `target` reference existing nodes.
`speaker` references a character; `background`/`portrait` reference assets.
Text IDs are globally unique across node text and option labels. Ending IDs are
unique and at least one end node is required. Narrative display is plain text.
Choice/end screens clear preceding line visuals; save restoration derives the
entire screen from the current node.

`options` is an ordered list of 1–32 objects with exactly `id`, `text_id`, `text`,
`target`, and optional `condition`. Option IDs are unique within their choice.
`operations` is an ordered list of 1–256 objects with exactly `op`, `variable`,
`value`: `op` is `set` or `increment`; increments require an integer variable and
integer literal. Assignments must match the declaration, including enum membership.

A comparison condition has exactly `op`, `variable`, `value`. `eq` and `ne` work
on matching declared types; `lt`, `le`, `gt`, `ge` require integers. Compound
conditions are `{"op": "all" or "any", "children": [...]}` or
`{"op": "not", "child": {...}}`. Children are nonempty; each full expression
has at most 64 condition nodes and depth 8, including its root. Conditions contain
data only, with no general expression language or executable source.

## PNG validation and deliberate format subset

Validate signature, CRCs, chunk framing/order, dimensions, legal color/bit-depth
combinations, palettes/transparency, supported metadata values, bounded zlib
scanline length, filter bytes and stream termination. Dimensions are 1–4096 on
each axis, at most 16,777,216 pixels. Both non-interlaced and Adam7 scanline layouts
are checked. This is structural validation, not a claim of pixel-level visual
correctness or a sandbox for an arbitrary image library.

The initial subset allows `IHDR`, `PLTE`, `tRNS`, consecutive `IDAT`, `IEND` and
bounded `sRGB`, `gAMA`, `cHRM`, `pHYs` chunks. Compressed profiles/text, APNG and
other chunks are unsupported. Art intake can later normalize supported uploads
before creating a package; the loader never silently strips unknown chunks.
Indexed images additionally require a complete `2**bit_depth` palette, which
ensures every representable pixel index exists without a second pixel decoder.
The rules follow the [W3C PNG specification](https://www.w3.org/TR/png-3/), reviewed
2026-10-27. Valid PNGs outside this deliberately constrained subset can be rejected.

## Identity and warnings

Canonical JSON is sorted-key compact UTF-8, without a BOM or trailing newline,
with unescaped non-ASCII text and no Unicode normalization. The reference
serializer is `json.dumps(sort_keys=True, ensure_ascii=False,
separators=(",", ":"), allow_nan=False)`. Arrays retain order.

The canonical package manifest contains `schema_version: "1"`, `story_sha256`,
`notices_sha256` and an ordered `assets` array with each asset's `id`, `path`,
`sha256`. Assets are sorted by ID, equivalent to path order for fixed paths.
`content_hash` is lowercase SHA-256 of the canonical manifest bytes. Timestamps,
source directories and the package hash itself are excluded. Story formatting
or object-key order does not change identity; changing text, notices or asset
bytes does. Fixture text is pinned to LF with `.gitattributes` across checkouts.

`structural_unreachable` marks nodes unreachable when all authored edges are
considered. `structural_cycle` warns that the graph contains a cycle. Neither
evaluates state-dependent conditions or proves an ending is reachable. The
reference player and later route explorer qualify actual state paths separately.

## Errors and fixture

`PackageError.code` identifies parsing/text/schema/object/field/ID/value/reference/
condition/operation/collection/hash/PNG/path/size/file failures. `location` uses
validated IDs and fixed field names, never absolute paths or source excerpts.
Do not show raw `OSError`, parser exception text or untrusted field values to
users. Preserve caller inputs on failure.

The [original fixture](../../tests/fixtures/narrative/README.md) has three authored
route expectations held outside the package. Its content hash is
`057e54a191c2a79d35a52a2d3502d749e214058b79214d5e967a9afb894b3850`.
It demonstrates valid structure, not running gameplay or real model quality.
