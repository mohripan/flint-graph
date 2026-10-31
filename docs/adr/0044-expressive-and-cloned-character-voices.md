# ADR 0044: Expressive and cloned character voices

Date: 2026-11-01. Status: accepted and delivered (M39, tracking #173: #174–#178).
Builds on [ADR 0043](0043-asset-folders-and-line-voices.md).
Delivery: [report](../reports/2026-11-01-expressive-and-cloned-voices.md),
[runbook](../runbooks/narrative-voice-generation.md).

## Context

Kokoro-82M speaks fixed English voices with no delivery control. Creators want a
character to speak in their own voice, or a consenting speaker's, cloned from a
short sample, and lines delivered angry, sad, whispered, shouted or dramatic. The
user decided that creators choose the model per character; that a model whose
license puts duties on generated audio is offered behind a license dialog, with its
duties carried into releases automatically; and that non-commercial weights stay
out. Everything must run locally on the shared 12 GB laptop GPU (RTX 5070 Ti, beside
Animagine XL and Ollama) and fall back or refuse clearly when the card is busy.

## Evaluation (#174)

Licenses were read from the official repositories and model cards
(Hugging Face API card data and the repositories' LICENSE files):

| Family | Code | Weights | Audio duties |
| --- | --- | --- | --- |
| Chatterbox (Resemble AI) | MIT | MIT (`ResembleAI/chatterbox`, `chatterbox-turbo`) | none; every clip carries the PerTh watermark |
| Qwen3-TTS (Alibaba Qwen) | Apache-2.0 | Apache-2.0 (Base, CustomVoice, tokenizer) | none |
| IndexTTS-2.5 (bilibili) | bilibili Model Use License | same agreement | generated audio is a derivative work: notice, agreement, disclaimer, terms for players, no training of other models; free below 100 million MAU or 100 million RMB a year (the Chinese text prevails) |
| IndexTTS2 | bilibili | its pipeline loads `amphion/MaskGCT`'s semantic codec, **CC-BY-NC-4.0** | excluded: non-commercial |
| F5-TTS, XTTS-v2, Fish Speech/OpenAudio | — | non-commercial | excluded |

IndexTTS-2.5's auxiliaries are w2v-BERT 2.0 (MIT), CAM++ (Apache-2.0) and BigVGAN v2
(MIT); its own codec replaces MaskGCT, which is never downloaded or loaded.

Measured through the real parent and child on the shared card, one job per run
(child's peak of reserved memory; first clip includes imports and loading):

| Model | Peak GPU | First clip | Later lines | Notes |
| --- | --- | --- | --- | --- |
| Kokoro-82M (ADR 0043) | < 1 GiB | 8.5 s warm | < 0.1 s | stock English voices |
| Chatterbox-Turbo | 3.1–3.2 GiB | 52–58 s | 1.1–1.2 s | cloning, style tags, sounds |
| Chatterbox (English) | 3.6 GiB | 48 s | 2.4–3.1 s | cloning, exaggeration |
| Qwen3-TTS 1.7B Base | 4.3–4.7 GiB | 62–64 s | 1.6–2.1 s | cloning; no instructions |
| IndexTTS-2.5 | 5.7–5.8 GiB | 114 s | 3.6 s | cloning plus emotion vectors |
| Qwen3-TTS 1.7B CustomVoice | 4.2–4.3 GiB | 31–43 s | 9.1 s | stock voices, instructions |

Creator ratings of the same fixed lines in the creator's own voice are in the
report. Japanese: Qwen3-TTS, Chatterbox Multilingual V3 and IndexTTS-2.5 speak it;
Kokoro and the English Chatterbox models do not.

## Decision

1. **A code registry of models, installed by the operator.** Kokoro-82M stays the
   default. The catalog offers Chatterbox (English), Chatterbox-Turbo, Chatterbox
   Multilingual V3, Qwen3-TTS 1.7B cloning, Qwen3-TTS 1.7B stock voices and
   IndexTTS-2.5 side by side, because they trade speed, memory, languages and kinds
   of control and the creator chooses per character. Each entry fixes the pinned
   repository revision, license text and SHA-256, duties, languages, deliveries,
   sounds, watermark, sample rate and GPU need; settings only name which entries are
   installed (folder, manifest pin, runtime).
2. **Isolation as ADR 0039/0043.** Each family runs in its own `runtimes/voicegen-*`
   child with its own uv lock (CUDA 12.8 PyTorch 2.8), `python -I`, a private folder,
   no credentials, `HF_HUB_OFFLINE` and a watchdog, over protocol 2: the parent writes
   the reference into the private folder, sends per-line controls, checks every clip
   against the model's sample rate and keeps the child's reported peak memory. A
   child uses the GPU only when NVML shows its measured peak plus headroom free;
   otherwise it speaks on the CPU, and the GPU-only IndexTTS-2.5 refuses with
   `gpu_busy`. Seeds are fixed per clip.
3. **Private references with consent (#175).** A 5–30 s sample, normalized like clips,
   saved only with a declaration ("my voice" or "the speaker gave permission") and the
   speaker's name, recorded with the declarer and time. References have their own
   table and object prefix, so no story, package, playtest, release or NOTICES can name
   them; only members read them; deletion removes the audio, blocks jobs and keeps the
   consent record.
4. **Cloned voices (#176).** A character's voice is a model plus a stock voice or a
   reference. Jobs snapshot the model, the reference hash and the consent record;
   clips stay candidates and their provenance names the model, license, reference,
   consent, watermark, delivery, language and device.
5. **Delivery (#177).** Ten deliveries with an intensity, mapped onto each engine by a
   fixed table: Chatterbox exaggeration and CFG weight, Turbo style tags, Qwen3-TTS
   fixed English instructions, IndexTTS-2.5 emotion vectors; sounds (laugh, sigh…) come
   from each model's fixed list. No free text reaches a model as control. Delivery
   defaults from the line's sprite expression and an override is editor metadata.
   **Delivery is not part of story format 2**: runtimes play recorded clips and never
   synthesize, so the four implementations need no new field; provenance keeps what
   each clip was made with.
6. **License duties (#178).** Acceptance is recorded per workspace, user, model and
   license hash, and gates generation. Clip provenance carries the license, so duties
   follow clips. NOTICES are rebuilt on save: any license with duties adds its full
   text, and a license that requires player terms adds a block between two fixed
   marker lines after the generated asset notices. A release lists the licenses it
   carries and the lines that cause them before it is built.
7. **Runtime 0.7.0.** Exported games show the player terms once before play (kept per
   story and terms hash) with a License menu entry to reread them; Studio playtests
   always show them. A shared parser (`player_terms.py`, `player_terms.gd`, the preview
   validator, `stageModel.ts`) passes the same conformance cases; a malformed block is
   refused everywhere.

## Consequences

- Weights are large: about 27 GB for the six models, plus three runtimes of about
  4 GB each. Operators download them explicitly with pinned, hash-verified manifests.
- The first clip of each job pays 50–115 s of loading; later lines take 1–4 s. Batch
  a scene's lines into one job.
- Chatterbox approximates emotions with one expressiveness knob; Turbo approximates
  them with style tags and cannot exaggerate; Qwen3-TTS cloning takes no instructions
  (its stock voices do); IndexTTS-2.5 needs 7 GiB free and does not run on the CPU.
- The runtime font has no CJK glyphs, so games show the English agreement and point to
  the bilingual one in NOTICES.txt.
- Existing Kokoro profiles, jobs, clips, releases and saves keep their meaning
  (migration defaults). Releases built on runtime 0.6.x keep their identity; rebuilding
  needs the 0.7.0 builder image.
- Watermarks are declared per model and verified for Chatterbox clips (PerTh detects
  1.0 on generated clips, 0.0 on Kokoro audio).
