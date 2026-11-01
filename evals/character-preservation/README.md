# Character-preservation bench

Offline M40 research for #180–#186. These original synthetic adult characters are
agent-selected fixtures, **not creator-approved Studio assets or training data**.
No real Studio project is read. See the [research report](../../docs/reports/2026-11-01-character-preservation.md)
for measured results, limitations and remaining qualification.

`pilot-v1/dataset.json` freezes two characters × four requests (back, sitting,
crossed arms, holding a flower) × seeds 101/102: 16 cases per method. It includes
exact reference hashes, original generation provenance, full/short conditioning,
dimensions, sampling settings and manually drawn pose-control hashes. No prompt
exceeds the SDXL tokenizer's 77-token limit. The two source images were generated
with Animagine XL 4.0, without an existing character/artist name. The pose controls
are original drawings; no OpenPose detector/code or third-party pose photo is used.

The lab is separate from Studio workers. Default runtime dependencies, database,
story format and Godot version do not change. Weights, caches and full generated
outputs go under ignored `notes/`, never into games. Only reference fixtures,
reviewed evidence sheets and machine-readable experimental results are retained.

## Prepare offline models

```powershell
uv sync --project runtimes/character_eval
uv sync --project runtimes/character_lab
```

`model-manifests/` retains public repository/revision/license/file hashes for each
tested checkpoint. They contain no credentials. To prepare a model from one of
these reviewed manifests using the existing bounded-file fetcher:

```powershell
$pin=Get-Content evals/character-preservation/model-manifests/ccip.json | ConvertFrom-Json
$fetchArgs=@('run','python','tools/narrative/fetch_model.py','--repo',$pin.repo,'--revision',$pin.revision,'--license',$pin.license,'--out','notes/models/ccip')
foreach($name in $pin.files.PSObject.Properties.Name) { $fetchArgs+=@('--file',$name) }
uv @fetchArgs
Copy-Item evals/character-preservation/model-manifests/ccip.json notes/models/ccip/flintgraph-download.json
```

Repeat for `wd14`; GPU methods additionally need `animagine-xl-4.0`, `ip-adapter`
and optionally `controlnet-openpose-sdxl`/`ip-face`. Respect each independent model
license. CCIP's exact OpenRAIL variant is unresolved, so this is internal research,
not a production adoption approval. The scorer checks the reviewed manifest bytes
and every downloaded file before CPU inference. Inference has no hub client.
After fetching each model, copy its reviewed manifest verbatim as above: the
generic fetcher's JSON formatting can differ by platform. Every downloaded file
is still checked against the reviewed manifest. Git preserves these manifest and
score/review bytes because their SHA-256 identities include line endings.

## Generate and score

Use a new output directory for every run. Admission requires 10 GiB dedicated
free memory for ordinary SDXL methods, 11 GiB for cached ControlNet or klein,
and 11.6 GiB for the uncached ControlNet baseline. It refuses a busy GPU and
never unloads another program or restarts
services. Run GPU methods sequentially, not in parallel on the shared card.

```powershell
runtimes/character_lab/.venv/Scripts/python.exe runtimes/character_lab/generate.py --dataset evals/character-preservation/pilot-v1/dataset.json --models notes/models --method locked --out notes/research/locked
runtimes/character_eval/.venv/Scripts/python.exe runtimes/character_eval/score.py --dataset evals/character-preservation/pilot-v1/dataset.json --run notes/research/locked/run.json --models notes/models --out notes/research/locked-scores
```

