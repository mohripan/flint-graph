# Generated music

[ADR 0067](../adr/0067-generated-music.md). Off by default.

## Turning it on

1. Download the model with `tools/narrative/fetch_model.py`, or use the verified copy in
   `notes/models/ace-step-v1-3.5b`.
2. Install the child's environment:

   ```powershell
   cd runtimes/musicgen
   uv sync
   ```

3. Add to `studio.local.env`, and add `music` to `STUDIO_SERVICES`:

   ```text
   FLINT_GRAPH_NARRATIVE_MUSIC_GENERATION_ENABLED=true
   FLINT_GRAPH_NARRATIVE_MUSIC_RUNTIME_DIR=C:/path/to/flint-graph/runtimes/musicgen
   FLINT_GRAPH_NARRATIVE_MUSIC_MODEL_DIR=C:/path/to/models/ace-step-v1-3.5b
   FLINT_GRAPH_NARRATIVE_MUSIC_MODEL_MANIFEST_SHA256=<sha256 of flintgraph-download.json in that folder>
   FLINT_GRAPH_NARRATIVE_MUSIC_RELEASE_OLLAMA_MODEL=<the assistant's model, on a shared GPU>
   ```

The assistant worker reads the same settings, so it offers music once they are set and it restarts.

## What to expect

On a 12 GB RTX 5070 Ti, a 30 s track took 73 s end to end, peaking near 6.8 GiB reserved. Ogg output
is about 15 KB/s.

| Failure | Meaning |
| --- | --- |
| `gpu_busy` | Under 7 GiB free. Try again when other GPU work has finished |
| `gpu_unavailable` | No GPU; this model has no CPU path here |
| `generation_timeout` | Past `NARRATIVE_MUSIC_JOB_DEADLINE_SECONDS` (900 by default) |
| `invalid_output` | The child wrote something the parent will not accept; nothing is published |
| `generation_failed` | The child failed. Its stderr is discarded, so rerun it by hand with the job's input |

The child's stderr is dropped on purpose, because libraries print prompts and paths. To debug, run
`generate.py` from a scratch copy with the worker's `_environment`, not your own shell: the first real
failure here only happened in that minimal environment.

## Limits

- Musical quality has not been judged by a person.
- It cannot sing or make sound effects.
- A track is about 2 s shorter than asked, because its loop point is crossfaded.
