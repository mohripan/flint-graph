# Character creation with local portrait generation (#170, #128 foundation)

The user asked for character creation: a character was only a name, and they wanted
to describe one and get an image. Delivered per the
[design](../superpowers/specs/2026-10-31-character-creation-design.md) and
[ADR 0039](../adr/0039-local-gpu-image-generation-in-an-isolated-child.md):

- **Character sheet.** The Characters tab is now a list with portrait avatars plus a
  sheet: name, appearance, character type and framing. The description autosaves as
  editor metadata (migration 0022, optimistic versions, 409 on stale saves).
- **Generate portraits.** A durable job renders four candidates locally with
  Animagine XL 4.0. The sheet shows live progress ("Loading the model…", "Generated 2
  of 4…") and offers Cancel. Each image records its model, revision, exact prompt,
  seed, settings, runtime and license.
- **Review.** "Use as portrait" approves a candidate, "Discard" hides one, and
  clicking an image opens it at full size. The chosen portrait appears on the
  character list and beside that speaker's lines in the script editor.
- **Isolation.** The GPU work runs in a separate child from `runtimes/imagegen`'s
  own lock (PyTorch 2.11 + CUDA 12.8, diffusers 0.42.1). It has a minimal
  environment, runs offline, loads safetensors only and has a watchdog. Its outputs
  must pass the strict PNG validator and exact dimension checks before storage.
- **Studio.** The Scenes tab now appears only on phones (on wide screens it showed
  the same view as Write). The Characters tab hides the scene rail and adapts to the
  width it actually gets.

The story format is unchanged: v1 characters carry only a name. Portraits therefore
do not appear in playtests or releases yet. That needs the asset export binding
(#128), which is next.

## Measurements

| Case | Result |
| --- | --- |
| Model load / first image / later images | 11.9 s / 27.9 s / ~11 s (832×1216, 28 steps) |
| Peak device memory | 7.7 GB with tiled VAE (9.5 GB untiled) |
| Four portraits, GPU free | 79.5 s wall |
| Four portraits, Ollama's 12B model resident | 89 s via API, 108 s from the browser (busy refusal, Ollama unload, retry) |
| Same job before the NVML check | ~115 s per image: Windows reported 10.8 GB free while 3.9 GB was free, and spilled into shared memory |

## Findings fixed during qualification

- `cudaMemGetInfo` on Windows (WDDM) counts shared memory. The busy check now uses
  NVML (`nvidia-ml-py`).
- PyTorch names caches with `getpass.getuser()`. Without `USERNAME` in the child's
  minimal environment, the diffusers import fails with "Artifact of type=precompile
  already registered". `USERNAME`/`USER`/`LOGNAME` are passed through (not secrets).
- When a child floods stdout and the reader stops, asyncio's `Process.wait()` never
  returns, because a paused pipe never reaches EOF. The parent now kills the child
  and drains with `communicate()`.
- At a 1,096 px window, the character sheet got 137 px beside the scene rail. The
  rail is now hidden on Characters, and container queries stack the layout.

## Verification

- Unit: prompt builder (8), child parent against a scripted fake child: protocol,
  watchdog, flooding, bad PNG/size/seed/inventory, model pin (10).
- Integration: profiles, roles, foreign/archived projects, job admission,
  idempotency, limits, relay, fenced execution, storage verification, approval,
  discard guards, cancellation, GPU contention and Ollama release, recovery. 16 passed
  on SQLite plus the owned PostgreSQL.
- Live on the owned Temporal: IDs-only history, cancellation stopping generation, and
  a real GPU job with verified bytes (3 passed).
- Live stack: owned API → outbox → image worker → real child on the RTX 5070 Ti →
  MinIO → hash-verified content. In the browser: describe, autosave, generate,
  progress, choose, discard, full-size view, speaker avatar, reload persistence and
  375×812 layout.
- Frontend: `npm test` with the character model (2 new), `npm run typecheck` and
  `npm run build`.