Methods: `text` (full look text only), `ip` (IP-Adapter Plus without garment text),
`locked` (Plus with the fixture's manually reviewed look description), `multi`
(same source at two scales, not independent views), `face` (Plus Face with a fixed
head/upper-body crop; add `--face-models notes/models/ip-face`), `img2img` (Plus and
full-image img2img strength 0.7), and `control` (Plus plus pose ControlNet 0.8).
The retained ablations add `--img2img-strength 0.95` (`img2img-950`) and
`--cache-text-embeddings` on `control` (`control-cached`). The latter releases
both text encoders before moving the UNet to the GPU; all 16 output PNG hashes
match the uncached baseline. The uncached run nearly fills this card and is a
measurement baseline, not the recommended worker configuration.
All use the same case seeds/size; parameters are recorded, including inactive
parameters for context. Every image records its byte hash, time and Torch peak
allocation; device use after inference is separately named, not a measured global
VRAM peak. Failed/partial runs cannot pass the scorer's complete-coverage check.

`edit.py` is the separate FLUX.2 klein experiment. It records its model-specific
English editing instructions, 4 distilled steps and bf16 precision. The frozen
semantic requests/seeds/dimensions match; identical seeds across architectures do
not imply identical latent noise. It encodes prompts first, releases the encoder,
then loads the transformer/VAE. Supply the reviewed download manifest SHA-256
explicitly with `--manifest-sha256` and an otherwise new output directory.
It also requires 9 GiB available host RAM. Prepare the pinned `flux2-klein-4b`
manifest with the same fetch/copy procedure. Example:

```powershell
$editPin=(Get-FileHash evals/character-preservation/model-manifests/flux2-klein-4b.json -Algorithm SHA256).Hash.ToLower()
runtimes/character_lab/.venv/Scripts/python.exe runtimes/character_lab/edit.py --dataset evals/character-preservation/pilot-v1/dataset.json --models notes/models/flux2-klein-4b --manifest-sha256 $editPin --out notes/research/klein
```

`pair-v1` tests two references with two seeds. `pair.py` runs the unchanged
production IP-Adapter child (`--models` names the parent of the verified base
and adapter directories).
`edit.py --dataset evals/character-preservation/pair-v1/dataset.json` tests klein
with two references; add `--background-context` for its third-image ablation.
Fixed per-actor half-image crops are diagnostic only: inspect the complete scene
for count, assignment and overlap first. Pair scores are excluded from fitting.

Scoring writes `scores.json` and a reference/output contact sheet. Identity uses
both small and b36 CCIP models with their learned metric, not cosine distance.
Clothing uses taxonomy v1 at 0.35 confidence, with unknown preserved. Raw general
and rating probabilities are separate; predicted character-name tags are omitted.
Per-reference contrast scores support explicit negative-pair analysis. No person
detector is used: each pilot image contains one intended character. The image
loader supports explicit verified crops for later multi-person datasets, which
still need detector/assignment/count qualification.

## Compare and review

```powershell
runtimes/character_eval/.venv/Scripts/python.exe runtimes/character_eval/compare.py --baseline notes/research/ip-scores/scores.json --candidate notes/research/locked-scores/scores.json --out notes/research/ip-vs-locked.json
runtimes/character_eval/.venv/Scripts/python.exe runtimes/character_eval/review.py --scores notes/research/locked-scores/scores.json --out notes/research/locked-review.json
```

Comparison refuses changed dataset/scorer hashes or partial case coverage. Negative
CCIP difference means closer identity, not approval or pose success. It never
overwrites a baseline. The blank review starts `unreviewed`, with all labels
unknown. After examining the actual images, explicitly record reviewer identity,
`review_kind` (`agent` or `creator`), and independent identity/clothes/pose labels
(`same`, `drifted`, `unknown`) plus notes. Do not relabel agent judgments as creator
reviews. A review pins the exact score file, which pins all candidate/reference
bytes; changing a case or run requires a new review.

```powershell
runtimes/character_eval/.venv/Scripts/python.exe runtimes/character_eval/review.py --scores notes/research/locked-scores/scores.json --ratings notes/research/locked-review.json --out notes/research/locked-fit.json
```

Identity and clothing fit independently. Missing clothing scores stay unknown even
if reviewed. A fit needs both labelled classes; otherwise it reports unavailable.
The result always says `production_ready: false`. Use held-out characters, outfits
and seeds, not the fit-set F1, to qualify a production threshold.

For pooled fitting, `calibration.py` accepts repeated `--entry SCORES REVIEW
DATASET`, plus `--review-kind agent|creator --out NEW_FILE`. It verifies each
review's exact score hash, deduplicates identical reference/candidate/crop pairs,
rejects conflicting labels and multi-person data, and reports confusion matrices
at garment confidence 0.15/0.25/0.35/0.5. `results/agent-fit.json` is exploratory:
at the usual 0.35 confidence its F1-optimal fit falsely accepts **14 of 15**
agent-labelled clothing drifts. Do not use it as an approval threshold.

## Recheck the scorer and resource probe

```powershell
uv run pytest tests/unit/test_character_bench.py -q
$env:FLINT_GRAPH_CHARACTER_EVAL_MODELS=(Resolve-Path notes/models).Path
uv run pytest tests/integration/test_character_eval_live.py -q
runtimes/character_lab/.venv/Scripts/python.exe -m unittest discover -s runtimes/character_lab -p test_*.py
```

For full imgutils API parity, prepare the pinned `wd14-parity` mirror as well,
install `uv sync --project runtimes/character_eval --group parity`, then run:

```powershell
runtimes/character_eval/.venv/Scripts/python.exe runtimes/character_eval/parity.py --dataset evals/character-preservation/pilot-v1/dataset.json --models notes/models --cache notes/new-hf-parity --out notes/new-parity.json
runtimes/character_lab/.venv/Scripts/python.exe runtimes/character_lab/memory_probe.py --models notes/models --resolution 768 --steps 6 --out notes/new-memory-768.json
```

Parity seeds a new private local HF cache from already hash-verified files and
calls imgutils 0.19.0 offline. The normal scorer uses the original WD checkpoint;
parity compares its probabilities against imgutils' embedding-augmented mirror.
The LoRA probe performs backward passes on **random tensors only**, with rank 4,
batch 1, gradient checkpointing and an 8-bit optimizer. It saves no weights and
does not establish character/style quality or the required training image count.
Actual training remains conditional on a creator-selected approved dataset.
