# Expressive and cloned character voices (M39, #173)

Date: 2026-11-01. Branch `claude/m39-voices`. Decision:
[ADR 0044](../adr/0044-expressive-and-cloned-character-voices.md). Operations:
[runbook](../runbooks/narrative-voice-generation.md). Evidence:
[`evidence/m39-voices-2026-11-01/`](evidence/m39-voices-2026-11-01/).

## What changed

- **#174 models.** A code catalog of six voice models beside Kokoro-82M with license
  texts, hashes, duties, deliveries and GPU needs; three isolated runtimes
  (`runtimes/voicegen-chatterbox`, `-qwen3`, `-indextts`; Python 3.11, CUDA 12.8
  PyTorch 2.8, own uv locks) speaking protocol 2; a pinned, hash-verified downloader
  (`tools/narrative/fetch_model.py`); a benchmark (`voice_bench.py`) and a local rating
  page (`voice_rating_page.py`). IndexTTS2 is excluded (CC-BY-NC MaskGCT codec);
  IndexTTS-2.5 is offered instead.
- **#175 references.** Members record or upload a 5–30 s sample with a consent
  declaration; private table and object prefix; deletion removes audio and blocks jobs
  (migration `0031_narrative_voice_references`).
- **#176 cloned voices.** A character's voice is a model plus a stock voice or a
  reference; jobs snapshot model, reference hash and consent; provenance names model,
  license, reference, consent, watermark, delivery, language and device (migration
  `0032_narrative_voice_models`).
- **#177 delivery.** Ten deliveries with intensity, a fixed per-engine mapping, sounds
  from each model's list, defaults from the line's expression, overrides as editor
  metadata, and plain notes where a model cannot do a delivery. Not in story format 2.
- **#178 licenses.** Catalog API with license metadata, a license dialog, per-workspace
  acceptance by license hash, NOTICES with license texts and a player-terms block,
  a pre-build list of carried licenses and causing lines, and runtime 0.7.0's one-time
  player license screen in exports and playtests.

## Licenses (verified 2026-10-31 from the official repositories and model cards)

| Weights | Revision | License | Note |
| --- | --- | --- | --- |
| `ResembleAI/chatterbox` | `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18` | MIT | English T3/S3Gen and Multilingual V3 |
| `ResembleAI/chatterbox-turbo` | `749d1c1a46eb10492095d68fbcf55691ccf137cd` | MIT | tokenizer adds style and sound tags |
| `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | `fd4b254389122332181a7c3db7f27e918eec64e3` | Apache-2.0 | cloning |
| `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | `0c0e3051f131929182e2c023b9537f8b1c68adfe` | Apache-2.0 | nine stock voices, instructions |
| `IndexTeam/IndexTTS-2.5` | `c39ce5ba981572cb187443877ff559dfb246ce63` | bilibili Model Use License | LICENSE bytes = GitHub `LICENSE` (same agreement as IndexTTS2) |
| `facebook/w2v-bert-2.0` | `da985ba0987f70aaeb84a80f2851cfac8c697a7b` | MIT | IndexTTS-2.5 auxiliary |
| `funasr/campplus` | `e4b6ede7ce16997aff4ae69fbca1f0175e2afede` | Apache-2.0 | IndexTTS-2.5 auxiliary |
| `nvidia/bigvgan_v2_22khz_80band_256x` | `633ff708ed5b74903e86ff1298cf4a98e921c513` | MIT | IndexTTS-2.5 auxiliary |
| `amphion/MaskGCT` | — | **CC-BY-NC-4.0** | needed by IndexTTS2 only: excluded |

Code: Chatterbox MIT (pinned commit `5de7a54`, because the 0.1.7 release hard-codes
Multilingual V2; Perth 1.0.1 MIT), qwen-tts 0.1.1 Apache-2.0, index-tts `d9e41aa`
under the bilibili agreement. Manifests (SHA-256 of `flintgraph-download.json`):
Turbo `c9d142e5…`, Chatterbox English `2df618a5…`, Qwen3 Base `8e2a45e1…`,
IndexTTS-2.5 `a2bb4d84…`.

## Measurements (RTX 5070 Ti Laptop, 12 GB, shared)

Through the real parent and child; child peak = `torch.cuda.max_memory_reserved`
reported by the child (other processes excluded).

| Model | Reference | Peak | First clip | Later lines |
| --- | --- | --- | --- | --- |
| Chatterbox-Turbo | synthetic / creator | 3.4 / 3.2 GiB | 52.3 / 57.9 s | 1.14 / 1.21 s |
| Chatterbox (English) | synthetic / creator | 3.5–3.6 GiB | 48.2 / 48.6 s | 2.35 / 3.06 s |
| Qwen3-TTS 1.7B Base | synthetic / creator | 4.7 / 4.3 GiB | 62.4 / 63.6 s | 1.56 / 2.09 s |
| IndexTTS-2.5 | creator | 5.8 GiB | 114.4 s | 3.64 s |
| Qwen3-TTS 1.7B CustomVoice | stock Ryan (10 deliveries) / Ono Anna (Japanese) | 4.3 / 4.2 GiB | 43.1 / 31.1 s | 9.14 s |

