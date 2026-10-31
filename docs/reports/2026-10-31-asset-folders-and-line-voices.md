# Asset folders and voiced dialogue lines (runtime 0.6.0)

Delivered [ADR 0043](../adr/0043-asset-folders-and-line-voices.md) following its
[design](../superpowers/specs/2026-10-31-asset-folders-and-line-voices-design.md), in the
order the user asked for: asset folders first, then voice audio for dialogue lines.
The branch is rebased onto master `2bbe8d7` (the Assets tab's CG section now opens from
the rail's CGs group).

## Asset folders

- **Model.** Migration `0028` adds `narrative_asset_folders` (names unique among
  siblings ignoring case, three levels at most, project-scoped composite keys) and
  `narrative_assets.folder_id`. Folders never touch asset bytes, hashes, stories,
  revisions or releases. Deleting a folder hands its subfolders and assets to its
  parent.
- **API.** `GET/POST /asset-folders`, `PATCH/DELETE /asset-folders/{id}` and
  `POST /assets/move` (1–100 assets, or back to no folder). `GET /assets` filters by
  `folder` (an ID or `none`) and `character_id`. Viewers read; members change; archived
  projects refuse changes.
- **Studio.** The Assets tab has a rail: All assets, To review and Unsorted; automatic
  groups by kind and by character (names from the story), which organize generated
  items with no manual filing; and the folder tree with New folder, New folder inside,
  Rename folder and Delete folder. Cards have a selection box; a bar moves the
  selection to any folder or back to Unsorted. Cards say which folder they are in.

## Voiced lines

- **Format 2 (additive).** Asset kind `audio` (`assets/<id>.wav`, canonical 16-bit PCM
  WAV: one 16-byte `fmt ` chunk, then one `data` chunk ending the file; mono or stereo;
  16–48 kHz; at most 60 s and 10 MiB). A line may carry
  `voice: {"mode": "full" | "vocalization", "text"?, "audio"?}`; absence means silent.
  A voice needs a speaker, a vocalization needs its sound (≤ 40 characters), full voice
  refuses one, and a voice without `audio` plays nothing yet. Stable codes:
  `invalid_voice`, `invalid_value`, `invalid_text`, `unknown_reference`,
  `invalid_asset_kind`, `invalid_id`; format 1 refuses `voice` (`unknown_field`).
  Views and frames carry `voice` (the settled line's clip or null); saves are unchanged.
- **Four implementations.** The Python validator and player, the Godot player
  (`player.gd`, runtime 0.6.0), the playtest validator (`validate_story.gd`) and the
  editor model (`voiceModel.ts`) share `tests/fixtures/narrative/line_voices.json`.
  The stage view parses WAV strictly (Python and GDScript agree on valid and broken
  files), starts a clip one frame after its line settles, stops it on the next screen,
  replays it after Load and Restart, and has a Voice slider (0–100 %) kept in
  `user://flint_graph/settings.json`; playtests keep it in memory. The bridge, preview
  and Studio playtest accept audio up to 10 MiB; builds accept `.wav` with the exact-bytes
  `keep` remap; the toolchain, release identity and build child moved to 0.6.0.
- **Generation (ADR 0039 pattern, CPU).** `runtimes/voicegen` is an isolated child with
  its own uv lock (CPU PyTorch 2.11, Kokoro 0.9.4, Misaki 0.9.4, spaCy model pinned as
  a wheel, eSpeak NG fallback for sounds such as "fufu"), started with `python -I`, a
  minimal environment, offline flags and a watchdog. The opt-in
  `narrative_voice_worker` owns the `narrative.voice_job_*` outbox topics and a fenced
  `NarrativeVoiceJobWorkflow` on its own queue (IDs only in history), verifies the
  Kokoro directory against its manifest at start-up, checks every clip as canonical
  24 kHz mono WAV of the announced length, stores it create-only and hash-verified, and
  records it as a candidate `voice` asset with model, voice, text, mode and seed.
  Migration `0029` adds `narrative_voice_jobs`, the profile `voice`, asset
  `duration_ms` and `voice_job_id`, the `voice` kind and `audio/wav`.
- **Uploads.** WAV voice clips upload with the existing rights declaration; metadata
  chunks, 18-byte and `WAVE_FORMAT_EXTENSIBLE` PCM formats are rewritten losslessly to
  the canonical form before hashing.
- **Binding.** Approved clips bind to stories by SHA-256 like images; NOTICES gain an
  audio entry crediting `hexgrad/Kokoro-82M@f3ff3571…` (Apache-2.0).
- **Studio.** Characters → Voice picks one of 28 English Kokoro voices and **Try this
  voice** speaks a sample. In the script, each line with a speaker has Voice: Silent,
  Full voice or Vocalization only (with its sound). It shows Generate voice (or why
  not), progress, candidates to Listen / Use this clip / Discard, the bound clip with
  Play, Regenerate and Remove clip, a note when the words changed after generation, and
  a clip picker for uploads. A scene offers **Generate N missing voices** (one job per
  speaker). The asset library plays clips and shows their length.
- **Assistant.** Voice actions are left for a follow-up. The outline shows each line's
  voice, and a line the assistant rewrites for the same speaker keeps it.
- **Launcher.** `tools/narrative/studio.py` runs the worker as the `voice` service.

## Live run (local Studio from this branch)

The user's own Studio (master, ports 8101/5192) kept running untouched. This branch ran
as a separate instance: ports 8111/5202/5183, a new `flint_voice_qa` database on the
owned PostgreSQL, the owned MinIO and Temporal with separate task queues, a playtest
build for `http://localhost:5183` and a freshly prepared builder image
(`sha256:9ba436ec…`, toolchain `10d8bc61…`). Services: API, release worker and relay,
voice worker, playtest server and frontend. Steps in the in-app browser:

1. A new workspace and project "Lantern voices QA" (format 2), with a four-line script
   seeded through the API.
2. **Character voices.** Mira → Emma (British), Quen → Bella (American). **Try this
   voice** returned Mira's sample within 30 s and it played in the Studio.
3. **Lines.** Mira's first line → Full voice; Quen's line → Vocalization only "fufu";
   the narration (no speaker) has no voice control; Mira's last line stays Silent.
   **Generate 2 missing voices** queued two jobs; both candidates arrived within 40 s
   (3.9 s and 1.5 s clips). **Use this clip** approved and bound them, and revision 3
   saved with both `audio` assets.
4. **Playtest.** Revision 3 opened in the Studio playtest with the Voice slider in the
   toolbar. Its iframe is cross-origin, so playback there was not inspected by script.
   The same preview view was checked headlessly in Godot (below).
5. **Release.** A real build on runtime 0.6.0 completed. The source ZIP holds both WAVs
   with `keep` remaps, and NOTICES carries the audio entries. The 10.5 MB web build,
   served locally and played in the browser pane: line 1 played Mira's clip
   (`voice_playing` true), line 2 played `quen_fufu`, the narration stopped it and played
   nothing. The Voice slider set to 30 % survived a reload.
6. **Folders.** The rail grouped the three clips (Voice clips 3; Mira 2, Quen 1; one
   sample to review). A folder "Voices" with "Harbor scene" inside was created, and both
   line clips moved into it in one step ("Moved 2 assets."); counts and labels updated.

Evidence (non-secret: hashes, pins, timings):
[qualification.json](evidence/asset-folders-and-line-voices-2026-10-31/qualification.json).

## Verification

Tests came first in each slice.

- **Unit.** WAV form and normalization (20), shared voice fixture on the Python
  validator, player and package (4), the voice child's trusted parent against a scripted
  child (17), v2 release export and build child with a WAV (15), worker settings,
  launcher, assistant voice guard.
- **Integration** (SQLite and a disposable database on the owned PostgreSQL, real
  migrations): folder API (3 × 2), voice API with the worker activity, candidate clips,
  approval-gated binding, NOTICES, revision asset serving and WAV uploads (3 × 2). The
  narrative selection: **280 passed, 10 skipped**.
- **Real Godot 4.7.2** (`test_narrative_line_voices_live.py`, with the existing Godot,
  preview and CG suites): frames match the reference on the voiced route; the playtest
  validator agrees on every shared case; runtime and preview views play, stop and replay
  clips, parse six WAV cases exactly as Python does, and keep the volume on disk
  (export) or in memory (playtest). **37 passed**, plus the Linux release builder test on
  the new image (**1 passed**).
- **Frontend.** `npm test` **100 passed** (voice model parity with the shared fixture,
  folder model), typecheck and production build.
- **Gates.** `uv run pytest` **1,795 passed, 102 skipped** (opt-in live and service
  tests); `ruff check`; `mypy`; `uv lock --check` (root and `runtimes/voicegen`);
  offline migration SQL through `0029`; `docker compose config`; the deterministic eval.

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy
uv lock --check; cd runtimes/voicegen; uv lock --check
$env:FLINT_GRAPH_ENV='test'; uv run alembic upgrade head --sql
docker compose config --quiet
npm --prefix frontend test; npm --prefix frontend run typecheck; npm --prefix frontend run build
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py tests/integration/test_narrative_line_voices_live.py -q
uv run python tools/narrative/prepare_builder.py --engine <linux godot> --templates <templates> --output <dir> --build
uv run python tools/narrative/build_preview.py --engine <win64 godot> --templates <templates> --parent-origin http://localhost:5183 --output <dir>
```

The PostgreSQL run created and dropped its own database; the owned connection settings
were read from `studio.local.env` and never printed.

## Notes and limits

- WAV is uncompressed (≈48 KB/s of mono 24 kHz speech). Fully voiced long stories will
  need a compressed format (Ogg Vorbis with #163, music and sound effects).
- English voices only for now.
- Browsers start audio after the first click or key press, so a release's first line
  may be silent until the player interacts.
- The QA database `flint_voice_qa` and its MinIO objects can be dropped.
