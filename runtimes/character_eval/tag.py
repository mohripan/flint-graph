"""Bounded WD14-only CPU child. It never opens CCIP weights or uses a GPU."""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image
from score import PINS, Scorer, canonical, digest, local_file, np, ort, pillow_version, session


class Tagger(Scorer):
    def __init__(self, folder):
        manifest = folder / "flintgraph-download.json"
        if digest(manifest) != PINS["wd14"]:
            raise ValueError("unreviewed tagger manifest")
        for name, entry in json.loads(manifest.read_text())["files"].items():
            if digest(local_file(folder, name)) != entry["sha256"]:
                raise ValueError("tagger model hash mismatch")
        # Reuse the numerically qualified WD preprocessing, with no CCIP sessions.
        self.ccip = {}
        self.wd = session(folder / "model.onnx")
        with (folder / "selected_tags.csv").open(encoding="utf-8") as stream:
            self.tags = list(csv.DictReader(stream))


def tag(folder, image_path):
    if image_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("image too large")
    with Image.open(image_path) as image:
        if image.format != "PNG" or max(image.size) > 2560:
            raise ValueError("bounded PNG required")
        image.load()
        scorer = Tagger(folder)
        _, general, ratings = scorer.extract(image)
    return {
        "model_manifest_sha256": PINS["wd14"],
        "tagger_sha256": canonical(
            {
                "tagger": digest(Path(__file__)),
                "preprocessing": digest(Path(__file__).with_name("score.py")),
                "onnxruntime": ort.__version__,
                "numpy": np.__version__,
                "pillow": pillow_version,
                "python": list(sys.version_info[:3]),
                "provider": "CPUExecutionProvider",
                "threads": 4,
            }
        ),
        "general_tags": general,
        "rating_tags_never_prompt": ratings,
    }


if __name__ == "__main__":
    request = json.loads(sys.stdin.buffer.read(4097))
    if set(request) != {"model_dir", "image"}:
        raise ValueError("invalid tag request")
    print(json.dumps(tag(Path(request["model_dir"]), Path(request["image"])), allow_nan=False))
