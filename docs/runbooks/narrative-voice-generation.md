# Narrative voice generation (local GPU, CPU fallback)

Dialogue lines can be silent, fully voiced or marked by a short vocalization such as
"fufu" ([ADR 0043](../adr/0043-asset-folders-and-line-voices.md)). Clips are spoken by
Kokoro-82M on the operator's own GPU (or CPU when the card is busy) through an opt-in
worker. The API only records
jobs; nothing speaks inside a request and nothing calls a paid service. Creators can
also upload their own WAV clips with a rights declaration.

## Requirements

- The Kokoro download (`hexgrad/Kokoro-82M`, revision
  `f3ff3571791e39611d31c381e3a41a3af07b4987`, Apache-2.0): `config.json`,
  `kokoro-v1_0.pth`, `voices/*.pt`, `README.md`, `VOICES.md` and its
  `flintgraph-download.json` manifest in one directory and no other files.
- An NVIDIA GPU with a CUDA 12.8 driver is used when it has at least 1 GiB free
  (qualified on the shared RTX 5070 Ti Laptop GPU, 12 GB); without one, or when the
  card is full, the same job runs on the CPU.
- The isolated runtime, installed once (CUDA 12.8 PyTorch from the same index as
  `runtimes/imagegen`, Kokoro 0.9.4, Misaki 0.9.4 with the pinned spaCy
  `en_core_web_sm` 3.8.0 wheel and the bundled eSpeak NG fallback):

  ```powershell
  cd runtimes/voicegen
  uv sync --frozen
  ```

  Nothing is downloaded at run time: spaCy's model comes from the lock, and the child
  runs with `HF_HUB_OFFLINE=1`. A voice job takes about 1 GiB of GPU memory only while
  it runs, so it fits beside image jobs and the assistant model.

## Configuration

| Setting | Purpose |
| --- | --- |
| `FLINT_GRAPH_NARRATIVE_VOICE_GENERATION_ENABLED` | API admits voice jobs (otherwise 503 `voice-generation-unavailable`). |
| `FLINT_GRAPH_NARRATIVE_VOICE_WORKER_ENABLED` | Explicit opt-in for `python -m flint_graph.processes.narrative_voice_worker`. |
| `FLINT_GRAPH_NARRATIVE_VOICE_TASK_QUEUE` | Its own Temporal queue (default `narrative-voice`; must differ from the others). |
| `FLINT_GRAPH_NARRATIVE_VOICE_RUNTIME_DIR` | Absolute path of `runtimes/voicegen`. |
| `FLINT_GRAPH_NARRATIVE_VOICE_MODEL_DIR` | Absolute path of the Kokoro directory. |
| `FLINT_GRAPH_NARRATIVE_VOICE_MODEL_MANIFEST_SHA256` | SHA-256 of that directory's `flintgraph-download.json`; the worker verifies every file against it at start-up. |
| `FLINT_GRAPH_NARRATIVE_VOICE_DEVICE` | `auto` (default: GPU when ≥ 1 GiB is free, else CPU) or `cpu`. |
| `FLINT_GRAPH_NARRATIVE_VOICE_CUDA_CACHE_DIR` | Where compiled CUDA kernels are kept between jobs (default: a folder in the system temp). |
| `FLINT_GRAPH_NARRATIVE_VOICE_MAX_ACTIVE_JOBS_PER_WORKSPACE` | Queued plus running jobs per workspace (default 4). |
| `FLINT_GRAPH_NARRATIVE_VOICE_JOB_DEADLINE_SECONDS` | Watchdog for one child run (default 600). |

The one-command Studio launcher (`uv run python tools/narrative/studio.py`) runs the
worker as the `voice` service; add the settings above to `studio.local.env` (see
`tools/narrative/studio.env.example`).

## How it works

1. Characters → **Voice** stores a Kokoro voice ID (28 English voices: American and
   British, female and male) on the character's profile. **Try this voice** speaks one
   sample line.
2. Write → each line with a speaker has **Voice**: Silent (default), Full voice or
   Vocalization only with its sound. **Generate voice** (or **Generate N missing
   voices** for a scene) queues a job per speaker with up to 24 texts.
3. The worker claims the job (fenced like image jobs), starts
   `runtimes/voicegen/generate.py` with `python -I`, a private temporary folder, the
   kernel cache and no credentials. The child picks the GPU or the CPU and reports the
   device per clip (stored in the clip's provenance and the job's runtime). The worker
   checks every clip: exactly one canonical 24 kHz mono 16-bit WAV
   per text, of the announced length, at most 60 s and 10 MiB. Clips are stored
   create-only and hash-verified and become candidate `voice` assets with provenance
   (model, voice, text, mode, seed).
