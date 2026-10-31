# Visual novel stage, theme and asset library

Date: 2026-10-31. Decision: [ADR 0040](../../adr/0040-visual-novel-stage-theme-and-asset-library.md).
Tracking: #157 (package v2), #128 (asset library), #161 (backgrounds), #164 (themed
player). Character sprite generation (#158/#167/#170) builds on this next.

## Goal

The user's request (2026-10-31):
- an asset library;
- backgrounds that stay for a scene;
- characters on stage;
- a dynamic game UI where the textbox has its own style, sits where the creator
  wants (usually the bottom), and can use an uploaded or built-in font.

The playtest and exported Godot games must show it.

## Asset library (#128)

`narrative_assets` gains kinds and an upload path (migration 0024):

| Kind | Media | Source | Notes |
| --- | --- | --- | --- |
| `character_portrait` | PNG | generated (ADR 0039) | existing |
| `background` | PNG | generated or uploaded | landscape suggested |
| `sprite` | PNG (alpha kept) | uploaded now, generated later | full-body character art |
| `image` | PNG | uploaded | CGs and other art |
| `font` | TTF/OTF | uploaded | `font/ttf`, `font/otf` |

Each asset has these columns:
- a `name` of 1–120 characters, which the creator can rename;
- for uploads: `license` (1–120 characters, such as "Own work", "CC BY 4.0" or
  "OFL-1.1"), `notice` (up to 4,000 characters of attribution text shipped in
  NOTICES), and `rights_declared_by_user_id`/`rights_declared_at`. The upload form
  requires the declaration "I made this or have the right to use it in my game".
  The system records it and does not verify ownership;
- `width`/`height`, which are null for fonts.

Uploads are approved on upload, since the uploader decides. Generated images stay
candidates until approved.

Upload validation runs before anything is stored:
- PNG: at most 10 MiB, the existing strict validator, at most 4096 px per side and
  16.7 MP. Colour type 6 alpha is allowed.
- Fonts: at most 8 MiB. The sfnt version must be `0x00010000`, `true` or `OTTO`. The
  table directory must be in bounds with sorted, non-overlapping tables, and must
  include `head`, `name`, `cmap`, and `glyf`/`loca` or `CFF `. Collections, WOFF and
  WOFF2 are rejected.

Uploads have no thumbnail: the thumbnail columns repeat the original, and fonts have
none.

API, all under `/v1/narrative/projects/{project_id}`:
- `GET /assets?kind=&status=&limit=&before=` lists assets.
- `POST /assets` takes multipart `file`, `kind`, `name`, `license`, `notice` and
  `rights_declared=true`.
- `PATCH /assets/{id}` renames.
- `POST /assets/{id}/approve` approves; discard already exists.
- `POST /assets/background-jobs` takes a description, a count and an idempotency key.

Background jobs reuse the ADR 0039 pipeline with `purpose=background` and a nullable
`character_id`, at 1344×768. The prompt is `no humans, scenery, {description}, …`
with people terms added to the negative prompt.

Viewers read; members upload, generate, rename, approve and discard. An asset used
by the head revision cannot be discarded (409).

## Story package v2 (#157)

```json
{
  "schema_version": "2",
  "id": "harbor", "title": "Harbor", "language": "en", "entry": "s0",
  "characters": {
    "mira": {"name": "Mira", "color": "#d5ae68",
             "sprites": {"neutral": "mira_neutral", "happy": "mira_happy"}}
  },
  "variables": {},
  "assets": {
    "harbor_dusk": {"kind": "image", "path": "assets/harbor_dusk.png", "sha256": "…"},
    "mira_neutral": {"kind": "image", "path": "assets/mira_neutral.png", "sha256": "…"},
    "old_type": {"kind": "font", "path": "assets/old_type.ttf", "sha256": "…"}
  },
  "theme": {
    "textbox": {"position": "bottom", "width": 92, "background": "#182635e6",
                "text": "#f0f4f6", "border": "#d5ae68", "radius": 12},
    "name": {"show": true, "background": "#d5ae68", "text": "#182635"},
    "choices": {"background": "#f0f4f6", "text": "#182635", "border": "#d5ae68"},
    "font": {"asset": "old_type", "size": 22}
  },
  "nodes": {
    "s0": {"type": "stage", "background": "harbor_dusk",
           "show": [{"character": "mira", "sprite": "neutral", "position": "left"}],
           "next": "l1"},
    "l1": {"type": "line", "speaker": "mira", "expression": "happy",
           "text_id": "l1", "text": "The bell!", "next": "end"}
  }
}
```

### Asset rules

Asset `kind` is `image` (PNG, `assets/<id>.png`) or `font` (`assets/<id>.ttf` or
`.otf`). The limit stays at 256 assets. Images remain at most 10 MiB, fonts at most
8 MiB, and the package at most 100 MiB.

### Characters and theme

- **Characters:** `name` is required. `color` is optional `#rrggbb`. `sprites` maps
  expression IDs to image assets, with at most 32.
- **Theme:** optional, a closed object; every field has a default.
  - `textbox.position` is `bottom`, `middle` or `top`.
  - `textbox.width` is an integer from 40 to 100 (% of the stage width).
  - Colours are `#rrggbb` or `#rrggbbaa`.
  - `radius` is 0–48.
  - `name.show` is a boolean, and the name box has two colours.
  - `choices` has three colours.
  - `font.asset` is a font asset or null. Null means the bundled Lora face.
  - `font.size` is 14–48.

### Nodes

- **`stage` node:** `background` is optional. Absent keeps the background, `null`
  clears it, and an ID sets it (`image` kind). `hide` lists up to 8 character IDs;
  `show` lists up to 8 entries of `{character, sprite, position}`, where `sprite` is
  one of the character's expressions and `position` is `left`, `center` or `right`.
  `next` is required. Hide applies before show. Showing a character already on stage
  updates its sprite and position. Showing at an occupied position removes the
  previous occupant. A stage node with no effect is a validation error.
- **`line` node:** `expression` is optional and requires a `speaker` whose sprites
  include it. If the speaker is on stage, their sprite changes and stays changed.
  Otherwise nothing visible happens and validation emits a warning. v1's `background`
  and `portrait` line fields do not exist in v2.

### Execution state

`stage` is `{"background": id|null, "characters": [{"id", "sprite", "position"}]}`,
ordered left, center, right. Stage nodes are applied atomically on a copy, like
`set`. Choice and end screens keep the stage. The view adds `stage` and
`speaker_color`. Save schema `2` stores stage state and is validated on load: assets,
characters and sprites must exist, positions must be valid, and characters must be
unique. Normalized conformance traces include stage state.

## Runtimes

- **Python reference** (`validation.py`, `player.py`): v1 and v2 side by side,
  selected by `schema_version`.
- **Godot:**
  - `bootstrap.gd` accepts font paths.
  - A new `vn_view.gd` renders v2: a full-rect background (cover), a character layer
    with three anchored slots (sprites keep aspect and stand on the bottom edge), and
    the textbox overlay positioned, sized and coloured from the theme, with a name
    box.
  - Choices are centred buttons; a compact Save/Load/Restart menu sits top-right.
  - Fonts load as `FontFile` from verified bytes. The text label keeps BBCode off.
  - v1 keeps `game_view.gd`.
- **Preview:**
  - The bridge's `load-snapshot` version 2 adds `assets: {id: base64}`, bounded at
    100 MiB decoded. The preview validator checks every SHA-256 before play.
  - The Studio resolves story asset hashes through the library and fetches bytes
    with the creator's credentials.
  - The preview build is rebuilt.
- **Releases:** the builder accepts assets. The input loader resolves each story
  asset hash to an approved library asset of the project and fetches its bytes
  verified. The PNG validator and the font checks run again. NOTICES gain an "Asset
  notices" section built from asset names, licences, notices and generator model
  licences, sorted by asset ID.

## Studio

- **Assets tab:** a filterable grid (Backgrounds, Sprites, Images, Fonts, Portraits,
  plus a Candidates filter), with:
  - an upload dialog with the rights declaration;
  - a "Generate backgrounds" form (description, four candidates, live progress);
  - approve, rename and discard actions;
  - font previews rendered with the font itself.
- **Look tab:** the theme editor, with a live CSS mock of the stage and textbox at
  each position.
- **Scene stage:** the top of the script editor shows the scene's background
  (thumbnail picker) and the characters on stage (character, expression,
  left/center/right, remove). Changes write a `stage` node at the start of the
  scene; the summary shows the stage inherited from earlier scenes.
- **Lines:** an expression picker sits beside the speaker when the speaker has
  sprites.
- **Characters:** the sheet gains a Sprites section with expression slots filled
  from library sprites, images or portraits.
- **Upgrade:** v1 projects show "Use stage & theme (v2)", which creates the upgraded
  revision. New projects default to v2 once runtimes, preview and releases support it.

## Delivery slices

1. **Asset library:** migration 0024, uploads with font and PNG validation, kinds,
   background jobs, and the Assets tab.
2. **Package v2:** validation, reference player, saves, traces, upgrade, and the
   editor model and types.
3. **Godot `vn_view`:** preview bridge v2, preview rebuild, release builder assets
   and NOTICES.
4. **Studio:** Look tab, scene stage, expressions, character sprites, and new
   projects on v2.

Each slice adds tests first and gets live qualification (browser playtest and a real
release build for slices 3 and 4) before it is committed.

## Review changes (2026-10-31)

An independent review of this design found the following. These rules override the
sections above where they differ.

**Slice 1 (done with the library):**
- One live row per file per project: a partial unique index on
  `(tenant_id, project_id, sha256)` for non-discarded rows. Re-uploading identical
  bytes returns the existing asset, or 409 if it has another kind.
- PNG metadata chunks (text, time, ICC profiles, background hints) are stripped
  losslessly before hashing. Unknown critical chunks are rejected. Inspection runs off
  the event loop, at most two at a time per process.
- Fonts with colour, bitmap, SVG, Graphite or AAT tables are rejected, as are fonts
  with restricted-licence embedding (`OS/2.fsType`).
- Variable fonts (`fvar`, `gvar`, `avar`, `cvar`, `HVAR`, `VVAR`, `MVAR`, `CFF2`) are
  rejected with a message asking for a static TTF/OTF. Variation code is the most
  complex, historically exploited part of font rendering (for example FreeType
  CVE-2025-27363), and uploaded fonts ship to other people's devices. Static
  instances are readily available, for example in the `static/` folder of Google Fonts
  downloads. Flattening variable fonts to a static instance at upload (fontTools in a
  limited child) is a possible later improvement.
- Re-serializing fonts through a sanitizer remains a known gap.

**Slice 2 (save path):**
- **NOTICES:** the server writes the "Asset notices" section when a revision is
  saved. It appends to `revision.notices` from immutable fields only (story asset ID,
  SHA-256, kind, licence, notice, generator model and licence), never names. It is
  deduplicated and bounded in UTF-8 bytes. The builder only verifies, so package
  hashes stay equal across playtest and release.
- **Binding:** story assets bind by SHA-256 within the tenant and project; missing and
  foreign hashes give the same 404. An `image` asset binds to portrait, background,
  sprite or image kinds; a `font` asset binds to fonts. The extension comes from the
  validated font flavour.
- **Discard:** discard only hides an asset from pickers. Bytes stay available to every
  revision that bound them. Asset rows are locked on both the save and discard paths.
- **Size budget:** an asset size budget is enforced at save time, using the library's
  sizes against the release limits.
- **Upgrade:** creating v2 revisions stays behind a flag until slice 3 qualifies
  playtest and release.
- **Scene projection:** `stage` nodes are continuations, like `set` nodes.
- **Assistant:** character updates merge `name` only, so `sprites` and `color`
  survive, and prompts and context learn the v2 vocabulary.

**Stage rules for all four implementations:**
- The initial stage is `{background: null, characters: []}`.
- Hiding an absent character is a no-op.
- `hide` IDs are unique. `show` entries have unique characters and unique positions
  (at most 3), and no character appears in both lists.
- A stage node has an effect when `background` is present, or `hide` or `show` is
  non-empty.
- A line's `expression` applies when the line settles. It is recorded in that state
  and save, and never reapplied on load or redisplay.
- Fault screens keep the stage.
- Save v2 validation:
  - characters are in canonical position order with unique positions;
  - each sprite belongs to its character's `sprites`, and the background is an
    `image` asset;
  - `automatic_transition_limit` may be raised at `stage` nodes.
- v1 frames, views and golden traces stay byte-identical, with no `stage` key.
- "Speaker not on stage" warnings and the scene summary's inherited stage come from a
  forward analysis: each character is on, off or unknown, and the background is an ID
  or unknown, with joins producing unknown. Warnings fire only on definite absence;
  disagreeing paths show "varies by path".

**Theme:**
- Colours match `^#[0-9a-f]{6}([0-9a-f]{2})?$` in every validator and are parsed by
  hand.
- Every sub-object and field is optional, with closed keys.
- Defaults: bottom textbox at width 92, `#182635e6` box, `#f0f4f6` text, `#d5ae68`
  border, radius 12, name box shown in `#d5ae68`/`#182635`, choice buttons
  `#f0f4f6`/`#182635`/`#d5ae68`, and Lora at size 22.
- An absent or `null` `font.asset` means Lora, which is also the fallback.

**Slice 3 (runtime, preview, release):**
- **Preview:**
  - Assets travel as `ArrayBuffer`s in the postMessage transfer list. The bridge
    checks the count (at most 256), per-kind caps and the total. Godot pulls assets
    one at a time, with no base64 or JSON wrapping.
  - The Studio fetches and hash-checks the assets before mounting the iframe, and
    starts its timeout after posting.
  - v1 revisions keep message version 1. `validate_story.gd` builds the schema "1"
    manifest of sorted `{id, path, sha256}` entries.
- **Release build budget:**
  - Child input, output and zip file limits, publication caps and the `/scratch`
    tmpfs are raised or the v2 total is lowered, each with tests.
  - Export presets include fonts with keep remaps.
  - `vn_view.gd` joins `TEMPLATE_FILES`, `RUNTIME_FILES` and the runtime file list.
  - `runtime_version` and the builder image pin change. Releases pinned to the old
    runtime then report `runtime_unavailable`, which is stated in their history.

## Out of scope here

The following are later work:
- generated transparent full-body sprites, expression sheets and poses (next slice,
  using the downloaded models);
- transitions and effects (#162);
- audio (#163);
- free x/y positions and more than three slots (#160);
- a gallery and CGs (#161);
- player name input (#165);
- long-form storage (#172).
