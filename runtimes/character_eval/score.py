"""Pinned ONNX CPU scorer. No hub client, GPU provider, or runtime download.

Preprocessing follows MIT-licensed deepghs/imgutils at
46df848dc4d20ac93f4919a40e2636d5f7c19766; see THIRD_PARTY.md.
The original WD checkpoint is used, not imgutils' embedding-augmented mirror.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np
import onnxruntime as ort
import psutil
from PIL import Image, ImageDraw, ImageOps
from PIL import __version__ as pillow_version

from flint_graph.narrative.character_bench import clothing_overlap

PINS = {
    "ccip": "0c2030c66d49d5e41f00d2c3adb610efad916010d1802914b8bdbe3afa651508",
    "wd14": "7e95e8ddb226fe53d512698f9589cbe37d7d1a26f53a78f63fa31010e4ddccf5",
}
CCIP_MODELS = ("ccip-caformer-24-randaug-pruned", "ccip-caformer_b36-24")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def local_file(root, name):
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or any(
        p.is_symlink() for p in (path, *path.parents) if p != root.parent
    ):
        raise ValueError("path escapes fixture root")
    if not path.is_file():
        raise ValueError("fixture file missing")
    return path


def verified_models(root):
    for name, expected in PINS.items():
        folder = root / name
        manifest = folder / "flintgraph-download.json"
        if digest(manifest) != expected:
            raise ValueError("unreviewed model manifest")
        info = json.loads(manifest.read_text())
        for name, entry in info["files"].items():
            path = local_file(folder, name)
            if digest(path) != entry["sha256"]:
                raise ValueError("model hash mismatch")


def session(path):
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def rgb(image):
    flat = Image.new("RGBA", image.size, "white")
    flat.alpha_composite(image.convert("RGBA"))
    return flat.convert("RGB")


class Scorer:
    def __init__(self, root):
        verified_models(root)
        self.ccip = {
            name: (
                session(root / "ccip" / name / "model_feat.onnx"),
                session(root / "ccip" / name / "model_metrics.onnx"),
            )
            for name in CCIP_MODELS
        }
        self.wd = session(root / "wd14/model.onnx")
        with (root / "wd14/selected_tags.csv").open(encoding="utf-8") as stream:
            self.tags = list(csv.DictReader(stream))

    def extract(self, image):
        image = rgb(image)
        data = np.asarray(image.resize((384, 384), Image.Resampling.BILINEAR), np.float32)
        data = data.transpose(2, 0, 1) / 255
        mean = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)[:, None, None]
        std = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)[:, None, None]
        batch = ((data - mean) / std)[None].astype(np.float32)
        features = {
            name: feature.run(["output"], {"input": batch})[0][0]
            for name, (feature, _) in self.ccip.items()
        }
        size = self.wd.get_inputs()[0].shape[1]
        side = max(image.size)
        square = Image.new("RGB", (side, side), "white")
        square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
        pixels = np.asarray(square.resize((size, size), Image.Resampling.BICUBIC), np.float32)
        probabilities = self.wd.run(None, {self.wd.get_inputs()[0].name: pixels[None, :, :, ::-1]})[
            0
        ][0]
        general, ratings = {}, {}
        for tag, value in zip(self.tags, probabilities, strict=True):
            if tag["category"] == "9":
                ratings[tag["name"]] = float(value)
            elif tag["category"] == "0" and value >= 0.05:
                general[tag["name"]] = float(value)
        return features, general, ratings

    def difference(self, a, b):
        return {
            name: float(metric.run(["output"], {"input": np.stack([a[name], b[name]])})[0][0, 1])
            for name, (_, metric) in self.ccip.items()
        }


def load_image(root, entry):
    path = local_file(root, entry["image"])
    if digest(path) != entry["sha256"]:
        raise ValueError("fixture hash mismatch")
    with Image.open(path) as image:
        image.load()
        if "box" in entry:
            box = entry["box"]
            if not (
                len(box) == 4
                and 0 <= box[0] < box[2] <= image.width
                and 0 <= box[1] < box[3] <= image.height
            ):
                raise ValueError("invalid character crop")
            return rgb(image.crop(tuple(box)))
        return rgb(image)


def score(dataset_file, run_file, models, output):
    dataset = json.loads(dataset_file.read_text(encoding="utf-8"))
    run = json.loads(run_file.read_text(encoding="utf-8"))
    if run["dataset_sha256"] != canonical(dataset):
        raise ValueError("incompatible dataset")
    expected = {c["id"] for c in dataset["cases"]}
    if len(expected) != len(dataset["cases"]) or expected != {c["id"] for c in run["images"]}:
        raise ValueError("incomplete or duplicate cases")
    if len(run["images"]) != len(expected):
        raise ValueError("duplicate output cases")
    # Verify all inputs before expensive model initialization or creating output.
    refs = {
        key: load_image(dataset_file.parent, value) for key, value in dataset["references"].items()
    }
    generated = {entry["id"]: load_image(run_file.parent, entry) for entry in run["images"]}
    if output.exists():
        raise ValueError("output must be new; reviewed runs are immutable")
    started = time.monotonic()
    scorer = Scorer(models)
    load_seconds = time.monotonic() - started
    ref_scores = {key: scorer.extract(image) for key, image in refs.items()}
    rows = []
    for case in dataset["cases"]:
        began = time.monotonic()
        features, tags, ratings = scorer.extract(generated[case["id"]])
        ref_features, ref_tags, _ = ref_scores[case["character"]]
        rows.append(
            {
                "id": case["id"],
                "identity_distance": scorer.difference(ref_features, features),
                "identity_by_reference": {
                    key: scorer.difference(reference[0], features)
                    for key, reference in ref_scores.items()
                },
                "clothing_by_reference_v1": {
                    key: clothing_overlap(reference[1], tags)
                    for key, reference in ref_scores.items()
                },
                "clothing_overlap_v1": clothing_overlap(ref_tags, tags),
                "general_tags": tags,
                "rating_tags_never_prompt": ratings,
                "seconds": time.monotonic() - began,
            }
        )
    result = {
        "schema": 1,
        "dataset_sha256": canonical(dataset),
        "scorer_sha256": canonical(
            {
                "models": PINS,
                "scorer_source": digest(Path(__file__)),
                "contract_source": digest(
                    Path(__file__).resolve().parents[2]
                    / "src/flint_graph/narrative/character_bench.py"
                ),
                "provider": "CPUExecutionProvider",
                "threads": 4,
                "runtime_versions": {
                    "onnxruntime": ort.__version__,
                    "numpy": np.__version__,
                    "pillow": pillow_version,
                    "python": list(sys.version_info[:3]),
                },
            }
        ),
        "run": run,
        "load_seconds": load_seconds,
        "rows": rows,
        "cpu_rss_bytes": psutil.Process().memory_info().rss,
        "versions": {
            "onnxruntime": ort.__version__,
            "numpy": np.__version__,
            "pillow": pillow_version,
            "python": list(sys.version_info[:3]),
        },
        "references": {
            key: {"general_tags": tags, "rating_tags_never_prompt": ratings}
            for key, (_, tags, ratings) in ref_scores.items()
        },
    }
    output.mkdir(parents=True)
    (output / "scores.json").write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
    )
    # Every output is adjacent to its own reference, with scores and its case ID.
    cell_w, cell_h = 440, 340
    sheet = Image.new("RGB", (cell_w * 3, cell_h * ((len(rows) + 2) // 3)), "#f4f4f4")
    draw = ImageDraw.Draw(sheet)
    for i, (case, row) in enumerate(zip(dataset["cases"], rows, strict=True)):
        x, y = i % 3 * cell_w, i // 3 * cell_h
        for j, image in enumerate((refs[case["character"]], generated[case["id"]])):
            thumb = ImageOps.contain(image, (210, 270))
            sheet.paste(thumb, (x + j * 220, y + 20))
        draw.text((x + 5, y + 3), case["id"], fill="black")
        small, big = [row["identity_distance"][name] for name in CCIP_MODELS]
        outfit = row["clothing_overlap_v1"]
        draw.text(
            (x + 5, y + 294), f"CCIP small {small:.3f} / b36 {big:.3f} (lower better)", fill="black"
        )
        draw.text(
            (x + 5, y + 313),
            f"Clothing {outfit:.3f}" if outfit is not None else "Clothing unknown",
            fill="black",
        )
    sheet.save(output / "contact-sheet.jpg", quality=90)
    return {
        "cases": len(rows),
        "seconds": time.monotonic() - started,
        "rss_mib": result["cpu_rss_bytes"] / 2**20,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(score(args.dataset, args.run, args.models, args.out)))
