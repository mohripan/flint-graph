"""Compare the minimal scorer against real imgutils public APIs, fully offline.

Requires `uv sync --project runtimes/character_eval --group parity` and the pinned
embedding-augmented WD mirror. This group is not needed for normal scoring.
"""

import argparse
import json
import os
import shutil
from pathlib import Path

from score import CCIP_MODELS, Scorer, digest, load_image


def seed_cache(cache, repo, source):
    info = json.loads((source / "flintgraph-download.json").read_text())
    folder = cache / "hub" / ("models--" + repo.replace("/", "--"))
    snapshot = folder / "snapshots" / info["revision"]
    for name, entry in info["files"].items():
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if digest(source / name) != entry["sha256"]:
            raise ValueError("parity input hash mismatch")
        shutil.copyfile(source / name, target)
    (folder / "refs").mkdir(exist_ok=True)
    (folder / "refs/main").write_text(info["revision"])


def parity(args):
    if args.cache.exists() or args.out.exists():
        raise ValueError("new cache and receipt required")
    args.cache.mkdir(parents=True)
    seed_cache(args.cache, "deepghs/ccip_onnx", args.models / "ccip")
    seed_cache(args.cache, "SmilingWolf/wd-swinv2-tagger-v3", args.models / "wd14")
    mirror = args.models / "wd14-parity"
    if (
        digest(mirror / "flintgraph-download.json")
        != "e18c64e977aa365ca47c4592aa4a4236ae5e1f4cf29d856e935b937e0a7a3c22"
    ):
        raise ValueError("unreviewed WD parity mirror")
    seed_cache(args.cache, "deepghs/wd14_tagger_with_embeddings", mirror)
    os.environ.update(
        HF_HOME=str(args.cache.resolve()),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
    )
    from imgutils.metrics import ccip_batch_differences
    from imgutils.tagging import get_wd14_tags

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    images = [load_image(args.dataset.parent, value) for value in dataset["references"].values()]
    scorer = Scorer(args.models)
    extracted = [scorer.extract(image) for image in images]
    differences = scorer.difference(extracted[0][0], extracted[1][0])
    errors = {}
    for model in CCIP_MODELS:
        upstream = ccip_batch_differences(images, model=model)
        errors[model] = abs(float(upstream[0, 1]) - differences[model])
    for i, image in enumerate(images):
        ratings, general, _ = get_wd14_tags(
            image,
            model_name="SwinV2_v3",
            general_threshold=0.05,
            character_threshold=1,
            drop_overlap=False,
        )
        minimal_tags, minimal_ratings = extracted[i][1:]
        if minimal_tags.keys() != general.keys():
            raise ValueError("WD tag membership mismatch")
        errors[f"wd14/{i}/general"] = max(abs(v - general[k]) for k, v in minimal_tags.items())
        errors[f"wd14/{i}/ratings"] = max(abs(v - ratings[k]) for k, v in minimal_ratings.items())
    if max(errors.values()) >= 1e-5:
        raise ValueError(f"parity tolerance exceeded: {errors}")
    result = {
        "imgutils": "0.19.0",
        "offline": True,
        "max_absolute_errors": errors,
        "tolerance": 1e-5,
        "reference_count": len(images),
        "passed": True,
        "wd_mirror_manifest_sha256": digest(mirror / "flintgraph-download.json"),
    }
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parity(parser.parse_args())
