"""Optional isolated CPU tagger; no ONNX/ML dependency in the API environment."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from flint_graph.domain.errors import DomainError, TooManyRequestsError

WD_MANIFEST = "7e95e8ddb226fe53d512698f9589cbe37d7d1a26f53a78f63fa31010e4ddccf5"


def unavailable(
    detail: str = "Tag suggestions are unavailable. You can enter and review the look manually.",
) -> DomainError:
    return DomainError(503, "Tagger unavailable", detail, "look-tagger-unavailable")


class LookTagger:
    def __init__(self, python: str | None, model_dir: str | None) -> None:
        self.python, self.model_dir = python, model_dir
        self.script = Path(__file__).resolve().parents[3] / "runtimes/character_eval/tag.py"
        self.ready = bool(python and model_dir and Path(python).is_file() and self.script.is_file())
        self.model_root = str(Path(model_dir).resolve()) if model_dir else None
        self.capacity = asyncio.Semaphore(1)

    async def tag(self, data: bytes) -> dict[str, Any]:
        if not self.python or not self.ready:
            raise unavailable()
        if self.capacity.locked():
            raise TooManyRequestsError(
                "Image tags are being read. Try again shortly, or enter the look manually."
            )
        # The child sees only this private verified input and the explicit model.
        # Stderr and child paths never become an API error or public log message.
        async with self.capacity:
            with tempfile.TemporaryDirectory(prefix="flint-look-") as temporary:
                root = Path(temporary)
                image = root / "source.png"
                image.write_bytes(data)
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
                }
                env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
                with (
                    (root / "out.json").open("wb") as output,
                    (root / "error.txt").open("wb") as error,
                ):
                    try:
                        process = await asyncio.create_subprocess_exec(
                            self.python,
                            "-I",
                            str(self.script),
                            stdin=asyncio.subprocess.PIPE,
                            stdout=output,
                            stderr=error,
                            cwd=root,
                            env=env,
                        )
                    except OSError:
                        raise unavailable() from None
                    try:
                        await asyncio.wait_for(
                            process.communicate(
                                json.dumps(
                                    {
                                        "model_dir": self.model_root,
                                        "image": str(image),
                                    }
                                ).encode()
                            ),
                            timeout=45,
                        )
                    except (TimeoutError, asyncio.CancelledError) as failure:
                        if process.returncode is None:
                            process.kill()
                        await process.wait()
                        if isinstance(failure, asyncio.CancelledError):
                            raise
                        raise unavailable() from None
                result_path = root / "out.json"
                if process.returncode or result_path.stat().st_size > 2 * 1024 * 1024:
                    raise unavailable()
                try:
                    result = json.loads(result_path.read_bytes())
                    if not isinstance(result, dict):
                        raise ValueError("invalid tagger result")
                    if result["model_manifest_sha256"] != WD_MANIFEST:
                        raise ValueError("wrong model")
                    return result
                except (ValueError, KeyError, TypeError):
                    raise unavailable() from None
