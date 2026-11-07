"""The assistant, image and voice workers in one process, for a remote GPU (ADR 0078).

Their models run elsewhere, so these only wait on the network. Sharing a process spares about
200 MB on a small server, where three separate interpreters would take most of what is free. If
one stops, they all stop, and the cluster restarts them together.
"""

import asyncio

from flint_graph.config import Settings, get_settings
from flint_graph.processes import (
    narrative_assistant_worker,
    narrative_image_worker,
    narrative_voice_worker,
)


async def run_workers(settings: Settings | None = None) -> None:
    configured = settings or get_settings()
    if not (
        configured.narrative_remote_gpu_image_url and configured.narrative_remote_gpu_voice_url
    ):
        raise SystemExit("These workers are for a remote GPU; set its image and voice addresses.")
    await asyncio.gather(
        narrative_assistant_worker.run_worker(configured),
        narrative_image_worker.run_worker(configured),
        narrative_voice_worker.run_worker(configured),
    )


def main() -> None:
    try:
        asyncio.run(run_workers())
    except KeyboardInterrupt:
        pass
    except SystemExit:
        raise
    except Exception:
        raise SystemExit("Studio workers failed; verify operator configuration.") from None


if __name__ == "__main__":
    main()
