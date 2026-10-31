# Narrative voice generation (local CPU)

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