GPU contention with a background-image job (Animagine XL, 2 images,
`contention.jsonl`): voice alone 58.4 s (peak 3.15 GiB, GPU); image alone 74.4 s
(card 8.5 GiB); both, voice queued 20 s after the image: image 58.6 s, voice 64.6 s,
both on the GPU, card peak 11.4 of 11.9 GiB. Admission thresholds are now the
measured peaks plus headroom (Turbo 3.5 GiB, Chatterbox 4.5, Qwen3 5.5, IndexTTS 7.0);
below them Chatterbox and Qwen3 speak on the CPU (Turbo: 59 s for load plus two lines)
and IndexTTS-2.5 fails clearly with `gpu_busy`.
Seen live: a Japanese IndexTTS-2.5 run started while 10.4 GiB were free; by the time
the child loaded, the user's own Studio was generating images (9.4 GiB), and the job
refused with `gpu_busy` instead of oversubscribing the card.

Watermark: Perth's detector reads 1.0 on Turbo and Chatterbox clips (after the
float→16-bit WAV conversion) and 0.0 on the Kokoro reference.

## Live qualification (QA Studio from the branch, database `flint_m39_qa`)

The QA Studio ran from the worktree on 8111/5202/5183 with its own queues, a 0.7.0
builder (`sha256:bd84cef6…`, toolchain `c33df303…`, prepared from LF sources) and a
0.7.0 playtest build. The user's Studio (8101/5192/5173) and the shared database were
not touched.

1. **#175** Assets → Voice references showed the private group to a member. An upload
   through the real file input (a 44.1 kHz WAV) was converted to 24 kHz, saved with the
   consent form and listed. The creator's own 9.5 s recording (stereo 48 kHz) was added
   as "this is my voice" through the API with the creator's confirmation.
2. **#176** Mira's voice = Chatterbox-Turbo cloning the creator's reference. "Generate 3
   missing voices" produced the scene's full lines and the vocalization on the GPU
   (peak 3.1 GiB) with provenance (model, MIT license, PerTh, reference hash, consent
   `self`, delivery, device). Clips were approved and bound; revision 4's NOTICES credit
   the model and contain no reference data; the playtest loaded; the release (runtime
   0.7.0) built, and its exported web game played `calm`, `angry` and `laugh` clips
   (`voice_playing: true` each). A byte search of both artifacts (16 high-entropy probes
   of the reference PCM plus its hash) found no reference data.
3. **#177** The script editor defaulted the angry-expression line to "Angry · from the
   expression · Chatterbox-Turbo only approximates angry", listed deliveries Turbo
   cannot do as "(not with Chatterbox-Turbo)", stored a whisper override and a chuckle
   sound, and the job carried exactly those deliveries.
   With a Kokoro voice, the same lines read "Kokoro-82M cannot speak a line angry; this
   clip will sound neutral" (and the same for the chuckle sound), with nine of ten
   deliveries marked as unsupported; the IndexTTS-2.5 line marked only whisper.
4. **#178** The catalog offered IndexTTS-2.5 as not accepted with `player_terms`.
   Choosing it opened the license dialog (summary, duties, full bilingual agreement);
   with the user's permission the QA acceptance was recorded. The Old keeper's line
   (afraid) was generated with IndexTTS-2.5 (peak 5.7 GiB); revision 7's NOTICES carry
   the clip's bilibili notice, the full agreement (license hash `9edf1e20…`) and the
   player-terms block; the Releases dialog listed "bilibili … caused by line keeper".
   The playtest opened on the license screen. The release's web game opened on the
   license screen with the story, voice and toolbar held; "I agree" started the first
   clip; a reload did not ask again; the IndexTTS clip played on its line; License in
   the menu reopened the terms for rereading.

## Checks

To be completed with the final command list.

## Limits and follow-ups

- First clips take 50–115 s (imports and model load); a warm model server would cut
  this but is not part of this milestone.
- Chatterbox's emotions are approximate (one expressiveness knob); Turbo uses style
  tags; Qwen3 cloning takes no instructions; IndexTTS-2.5 is GPU-only.
- The game shows the English agreement; the Chinese text (which prevails) is in
  NOTICES.txt because the runtime font has no CJK glyphs.
- The browser microphone path was exercised by code and the shared upload pipeline;
  the creator supplied a recording file rather than recording in the Studio.