4. **Use this clip** approves the candidate and binds it to the line as an `audio`
   story asset by SHA-256. NOTICES credit the model. Playtests and releases play the
   clip when the line appears; the player's **Voice** slider sets the volume.

Measured on the development laptop: on the GPU the first job ever compiles CUDA
kernels (about 50 s); after that a job takes about 8.5 s (imports and model load),
plus well under 0.1 s per line. On the CPU a job takes about 13 s for two lines,
plus 0.2–0.6 s per further line.

## Uploads

Assets → Upload → **Voice clip (WAV)** accepts 16-bit PCM WAV, mono or stereo,
16–48 kHz, up to 60 s and 10 MiB. Metadata chunks, an 18-byte format chunk and
`WAVE_FORMAT_EXTENSIBLE` PCM are rewritten losslessly into the canonical form before
hashing; float, 8/24-bit, compressed and MP3/Ogg files are refused.

## Failure codes

| Code | Meaning |
| --- | --- |
| `empty_speech` | Kokoro produced no audio for a text (for example only punctuation). |
| `too_long` | A clip would be longer than 60 s; split the line. |
| `invalid_output` | The child broke the protocol or wrote a malformed clip. |
| `model_invalid` | The model or voice pack could not be loaded. |
| `generation_timeout` | The watchdog stopped the child. |
| `worker_interrupted` | The run closed without finishing (recovered after 30 minutes). |

## Limits

- English voices only; Japanese and other Kokoro voices need more Misaki packages.
- WAV is uncompressed (≈48 KB per second of mono 24 kHz speech) and counts against the
  48 MiB story asset budget. Fully voiced long stories need a compressed format later.
- Browsers start audio only after a first click or key press. Since runtime 0.6.1 the
  Studio playtest frame inherits the click that opened it (`allow="autoplay"`), so the
  first voiced line plays at once. A web page that still may not play sound shows a
  "Click or press any key to start" screen for stories with voice clips; that input
  starts the first line's clip instead of skipping the line.

## Cloned and expressive voices (ADR 0045)

Beside Kokoro, an operator may install catalog models that clone a voice from a
private reference sample or steer each line's delivery. The catalog, each model's
license text and hash, and the duties its audio carries live in code
(`src/flint_graph/narrative/voice_models.py`); the server offers only models listed in
`FLINT_GRAPH_NARRATIVE_VOICE_MODELS`. Non-commercial weights are not in the catalog
(IndexTTS2 is excluded because its inference needs the CC-BY-NC MaskGCT codec).

| Model ID | Weights (revision) | License | Runtime | Cloning | Delivery |
| --- | --- | --- | --- | --- | --- |
| `chatterbox` | `ResembleAI/chatterbox@5bb1f6e` (English T3 + S3Gen) | MIT, PerTh watermark | `runtimes/voicegen-chatterbox` | yes | approximate (exaggeration) |
| `chatterbox-turbo` | `ResembleAI/chatterbox-turbo@749d1c1` | MIT, PerTh watermark | `runtimes/voicegen-chatterbox` | yes | approximate (style tags) plus sounds |
| `chatterbox-multilingual` | `ResembleAI/chatterbox@5bb1f6e` (Multilingual V3) | MIT, PerTh watermark | `runtimes/voicegen-chatterbox` | yes | approximate; Japanese and 22 more languages |
| `qwen3-tts-clone` | `Qwen/Qwen3-TTS-12Hz-1.7B-Base@fd4b254` | Apache-2.0 | `runtimes/voicegen-qwen3` | yes (a transcript helps) | neutral only |
| `qwen3-tts-voices` | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice@0c0e305` | Apache-2.0 | `runtimes/voicegen-qwen3` | no (nine stock voices) | all ten, by fixed instructions |
| `indextts-2.5` | `IndexTeam/IndexTTS-2.5@c39ce5b` plus w2v-BERT 2.0 (MIT), CAM++ (Apache-2.0), BigVGAN (MIT) | bilibili Model Use License: duties on audio | `runtimes/voicegen-indextts` | yes | emotion vectors; GPU only |

### Installing a model

1. Download the pinned files with their manifest, for example:

   ```powershell
   uv run python tools/narrative/fetch_model.py --repo ResembleAI/chatterbox-turbo `
     --revision 749d1c1a46eb10492095d68fbcf55691ccf137cd --license mit `
     --file README.md --file added_tokens.json --file conds.pt --file merges.txt `
     --file s3gen_meanflow.safetensors --file special_tokens_map.json `
     --file t3_turbo_v1.safetensors --file t3_turbo_v1.yaml --file tokenizer_config.json `
     --file ve.safetensors --file vocab.json --out C:/models/chatterbox-turbo
   ```

   Every file is checked against the hash Hugging Face publishes for that revision; the
   last line prints the manifest SHA-256. IndexTTS-2.5 takes its auxiliaries with
   `--source repo@revision:license:hf_cache/...=files` (see the report for the exact
   command). Interrupted downloads resume.
