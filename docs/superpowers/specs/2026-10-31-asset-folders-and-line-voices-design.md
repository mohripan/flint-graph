# Asset folders and voiced dialogue lines

Date: 2026-10-31. Decision record: [ADR 0043](../../adr/0043-asset-folders-and-line-voices.md).
Builds on ADR 0039 (local generation), ADR 0040 (story format 2 and the asset
library) and ADR 0042 (runtime 0.5.0).

## Slice 1: asset folders

### Data

Migration `0028_narrative_asset_folders`:

- `narrative_asset_folders(id, tenant_id, project_id, parent_id, name, created_by_user_id,
  created_at, updated_at)`. The parent is a folder of the same project (composite
  foreign key, `RESTRICT`). Names are 1–80 characters, trimmed, unique among siblings
  ignoring case (checked under the project lock). Depth is at most three.
- `narrative_assets.folder_id`, nullable, with a composite foreign key to a folder of
  the same project and tenant.

### API

All under `/v1/narrative/projects/{project}`; viewers read, members change, archived
projects refuse changes.

- `GET /asset-folders` returns the folders and an index of counts for live
  (non-discarded) assets: per folder (direct contents), unfiled, to review, per kind
  and per character.
- `POST /asset-folders` `{name, parent_id?}` creates; `PATCH /asset-folders/{id}`
  `{name?, parent_id?}` renames or moves (no cycles, depth ≤ 3); `DELETE` moves
  children and assets to the parent, then removes the folder.
- `POST /assets/move` `{asset_ids (1–100), folder_id | null}` files assets.
- `GET /assets` gains `folder` (`<uuid>` or `none`) and `character_id` filters. Asset
  responses gain `folder_id`.

### Studio

The Assets tab gets a side rail: All, To review, Unsorted; By kind; By character
(names from the story, IDs otherwise); and the folder tree with New folder, rename
and delete. Cards and a multi-select bar offer Move to. Generated items need no
filing: by character and by kind are automatic.

## Slice 2: audio assets and voice generation

### Audio files

Canonical WAV: `RIFF` with exactly a 16-byte `fmt ` chunk (PCM, 1–2 channels,
16000/22050/24000/32000/44100/48000 Hz, 16 bits, consistent byte rate and block
align) followed by one `data` chunk that ends the file; at least one frame, at most
60 s and 10 MiB. Uploads may carry other chunks (`LIST`, `fact`, …), an 18-byte
`fmt `, or `WAVE_FORMAT_EXTENSIBLE` with the PCM subformat; these are rewritten
losslessly into the canonical form before hashing. Library kind `voice`, media type
`audio/wav`, a `duration_ms` column, no thumbnail. Object key variant `audio`.

### Voices and jobs

Migration `0029_narrative_voice`:

- `narrative_character_profiles.voice` (Kokoro voice ID, nullable).
- `narrative_voice_jobs`: the image job columns that apply (fence, workflow owner,
  status, progress, cancellation, errors, model, runtime), plus `character_id`,
  `voice`, `speed` (1.0), `seed`, `items` (1–24 objects `{mode, text, node_id?}`).
- `narrative_assets.voice_job_id` with `(voice_job_id, job_index)` unique.

Endpoints: `GET /voices` (the English catalog), `PUT /characters/{id}/voice`
`{base_version, voice | null}`, `POST/GET /characters/{id}/voice-jobs`,
`GET /voice-jobs/{id}`, `POST /voice-jobs/{id}/cancel`. A job needs the character's
voice; texts are 1–600 characters (vocalizations 1–40). Outbox topics
`narrative.voice_job_queued` / `_cancelled`, workflow `NarrativeVoiceJobWorkflow`,
activities `run_narrative_voice_job` / `finalize_narrative_voice_job`.

### Child protocol (`runtimes/voicegen/generate.py`, protocol 1)

Request on stdin: `{protocol, model_dir, output_dir, voice, speed, seed, items:
[{text, mode}]}`. Events on stdout: `loaded {runtime}`, one `clip {index, file,
samples}` per item in order, `done`, or `error {code}`. The parent checks the
event order, the exact output file set, the canonical WAV form (24 kHz mono), the
duration and size caps, then hashes and stores clips create-only. The worker
verifies the model directory against its pinned manifest at startup.

## Slice 3: format, players and builds

- Format 2: asset kind `audio`; line `voice` as in ADR 0043. Stable codes:
  `invalid_voice` (no speaker; text with full voice; vocalization without text),
  `invalid_value` (mode), `invalid_text` (vocalization over 40 characters),
  `unknown_reference` / `invalid_asset_kind` / `invalid_id` (audio). Format 1 refuses
  `voice` with `unknown_field`.
- Views and frames: `voice` is the settled line's clip or `null`.
- Godot runtime 0.6.0: bootstrap caps `wav` at 10 MiB; `vn_view.gd` parses WAV
  strictly, plays the clip when a line settles (also after Load and Restart), stops it
  on the next screen and applies the voice volume (0–100 %, default 100) persisted in
  `user://flint_graph/settings.json`. The preview keeps the setting in memory.
- Preview bridge and Studio playtest accept audio up to 10 MiB per asset.
- Builds: the build child, export preset and builder accept `.wav` with the `keep`
  remap; the toolchain, release identity and child move to 0.6.0.

## Slice 4: Studio

- Characters: a voice picker (Kokoro catalog) and "Try voice", a one-line job.
- Script: each line with a speaker has a Voice select (Silent, Full voice,
  Vocalization + sound text). A voiced line shows its clip state: Generate (or
  "choose a voice first"), progress, candidate with Play / Use / Discard, bound clip
  with Play and Regenerate, and a note when the line text changed after generation.
  A scene-level "Voice missing lines" queues one job per speaker.
- Assets: Voice filter, audio cards with a player, WAV uploads.

## Testing

Test-first per slice: format and player units with a shared `line_voices.json`
fixture used by Python, Godot (frames, WAV parsing), the preview validator and the
TypeScript model; WAV normalization units; folder and voice API integration on
SQLite and PostgreSQL; child protocol units with a fake child; a live Temporal
voice workflow test; real Godot conformance and a Linux release build with audio.
