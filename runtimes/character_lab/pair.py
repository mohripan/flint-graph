"""Run the unchanged production image child as the two-character CG baseline.

The fixed half-image crops are experimental annotations, not person detection.
Inspect figure count and crop validity before interpreting per-character scores.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from generate import PINS, canonical, digest, image, verify


def run(args):
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.out.exists() or len(dataset["references"]) != 2:
        raise ValueError("new output and two reference fixtures required")
    for key in ("animagine-xl-4.0", "ip-adapter"):
        verify(args.models / key, PINS[key])
    people = dataset["cases"][0]["participants"]
    if len(people) != 2 or any(case["participants"] != people for case in dataset["cases"]):
        raise ValueError("inconsistent pair participants")
    seeds = list(dict.fromkeys(case["seed"] for case in dataset["cases"]))
    if not 1 <= len(seeds) <= 4:
        raise ValueError("bounded seed count required")
    references = []
    for key in people:
        ref = dataset["references"][key]
        image(args.dataset.parent, ref)
        references.append(
            {"image": str((args.dataset.parent / ref["image"]).resolve()), "sha256": ref["sha256"]}
        )
    args.out.mkdir(parents=True)
    renders = args.out / "render"
    renders.mkdir()
    request = {
        "protocol": 1,
        "model_dir": str((args.models / "animagine-xl-4.0").resolve()),
        "output_dir": str(renders.resolve()),
        "prompt": dataset["scene_prompt"],
        "negative_prompt": dataset["negative_prompt"],
        "width": 1344,
        "height": 768,
        "steps": 28,
        "guidance": 5,
        "seeds": seeds,
        "scene": {
            "adapter": str((args.models / "ip-adapter").resolve()),
            "weight": "sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors",
            "encoder": "models/image_encoder",
            "scale": 0.5,
            "references": references,
        },
    }
    (args.out / "request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    child = Path(__file__).resolve().parents[1] / "imagegen/generate.py"
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(child)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=os.environ | {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        timeout=900,
    )
    (args.out / "child.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("CG child failed; inspect task-owned child.log")
    events = []
    for line in result.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    loaded = next(e for e in events if e.get("event") == "loaded")
    peak = next(e["peak_bytes"] for e in events if e.get("event") == "done")
    frames = {e["seed"]: e for e in events if e.get("event") == "image"}
    rows = []
    for case in dataset["cases"]:
        event = frames[case["seed"]]
        path = renders / event["file"]
        rows.append(
            {
                "id": case["id"],
                "image": path.relative_to(args.out).as_posix(),
                "sha256": digest(path),
                "box": case["box"],
                "seconds": event["seconds"],
                "torch_peak_bytes": peak,
                "device_used_bytes_after": None,
                "crop_origin": "fixed expected region; requires manual count/crop audit",
            }
        )
    metadata = {
        "schema": 1,
        "method": "ip-pair",
        "dataset_sha256": canonical(dataset),
        "model_manifests": {k: PINS[k] for k in ("animagine-xl-4.0", "ip-adapter")},
        "generator_source_sha256": digest(child),
        "wrapper_source_sha256": digest(Path(__file__)),
        "parameters": {
            "steps": 28,
            "guidance": 5,
            "ip_scale": 0.5,
            "image_masks": "left/right halves",
            "text_conditioning": "global",
            "peak_scope": "whole child job",
        },
        "versions": loaded["runtime"],
        "load_seconds": loaded["seconds"],
        "total_seconds": time.monotonic() - started,
        "physical_image_count": len(frames),
        "images": rows,
    }
    (args.out / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "physical_images": len(frames),
                "character_cases": len(rows),
                "seconds": metadata["total_seconds"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())