2. Install the runtime once: `uv sync --frozen` in its `runtimes/voicegen-*` folder
   (Python 3.11, CUDA 12.8 PyTorch 2.8, about 4 GB each).
3. Add the model to `FLINT_GRAPH_NARRATIVE_VOICE_MODELS` (one JSON object on one line,
   see `tools/narrative/studio.env.example`) for both the API and the voice worker, and
   restart them. The worker verifies every file and refuses to start on a mismatch.

`tools/narrative/voice_bench.py` measures a model through the real parent and child
(load time, seconds per line, the child's peak of reserved GPU memory);
`tools/narrative/voice_rating_page.py` builds a local page to rate the samples.

### References, cloned voices and delivery

- **Assets → Voice references** (members only, not viewers): record with the browser
  microphone or upload any audio the browser can decode. The Studio converts it to
  24 kHz mono WAV; the server refuses samples shorter than 5 s, longer than 30 s,
  clipped or near silent. Saving needs the consent declaration ("this is my voice" or
  "the speaker gave me permission") and the speaker's name; who declared it and when
  is recorded, not verified. References live under `voice-references/` in the bucket,
  outside `assets/`, and can never be bound into a story, playtest, release or NOTICES.
  Deleting one removes its audio, blocks queued and new jobs (`reference_deleted`) and
  keeps the consent record that earlier clips name.
- **Characters → Voice model**: Kokoro and Qwen3 stock voices pick a voice; cloning
  models pick a reference. Switching never touches approved clips or bound lines.
- **Write → each voiced line**: a delivery (neutral, happy, angry, sad, afraid,
  surprised, whisper, shout, dramatic, tender) with an intensity, and a sound before
  the line where the model has sounds. It defaults from the line's sprite expression
  (for example crying → sad 0.9); an override is editor metadata. A model that cannot
  do a delivery says so next to the line, and the clip is spoken neutral. Delivery is
  not part of the story format: runtimes play clips and never speak.
- Every clip's provenance names the model, its license (ID, name, hash, duties), the
  reference hash and consent record, the delivery, the language, the watermark and
  the device. Job runtime records each child's peak GPU memory.

### Licenses, NOTICES and the player license screen

- A model whose license puts duties on its audio (IndexTTS-2.5) opens a dialog with
  the license text and a plain summary when a creator first chooses it. Generation
  starts only for a creator who accepted the current text in that workspace
  (`voice-license-not-accepted`); a changed text asks again.
- Saving a revision rebuilds NOTICES from the bound clips' licenses: clips keep their
  attribution line, and any license with duties adds its full text. When a license
  requires player terms, NOTICES ends with a block between
  `=== Player terms (shown once to players by the game) ===` and
  `=== End of player terms ===`. Creators cannot remove it; it is recomposed on save
  and checked again at build time.
- Releases → **Voice licenses this release carries** lists each license and the lines
  that cause it, so a line can be regenerated with another model to drop a duty.
- Runtime 0.7.0 shows the terms once before play in exported games (kept per story and
  terms hash on the device) and in every Studio playtest; **License** in the menu shows
  them again. The game shows the summary and the English agreement; the full bilingual
  agreement, whose Chinese text prevails, is in the `NOTICES.txt` every build ships.

### GPU sharing

Each child uses the GPU only when NVML reports its measured peak plus headroom free
(Chatterbox 4.5 GiB, Turbo 3.5, Multilingual 4.5, Qwen3-TTS 5.5, IndexTTS-2.5 7.0),
otherwise Chatterbox and Qwen3 speak on the CPU and IndexTTS-2.5 refuses with
`gpu_busy`. Measured beside a background-image job (8.5 GB), a Turbo job still ran on
the GPU (card peak 11.4 of 11.9 GB) and took 64.6 s instead of 58.4 s.

### More failure codes

| Code | Meaning |
| --- | --- |
| `gpu_busy` | The GPU had too little free memory for a GPU-only model. Retry later. |
| `reference_deleted` | The voice reference was deleted before the job spoke. |
| `reference_invalid` | The model could not use the reference audio. |
| `reference_unavailable` | The reference audio could not be read from storage. |
| `voice_generation_unavailable` | The worker has no generator for the job's model. |
