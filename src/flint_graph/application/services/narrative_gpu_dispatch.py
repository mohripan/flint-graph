"""GPU work reaches Temporal from the always-on tier, so the GPU machine only executes (ADR 0070).

If GPU workers relay their own outbox rows, a sleeping machine dispatches nothing, and nothing
can ever show up to wake it. Dispatching here means a queued job waits durably in Temporal
while the machine is off.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flint_graph.application.services.narrative_assistant_actions import (
    AssetBytes,
    dispatch_actions,
    reconcile_actions,
)
from flint_graph.application.services.narrative_assistant_relay import (
    AssistantDispatcher,
    recover_stale_turns,
    relay_assistant_batch,
)
from flint_graph.application.services.narrative_image_relay import (
    ImageDispatcher,
    recover_stale_image_jobs,
    relay_image_batch,
)
from flint_graph.application.services.narrative_music_relay import (
    recover_stale_music_jobs,
    relay_music_batch,
)
from flint_graph.application.services.narrative_style_relay import (
    recover_style_jobs,
    relay_style_batch,
)
from flint_graph.application.services.narrative_voice_relay import (
    recover_stale_voice_jobs,
    relay_voice_batch,
)
from flint_graph.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GpuDispatchers:
    """One per kind of GPU work this server runs; a kind it does not run stays None."""

    image: ImageDispatcher | None = None
    pose: ImageDispatcher | None = None
    voice: ImageDispatcher | None = None
    style: ImageDispatcher | None = None
    music: ImageDispatcher | None = None
    assistant: AssistantDispatcher | None = None


Step = tuple[str, Callable[[], Awaitable[int]]]


def _relays(
    factory: async_sessionmaker[AsyncSession], dispatchers: GpuDispatchers, *, recover: bool
) -> list[Step]:
    steps: list[Step] = []
    if (image := dispatchers.image) is not None:
        steps.append(("image", lambda: relay_image_batch(factory, dispatcher=image)))
        if recover:
            steps.append(
                ("image.recover", lambda: recover_stale_image_jobs(factory, dispatcher=image))
            )
    if (pose := dispatchers.pose) is not None:
        steps.append(("pose", lambda: relay_image_batch(factory, dispatcher=pose, poses=True)))
        if recover:
            steps.append(
                (
                    "pose.recover",
                    lambda: recover_stale_image_jobs(factory, dispatcher=pose, poses=True),
                )
            )
    if (voice := dispatchers.voice) is not None:
        steps.append(("voice", lambda: relay_voice_batch(factory, dispatcher=voice)))
        if recover:
            steps.append(
                ("voice.recover", lambda: recover_stale_voice_jobs(factory, dispatcher=voice))
            )
    if (style := dispatchers.style) is not None:
        steps.append(("style", lambda: relay_style_batch(factory, dispatcher=style)))
        if recover:
            steps.append(("style.recover", lambda: recover_style_jobs(factory, dispatcher=style)))
    if (music := dispatchers.music) is not None:
        steps.append(("music", lambda: relay_music_batch(factory, dispatcher=music)))
        if recover:
            steps.append(
                ("music.recover", lambda: recover_stale_music_jobs(factory, dispatcher=music))
            )
    if (assistant := dispatchers.assistant) is not None:
        steps.append(("assistant", lambda: relay_assistant_batch(factory, dispatcher=assistant)))
        if recover:
            steps.append(
                ("assistant.recover", lambda: recover_stale_turns(factory, dispatcher=assistant))
            )
    return steps


async def dispatch_gpu_work(
    factory: async_sessionmaker[AsyncSession],
    *,
    dispatchers: GpuDispatchers,
    settings: Settings,
    store: AssetBytes,
    recover: bool,
) -> dict[str, int]:
    """One pass over every kind, and how much each did.

    Actions come first, so a job they admit is on its queue by the end of the same pass.
    Each step has its own guard: Temporal being away from one queue holds up no other.
    """
    done: dict[str, int] = {}
    steps: list[Step] = [
        ("actions", lambda: dispatch_actions(factory, settings=settings, store=store)),
        ("actions.reconcile", lambda: reconcile_actions(factory)),
        *_relays(factory, dispatchers, recover=recover),
    ]
    for name, step in steps:
        try:
            done[name] = await step()
        except Exception:
            # Raw errors may hold story text; the name of the step is enough to look further.
            logger.warning("gpu dispatch unavailable: %s", name)
    return done
