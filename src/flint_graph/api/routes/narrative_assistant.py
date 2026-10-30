"""Project assistant threads, turns and proposal decisions (ADR 0038).

Requests record intent only; no model runs inside an API request.
"""

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

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
    AssistantProposalResponse,
    AssistantProposalSummary,
    AssistantThreadCreate,
    AssistantThreadResponse,
    AssistantTurnCreate,
    AssistantTurnResponse,
)
from flint_graph.api.narrative_schemas import NarrativeRevisionResponse
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_assistant import (
    accept_proposal,
    cancel_turn,
    create_thread,
    get_proposal,
    get_thread,
    list_threads,
    list_turns,
    post_turn,
    reject_proposal,
)
from flint_graph.infrastructure.db.models import NarrativeAssistantProposal, NarrativeAssistantTurn

router = APIRouter(prefix="/v1/narrative/projects/{project_id}/assistant", tags=["narrative"])


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
