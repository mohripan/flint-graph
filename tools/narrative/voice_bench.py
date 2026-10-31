"""Measure a local voice model through the real parent and child (#174, ADR 0045).

    uv run python tools/narrative/voice_bench.py --model chatterbox-turbo \
        --model-dir notes/models/chatterbox-turbo --runtime runtimes/voicegen-chatterbox \
        --reference notes/voice-eval/reference.wav --out notes/voice-eval/turbo

Speaks the fixed evaluation lines (one per delivery the model supports, plus a
vocalization) with the reference voice or a stock voice, keeps every clip for
listening and rating, and writes ``bench.json`` with the device, the time to the
first clip (model load plus one line), seconds per later line and the peak of
NVML-reported GPU memory above the idle baseline. The manifest is verified first.
"""

import argparse
import asyncio
import hashlib
import itertools
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from flint_graph.infrastructure.narrative_imagegen import runtime_paths
from flint_graph.infrastructure.narrative_voicegen import (
    LocalEngineVoiceGenerator,
    ReferenceInput,
    VoiceItem,
    VoiceRequest,
    verify_engine_model,
)
from flint_graph.narrative.voice_models import MODELS, Delivery
from flint_graph.narrative.voice_references import inspect_reference

LINES = {
    "neutral": "The ferry leaves at dawn, so pack only what you can carry.",
    "happy": "You came back! I knew you would, I just knew it!",
    "angry": "You promised me. You stood right there and promised me!",
    "sad": "I kept the lantern lit every night, but nobody came home.",
    "afraid": "Did you hear that? Something is moving under the pier.",
    "surprised": "Wait, the letter was from you? All this time?",
    "whisper": "Keep your voice down. The guards change shifts at midnight.",
    "shout": "Get away from the edge! The rocks are giving way!",
    "dramatic": "And so the last lighthouse keeper turned to face the storm alone.",
    "tender": "It's all right. I'm here now, and I'm not leaving.",
}
JAPANESE = "港の灯りがまたともった。誰かがまだ帰りを待っているんだ。"


class Sampler(threading.Thread):
    """GPU memory in use (``nvidia-smi``, the same NVML figure), every 200 ms."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.baseline = self.used()
        self.peak = self.baseline
        self.running = True

    @staticmethod
    def used() -> int:
        query = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
        output = subprocess.run(query, capture_output=True, text=True, check=True).stdout
        return int(output.splitlines()[0]) * 2**20

    def run(self) -> None:
        while self.running:
            self.peak = max(self.peak, self.used())
            time.sleep(0.2)


def items_for(model_id: str, language: str) -> list[VoiceItem]:
    spec = MODELS[model_id]
    if language == "ja":
        return [VoiceItem(JAPANESE, "full")]
    items = [
        VoiceItem(text, "full", Delivery(emotion, 0.75 if emotion != "neutral" else 0.5))
        for emotion, text in LINES.items()
        if emotion in spec.deliveries
    ]
    tag = "laugh" if "laugh" in spec.tags else None
    items.append(VoiceItem("fufu", "vocalization", Delivery("neutral", 0.5, tag)))
    return items


def bench(args: argparse.Namespace) -> dict:
    spec = MODELS[args.model]
    manifest = hashlib.sha256((args.model_dir / "flintgraph-download.json").read_bytes())
    identity = verify_engine_model(args.model_dir, manifest.hexdigest(), spec)
    python, script = runtime_paths(args.runtime.resolve())
    cache = Path(args.cuda_cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    generator = LocalEngineVoiceGenerator(
        spec=spec,
        python=python,
        script=script,
        model_dir=args.model_dir.resolve(),
        model=identity,
        deadline_seconds=args.deadline,
        device=args.device,
        cuda_cache=cache,
    )
    reference = None
    if spec.cloning:
        audio = inspect_reference(args.reference.read_bytes())
        reference = ReferenceInput(audio.data, audio.sha256, args.transcript or None)
    items = items_for(args.model, args.language)
    request = VoiceRequest(
        voice=None if spec.cloning else args.voice,
        speed=1.0,
        seed=args.seed,
        items=tuple(items),
        model=args.model,
        reference=reference,
        language=args.language,
    )
    sampler = Sampler()
    sampler.start()
    stamps: list[float] = []
    started = time.perf_counter()

    async def progress(done: int) -> None:
        stamps.append(time.perf_counter() - started)

    try:
        result = asyncio.run(generator.generate(request, on_progress=progress))
    finally:
        sampler.running = False
        sampler.join()
    total = time.perf_counter() - started
    args.out.mkdir(parents=True, exist_ok=True)
    clips = []
    for item, clip in zip(items, result.clips, strict=True):
        name = item.delivery.emotion if item.mode == "full" and item.delivery else "vocalization"
        if args.language != "en":
            name = args.language
        path = args.out / f"{args.model}-{name}.wav"
        path.write_bytes(clip.data)
        clips.append({"file": path.name, "delivery": name, "seconds": clip.duration_ms / 1000})
    per_line = [later - earlier for earlier, later in itertools.pairwise(stamps)]
    audio_seconds = sum(clip["seconds"] for clip in clips)
    report = {
        "model": args.model,
        "repo": f"{spec.repo}@{spec.revision}",
        "language": args.language,
        "runtime": result.runtime,
        "devices": sorted({clip.device for clip in result.clips}),
        "lines": len(items),
        "first_clip_seconds": round(stamps[0], 2),
        "seconds_per_later_line": round(sum(per_line) / len(per_line), 2) if per_line else None,
        "total_seconds": round(total, 2),
        "audio_seconds": round(audio_seconds, 2),
        "real_time_factor": round(
            (total - stamps[0]) / max(audio_seconds - clips[0]["seconds"], 0.01), 3
        )
        if per_line
        else None,
        "child_peak_reserved_mib": int(result.runtime.get("peak_vram_mib", "0")),
        "gpu_baseline_mib": sampler.baseline // 2**20,
        "gpu_peak_above_baseline_mib": (sampler.peak - sampler.baseline) // 2**20,
        "clips": clips,
    }
    (args.out / f"{args.model}-{args.language}-bench.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, choices=sorted(set(MODELS) - {"kokoro-82m"}))
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--transcript", default="")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="auto", choices=("auto", "cpu"))
    parser.add_argument("--seed", type=int, default=20261101)
    parser.add_argument("--deadline", type=int, default=1800)
    parser.add_argument("--cuda-cache", default="notes/voice-eval/cuda-cache")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(bench(args), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
