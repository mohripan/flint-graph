"""Whether generation will have to wait for the GPU (ADR 0069)."""

from fastapi import APIRouter
from pydantic import BaseModel

from flint_graph.api.dependencies import CurrentUserDep, SessionDep, SettingsDep
from flint_graph.application.services.narrative_gpu import read_gpu_view

router = APIRouter(prefix="/v1/narrative", tags=["narrative"])


class GpuStatusResponse(BaseModel):
    state: str
    detail: str | None
    wake_seconds: int | None
    waiting: list[str]


@router.get("/gpu", response_model=GpuStatusResponse)
async def gpu_status_endpoint(
    _: CurrentUserDep, session: SessionDep, settings: SettingsDep
) -> GpuStatusResponse:
    view = await read_gpu_view(session, settings)
    return GpuStatusResponse(
        state=view.state,
        detail=view.detail,
        wake_seconds=view.wake_seconds,
        waiting=list(view.waiting),
    )
