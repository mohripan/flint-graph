"""Project assistant threads, turns and proposal decisions (ADR 0038).

Requests record intent only; no model runs inside an API request. Live turn
progress is read back from PostgreSQL by sequence, as JSON or server-sent events.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_assistant_schemas import (
    AssistantDecision,
    AssistantImageActionResponse,
    AssistantProposalResponse,
    AssistantProposalSummary,
    AssistantThreadCreate,
    AssistantThreadResponse,
    AssistantTurnCreate,
    AssistantTurnEventResponse,
    AssistantTurnResponse,
)
from flint_graph.api.narrative_character_schemas import ImageJobResponse
from flint_graph.api.narrative_schemas import NarrativeRevisionResponse
from flint_graph.api.routes.narrative import _persist
from flint_graph.api.routes.narrative_characters import job_response
from flint_graph.application.services.narrative_assistant import (
    accept_proposal,
    cancel_turn,
    create_thread,
    get_proposal,
    get_thread,
    list_threads,
    list_turn_events,
    list_turns,
    post_turn,
    reject_proposal,
    turn_status,
)
from flint_graph.application.services.narrative_assistant_events import events_after
from flint_graph.application.services.narrative_assistant_images import action_jobs, start_action
from flint_graph.application.services.narrative_images import get_image_job
from flint_graph.infrastructure.db.models import NarrativeAssistantProposal, NarrativeAssistantTurn
from flint_graph.infrastructure.db.narrative_assistant_models import NarrativeAssistantTurnEvent

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/assistant", tags=["narrative"])

_TERMINAL = ("completed", "failed", "cancelled")
STREAM_POLL_SECONDS = 0.25
STREAM_KEEPALIVE_SECONDS = 10.0
STREAM_MAX_SECONDS = 300.0


@router.get(
    "/proposals/{proposal_id}/image-actions", response_model=list[AssistantImageActionResponse]
)
async def image_actions_endpoint(
    project_id: UUID,
    proposal_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> list[AssistantImageActionResponse]:
    result = []
    for index, job in await action_jobs(
        session, tenant_id=tenant_id, project_id=project_id, proposal_id=proposal_id
    ):
        if job is not None:
            job, assets = await get_image_job(
                session, tenant_id=tenant_id, project_id=project_id, job_id=job.id
            )
            result.append(AssistantImageActionResponse(index=index, job=job_response(job, assets)))
        else:
            result.append(AssistantImageActionResponse(index=index, job=None))
    return result


@router.post(
    "/proposals/{proposal_id}/image-actions/{index}",
    response_model=ImageJobResponse,
    status_code=202,
)
async def start_image_action_endpoint(
    project_id: UUID,
    proposal_id: UUID,
    index: int,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
    settings: SettingsDep,
) -> ImageJobResponse:
    job = await _persist(
        session,
        start_action(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
            index=index,
            author_user_id=current_user.user.id,
            actor=actor,
            settings=settings,
        ),
    )
    job, assets = await get_image_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job.id
    )
    return job_response(job, assets)


def turn_response(
    turn: NarrativeAssistantTurn, proposal: NarrativeAssistantProposal | None
) -> AssistantTurnResponse:
    return AssistantTurnResponse(
        id=turn.id,
        thread_id=turn.thread_id,
        sequence=turn.sequence,
        request=turn.request,
        base_revision_id=turn.base_revision_id,
        focus_node=turn.focus_node,
        status=turn.status,
        cancel_requested=turn.cancel_requested,
        reply=turn.reply,
        error_code=turn.error_code,
        model=turn.model,
        attempts=turn.attempts,
        created_at=turn.created_at,
        updated_at=turn.updated_at,
        finished_at=turn.finished_at,
        proposal=AssistantProposalSummary.model_validate(proposal) if proposal else None,
    )


@router.post("/threads", response_model=AssistantThreadResponse, status_code=201)
async def create_thread_endpoint(
    project_id: UUID,
    payload: AssistantThreadCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> AssistantThreadResponse:
    thread = await _persist(
        session,
        create_thread(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            author_user_id=current_user.user.id,
            title=payload.title,
            idempotency_key=payload.idempotency_key,
            actor=actor,
        ),
    )
    return AssistantThreadResponse.model_validate(thread)


@router.get("/threads", response_model=list[AssistantThreadResponse])
async def list_threads_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=25, ge=1, le=100),
    before_id: UUID | None = None,
    include_archived: bool = False,
) -> list[AssistantThreadResponse]:
    rows = await list_threads(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
        before_id=before_id,
        include_archived=include_archived,
    )
    return [AssistantThreadResponse.model_validate(row) for row in rows]


@router.get("/threads/{thread_id}", response_model=AssistantThreadResponse)
async def get_thread_endpoint(
    project_id: UUID,
    thread_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> AssistantThreadResponse:
    thread = await get_thread(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        include_archived=include_archived,
    )
    return AssistantThreadResponse.model_validate(thread)


@router.post("/threads/{thread_id}/turns", response_model=AssistantTurnResponse, status_code=202)
async def post_turn_endpoint(
    project_id: UUID,
    thread_id: UUID,
    payload: AssistantTurnCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> AssistantTurnResponse:
    turn = await _persist(
        session,
        post_turn(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            thread_id=thread_id,
            author_user_id=current_user.user.id,
            request=payload.request,
            base_revision_id=payload.base_revision_id,
            focus_node=payload.focus_node,
            idempotency_key=payload.idempotency_key,
            actor=actor,
            available=settings.narrative_assistant_provider not in (None, "disabled"),
            max_active_turns=settings.narrative_assistant_max_active_turns_per_workspace,
        ),
    )
    return turn_response(turn, None)


@router.get("/threads/{thread_id}/turns", response_model=list[AssistantTurnResponse])
async def list_turns_endpoint(
    project_id: UUID,
    thread_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    after_sequence: int = Query(default=0, ge=0, le=2**31 - 1),
    limit: int = Query(default=50, ge=1, le=100),
    include_archived: bool = False,
) -> list[AssistantTurnResponse]:
    rows = await list_turns(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        after_sequence=after_sequence,
        limit=limit,
        include_archived=include_archived,
    )
    return [turn_response(turn, proposal) for turn, proposal in rows]


@router.get(
    "/threads/{thread_id}/turns/{turn_id}/events",
    response_model=list[AssistantTurnEventResponse],
)
async def list_turn_events_endpoint(
    project_id: UUID,
    thread_id: UUID,
    turn_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    after_sequence: int = Query(default=0, ge=0, le=2**31 - 1),
    limit: int = Query(default=200, ge=1, le=500),
    include_archived: bool = False,
) -> list[AssistantTurnEventResponse]:
    rows = await list_turn_events(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        after_sequence=after_sequence,
        limit=limit,
        include_archived=include_archived,
    )
    return [AssistantTurnEventResponse.model_validate(row) for row in rows]


def _frame(event: NarrativeAssistantTurnEvent) -> str:
    data = AssistantTurnEventResponse.model_validate(event).model_dump_json()
    return f"id: {event.sequence}\nevent: {event.kind}\ndata: {data}\n\n"


def _cursor(after_sequence: int, last_event_id: str | None) -> int:
    try:
        resumed = int(last_event_id or 0)
    except ValueError:
        resumed = 0
    return max(after_sequence, min(max(resumed, 0), 2**31 - 1))


async def _turn_events(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    turn_id: UUID,
    cursor: int,
) -> AsyncIterator[str]:
    # Each poll uses its own short session: no connection or lock is held between polls.
    loop = asyncio.get_running_loop()
    started = quiet = loop.time()
    yield "retry: 1000\n\n"
    while loop.time() - started < STREAM_MAX_SECONDS:
        async with factory() as session:
            rows = await events_after(
                session, tenant_id=tenant_id, turn_id=turn_id, after_sequence=cursor, limit=200
            )
            status = None
            if not rows:
                status = await session.scalar(
                    select(NarrativeAssistantTurn.status).where(
                        NarrativeAssistantTurn.id == turn_id
                    )
                )
        for row in rows:
            cursor = row.sequence
            yield _frame(row)
            if row.kind == "status":
                return
        if rows:
            quiet = loop.time()
            continue
        # The terminal event commits with the status, so a finished turn with nothing
        # newer is caught up (turns from before live progress have no events at all).
        if status in _TERMINAL:
            return
        if loop.time() - quiet >= STREAM_KEEPALIVE_SECONDS:
            quiet = loop.time()
            yield ": keep-alive\n\n"
        await asyncio.sleep(STREAM_POLL_SECONDS)


@router.get("/threads/{thread_id}/turns/{turn_id}/events/stream")
async def stream_turn_events_endpoint(
    project_id: UUID,
    thread_id: UUID,
    turn_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    after_sequence: int = Query(default=0, ge=0, le=2**31 - 1),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=12),
    include_archived: bool = False,
) -> StreamingResponse:
    await turn_status(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        include_archived=include_archived,
    )
    bind = session.bind
    if bind is None:
        raise RuntimeError("database session is not bound")
    factory = async_sessionmaker(bind=cast(AsyncEngine, bind), expire_on_commit=False)
    # Release the request session (and any user-row lock) before the long body.
    await session.commit()
    return StreamingResponse(
        _turn_events(
            factory,
            tenant_id=tenant_id,
            turn_id=turn_id,
            cursor=_cursor(after_sequence, last_event_id),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/threads/{thread_id}/turns/{turn_id}/cancel", response_model=AssistantTurnResponse)
async def cancel_turn_endpoint(
    project_id: UUID,
    thread_id: UUID,
    turn_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> AssistantTurnResponse:
    turn = await _persist(
        session,
        cancel_turn(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            thread_id=thread_id,
            turn_id=turn_id,
            actor=actor,
        ),
    )
    return turn_response(turn, None)


@router.get("/proposals/{proposal_id}", response_model=AssistantProposalResponse)
async def get_proposal_endpoint(
    project_id: UUID,
    proposal_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> AssistantProposalResponse:
    proposal = await get_proposal(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        proposal_id=proposal_id,
        include_archived=include_archived,
    )
    return AssistantProposalResponse.model_validate(proposal)


@router.post(
    "/proposals/{proposal_id}/accept", response_model=NarrativeRevisionResponse, status_code=201
)
async def accept_proposal_endpoint(
    project_id: UUID,
    proposal_id: UUID,
    payload: AssistantDecision,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> NarrativeRevisionResponse | JSONResponse:
    revision = await _persist(
        session,
        accept_proposal(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
            author_user_id=current_user.user.id,
            idempotency_key=payload.idempotency_key,
            actor=actor,
        ),
    )
    if revision.conflicted:
        # Same contract as a stale manual save: the conflict snapshot is committed.
        return JSONResponse(
            status_code=409,
            media_type="application/problem+json",
            content={
                "type": "urn:flint-graph:error:stale-revision",
                "title": "Revision conflict",
                "status": 409,
                "detail": "The story changed after this proposal. It was saved as a conflict "
                "revision; the current story is unchanged.",
                "errors": [
                    {
                        "code": "stale_revision",
                        "conflict_revision_id": str(revision.id),
                        "observed_head_revision_id": str(revision.observed_head_revision_id),
                    }
                ],
            },
        )
    return NarrativeRevisionResponse.model_validate(revision)


@router.post("/proposals/{proposal_id}/reject", response_model=AssistantProposalResponse)
async def reject_proposal_endpoint(
    project_id: UUID,
    proposal_id: UUID,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> AssistantProposalResponse:
    proposal = await _persist(
        session,
        reject_proposal(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            proposal_id=proposal_id,
            author_user_id=current_user.user.id,
            actor=actor,
        ),
    )
    return AssistantProposalResponse.model_validate(proposal)
