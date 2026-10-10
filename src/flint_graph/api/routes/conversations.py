from uuid import UUID

from fastapi import APIRouter, Query, status

from flint_graph.api.dependencies import (
    SessionDep,
    SettingsDep,
    TenantAdminDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.schemas import (
    ConversationArchiveRequest,
    ConversationCreateRequest,
    ConversationResponse,
    ConversationTurnCreateRequest,
    ConversationTurnResponse,
)
from flint_graph.application.services.conversations import (
    ConversationTurnCreate,
    cancel_queued_conversation_turn,
    create_conversation,
    create_conversation_turn,
    get_conversation,
    get_conversation_turn,
    list_conversation_turns,
    list_conversations,
    set_conversation_archived,
)
from flint_graph.domain.errors import BadRequestError

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.post("/{conversation_id}/turns/{turn_id}/cancel", response_model=ConversationTurnResponse)
async def cancel_queued_turn_endpoint(
    conversation_id: UUID,
    turn_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
) -> ConversationTurnResponse:
    turn = await cancel_queued_conversation_turn(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    return ConversationTurnResponse.model_validate(turn)


@router.post("/{conversation_id}/archive", response_model=ConversationResponse)
async def archive_conversation_endpoint(
    conversation_id: UUID,
    payload: ConversationArchiveRequest,
    tenant_id: TenantAdminDep,
    session: SessionDep,
) -> ConversationResponse:
    conversation = await set_conversation_archived(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        archived=payload.archived,
    )
    return ConversationResponse.model_validate(conversation)


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation_endpoint(
    payload: ConversationCreateRequest,
    tenant_id: TenantMemberDep,
    session: SessionDep,
) -> ConversationResponse:
    conversation = await create_conversation(session, tenant_id=tenant_id, title=payload.title)
    return ConversationResponse.model_validate(conversation)


@router.post(
    "/{conversation_id}/turns",
    response_model=ConversationTurnResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation_turn_endpoint(
    conversation_id: UUID,
    payload: ConversationTurnCreateRequest,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ConversationTurnResponse:
    if not settings.query_enabled:
        raise BadRequestError("Query orchestration is disabled.")
    turn = await create_conversation_turn(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        spec=ConversationTurnCreate(**payload.model_dump()),
    )
    return ConversationTurnResponse.model_validate(turn)


@router.get("/{conversation_id}/turns", response_model=list[ConversationTurnResponse])
async def list_conversation_turns_endpoint(
    conversation_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    after_id: UUID | None = None,
    include_archived: bool = False,
) -> list[ConversationTurnResponse]:
    turns = await list_conversation_turns(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        limit=limit,
        after_id=after_id,
        include_archived=include_archived,
    )
    return [ConversationTurnResponse.model_validate(turn) for turn in turns]


@router.get("/{conversation_id}/turns/{turn_id}", response_model=ConversationTurnResponse)
async def get_conversation_turn_endpoint(
    conversation_id: UUID,
    turn_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> ConversationTurnResponse:
    turn = await get_conversation_turn(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        include_archived=include_archived,
    )
    return ConversationTurnResponse.model_validate(turn)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations_endpoint(
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    before_id: UUID | None = None,
    include_archived: bool = False,
) -> list[ConversationResponse]:
    conversations = await list_conversations(
        session,
        tenant_id=tenant_id,
        limit=limit,
        before_id=before_id,
        include_archived=include_archived,
    )
    return [ConversationResponse.model_validate(row) for row in conversations]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_endpoint(
    conversation_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    include_archived: bool = False,
) -> ConversationResponse:
    conversation = await get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        include_archived=include_archived,
    )
    return ConversationResponse.model_validate(conversation)
