# Project asset library and generated backgrounds (#128, #161 first slice)

Slice 1 of [ADR 0040](../adr/0040-visual-novel-stage-theme-and-asset-library.md)
([design](../superpowers/specs/2026-10-31-vn-stage-and-asset-library-design.md)). The
user asked for asset management and backgrounds before the visual novel stage and
textbox.

## Delivered

- **Assets tab.** A library with filters for backgrounds, sprites, images, fonts,
  portraits and items to review. The Studio hides the scene rail here. Each item can
  be approved, renamed or discarded, images open full size, and fonts preview in
  themselves. A "Generate backgrounds" form shows live progress and a Cancel button.
- **Uploads** (`POST /assets`, multipart):
  - PNG images keep transparency, up to 10 MiB and the strict validator's limits.
    Editor metadata (text, time, ICC profiles, background hints) is stripped losslessly
    before hashing.
  - TrueType/OpenType fonts are accepted up to 8 MiB after sfnt structure checks.
    Fonts are refused if they are variable, use colour, bitmap, SVG, Graphite or AAT
    tables, or have restricted embedding.
  - Every upload records a licence, an optional notice and the uploader's rights
    declaration. The system does not verify ownership. Validation runs off the event
    loop, at most two at a time.
- **One asset per file.** A partial unique index on `(tenant, project, sha256)` for
  live rows means identical uploads return the existing asset (409 if it has another
  kind). Repeated generated images are skipped.
- **Backgrounds.** Jobs on the ADR 0039 pipeline (`purpose=background`) render
  1344×768 scenery with `no humans`. The negative prompt excludes people. Candidates
  get readable names, list in generation order, and wait for approval.
- **Migration 0024** adds asset names, notices, rights declarations, the new kinds,
  nullable font dimensions and thumbnails, and background jobs without a character.

## Live qualification (owned API, worker, RTX 5070 Ti, MinIO, browser)

- A transparent sprite (240×480) and a static Lora instance (made with fontTools from
  the bundled variable font) were uploaded through the real dialog. The sprite shows
  on a transparency checkerboard. The font loads as a `FontFace` from authenticated
  bytes and renders its sample.
- An upload whose bytes were corrupted while being pasted in by hand was refused with
  "Upload a PNG image", as intended.
- Four harbour-at-dusk backgrounds took 85 s, including the Ollama model release. The
  output was 1344×768 with lanterns, pier and lighthouse and no people. One was
  approved and one discarded in the UI.
- At 375×812 the Assets grid shows two columns with no horizontal scroll.

## Owned environment

Docker restarted on 2026-10-31 and wiped the owned PostgreSQL, MinIO and Temporal
fixtures, which kept their data in tmpfs; every Studio project was lost. At the
user's request, `notes/persist-narrative-fixtures.py` recreated the fixtures with
named volumes, fixed loopback ports and `--restart unless-stopped`, keeping the same
images, users, limits and hardening. A container restart then preserved the schema and
a stored object.

## Verification

- Unit tests:
  - font checks (20);
  - PNG normalization (5);
  - prompts, background included (9).
- Integration tests:
  - asset library and characters, 15 tests run on SQLite and on the owned PostgreSQL
    (30 runs), with migration 0024 applied;
  - live Temporal image workflow (3).
- Frontend: `npm test` 70, `npm run typecheck`, `npm run build`.
- Gates: full `uv run pytest`, `ruff check`, `mypy`, `uv lock --check`, offline
  migration SQL (head 0024), compose config and the deterministic eval.

## Next

Slice 2 covers the package v2 format, saves, the reference player, server-built
NOTICES and asset binding, following the review changes in the design. Variable fonts
could later be flattened at upload instead of refused.
