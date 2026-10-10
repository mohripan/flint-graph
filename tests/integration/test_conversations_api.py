import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flint_graph.application.services.conversations import (
    ConversationTurnCreate,
    create_conversation_turn,
    get_conversation,
)
from flint_graph.application.services.query_runs import transition_query_run
from flint_graph.application.services.retrieval_index_versions import (
    deprecate_retrieval_index_version,
)
from flint_graph.config import Settings, get_settings
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    QueryRunStatus,
    SourceType,
    WorkspaceMembershipStatus,
)
from flint_graph.domain.errors import ConflictError
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentIndexCoverage,
    DocumentVersion,
    User,
    WorkspaceMembership,
)
from flint_graph.infrastructure.db.session import get_session
from flint_graph.main import app, create_app


@pytest_asyncio.fixture(
    params=["sqlite", "postgres"] if os.getenv("FLINT_GRAPH_PG_INTEGRATION") else ["sqlite"]
)
async def conversation_env(request, tmp_path) -> AsyncIterator[tuple]:
    schema = None
    if request.param == "postgres":
        schema = f"flint_conversation_test_{uuid4().hex}"
        engine = create_async_engine(
            os.getenv(
                "FLINT_GRAPH_PG_TEST_URL",
                "postgresql+asyncpg://flint_graph:flint_graph@localhost:55432/flint_graph",
            )
        )
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'conversation.sqlite'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(_env_file=None, env="test", otel_enabled=False)
    app = create_app(settings)

    async def sessions():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, factory, request.param
    finally:
        if schema is not None:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def searchable_workspace(client, factory) -> tuple[dict[str, str], str]:
    workspace = (await client.post("/v1/workspaces", json={"name": "Searchable fixture"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}
    index = (await client.post("/v1/retrieval-index/bootstrap", headers=headers)).json()
    async with factory() as session:
        document = Document(
            tenant_id=UUID(workspace["id"]), title="Fixture", source_type=SourceType.UPLOAD
        )
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            document_id=document.id, version_number=1, status=DocumentVersionStatus.ACTIVE
        )
        session.add(version)
        await session.flush()
        session.add(
            DocumentIndexCoverage(
                tenant_id=document.tenant_id,
                document_id=document.id,
                document_version_id=version.id,
                retrieval_index_version_id=UUID(index["id"]),
                status=DocumentIndexCoverageStatus.COMPLETED,
                chunk_count=1,
                embedded_count=1,
                lexical_count=1,
                vector_count=1,
            )
        )
        await session.commit()
    return headers, index["id"]


@pytest.mark.anyio
async def test_conversation_can_be_created_reopened_and_is_tenant_scoped(conversation_env) -> None:
    client, _, _ = conversation_env
    workspace = (await client.post("/v1/workspaces", json={"name": "Conversation fixture"})).json()
    foreign = (await client.post("/v1/workspaces", json={"name": "Foreign fixture"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}
    created = await client.post("/v1/conversations", headers=headers, json={"title": "Research"})
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["tenant_id"] == workspace["id"]
    assert conversation["title"] == "Research"
    assert conversation["next_turn_number"] == 1
    reopened = await client.get(f"/v1/conversations/{conversation['id']}", headers=headers)
    assert reopened.json() == conversation
    assert (await client.get("/v1/conversations", headers=headers)).json() == [conversation]
    denied = await client.get(
        f"/v1/conversations/{conversation['id']}", headers={"X-Tenant-ID": foreign["id"]}
    )
    assert denied.status_code == 404
    assert (await client.get(f"/v1/conversations/{uuid4()}", headers=headers)).status_code == 404
    for title in ("", "   ", "x" * 201):
        assert (
            await client.post("/v1/conversations", headers=headers, json={"title": title})
        ).status_code == 422


@pytest.mark.anyio
async def test_conversation_rename_persists_only_a_trimmed_title(conversation_env) -> None:
    client, _, _ = conversation_env
    workspace = (await client.post("/v1/workspaces", json={"name": "Rename fixture"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}
    created = (
        await client.post("/v1/conversations", headers=headers, json={"title": "Original"})
    ).json()
    path = f"/v1/conversations/{created['id']}"
    renamed = await client.patch(
        path, headers=headers, json={"title": "  Annual report research  "}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Annual report research"
    assert renamed.json()["id"] == created["id"]
    assert renamed.json()["created_at"] == created["created_at"]
    assert renamed.json()["next_turn_number"] == 1
    assert (await client.get(path, headers=headers)).json() == renamed.json()
    assert (await client.get("/v1/conversations", headers=headers)).json() == [renamed.json()]
    assert (await client.get("/v1/system-readiness", headers=headers)).json()["setup_capabilities"][
        "conversation_discovery"
    ] is True
    for payload in (
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "New", "tenant_id": workspace["id"]},
        {"title": 123},
        {"title": "Invalid\x00title"},
    ):
        assert (await client.patch(path, headers=headers, json=payload)).status_code == 422
    assert (
        await client.post("/v1/conversations", headers=headers, json={"title": "Invalid\x00title"})
    ).status_code == 422


@pytest.mark.anyio
async def test_conversation_search_matches_literal_titles_not_sql_patterns(
    conversation_env,
) -> None:
    client, _, _ = conversation_env
    workspace = (await client.post("/v1/workspaces", json={"name": "Search fixture"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}
    literal = (
        await client.post(
            "/v1/conversations", headers=headers, json={"title": "Revenue 100%_!\\ research"}
        )
    ).json()
    other = (
        await client.post(
            "/v1/conversations", headers=headers, json={"title": "Headquarters research"}
        )
    ).json()
    for query in ("REVENUE", "%", "_", "!", "\\", "  revenue  "):
        rows = (await client.get("/v1/conversations", headers=headers, params={"q": query})).json()
        assert [row["id"] for row in rows] == [literal["id"]]
    assert (
        len((await client.get("/v1/conversations", headers=headers, params={"q": "  "})).json())
        == 2
    )
    assert (
        await client.get("/v1/conversations", headers=headers, params={"q": "missing"})
    ).json() == []
    assert (
        await client.get("/v1/conversations", headers=headers, params={"q": "x" * 201})
    ).status_code == 422
    assert (
        await client.get("/v1/conversations", headers=headers, params={"q": "Invalid\x00search"})
    ).status_code == 422
    for cursor in (literal["id"], other["id"]):
        assert (
            await client.get(
                "/v1/conversations",
                headers=headers,
                params={"q": "research", "before_id": cursor, "limit": 1},
            )
        ).status_code == 200


@pytest.mark.anyio
async def test_search_paging_and_rename_preserve_tenant_and_archive_boundaries(conversation_env):
    client, _, _ = conversation_env
    workspace = (await client.post("/v1/workspaces", json={"name": "Discovery fixture"})).json()
    foreign = (await client.post("/v1/workspaces", json={"name": "Foreign discovery"})).json()
    headers, foreign_headers = {"X-Tenant-ID": workspace["id"]}, {"X-Tenant-ID": foreign["id"]}
    created = []
    for title in ("Revenue first", "Other subject", "Revenue second", "Revenue third"):
        created.append(
            (await client.post("/v1/conversations", headers=headers, json={"title": title})).json()
        )
    foreign_row = (
        await client.post(
            "/v1/conversations", headers=foreign_headers, json={"title": "Revenue foreign"}
        )
    ).json()
    expected = sorted(
        [row for row in created if "Revenue" in row["title"]],
        key=lambda row: (row["created_at"], row["id"]),
        reverse=True,
    )
    rows = []
    params = {"q": "revenue", "limit": 1}
    while True:
        page = (await client.get("/v1/conversations", headers=headers, params=params)).json()
        if not page:
            break
        rows.extend(page)
        params["before_id"] = page[-1]["id"]
    assert [row["id"] for row in rows] == [row["id"] for row in expected]
    assert (
        await client.get(
            "/v1/conversations",
            headers=headers,
            params={"q": "missing", "before_id": foreign_row["id"]},
        )
    ).status_code == 404
    path = f"/v1/conversations/{created[0]['id']}"
    assert (
        await client.patch(path, headers=foreign_headers, json={"title": "Foreign write"})
    ).status_code == 404
    assert (
        await client.post(path + "/archive", headers=headers, json={"archived": True})
    ).status_code == 200
    assert (
        await client.patch(path, headers=headers, json={"title": "Hidden write"})
    ).status_code == 404
    visible = (
        await client.get("/v1/conversations", headers=headers, params={"q": "revenue"})
    ).json()
    assert created[0]["id"] not in {row["id"] for row in visible}
    archived = (
        await client.get(
            "/v1/conversations",
            headers=headers,
            params={"q": "revenue", "include_archived": "true"},
        )
    ).json()
    assert len(archived) == 3
    assert (
        await client.post(path + "/archive", headers=headers, json={"archived": False})
    ).status_code == 200
    before = (await client.get(path + "/turns", headers=headers)).json()
    assert (
        await client.patch(path, headers=headers, json={"title": "Changed topic"})
    ).status_code == 200
    assert (await client.get(path + "/turns", headers=headers)).json() == before


@pytest.mark.anyio
async def test_conversation_turn_links_an_original_question_to_a_run(conversation_env) -> None:
    client, factory, _ = conversation_env
    headers, index_id = await searchable_workspace(client, factory)
    conversation = (
        await client.post("/v1/conversations", headers=headers, json={"title": "Annual reports"})
    ).json()
    path = f"/v1/conversations/{conversation['id']}/turns"
    created = await client.post(
        path,
        headers=headers,
        json={
            "query": "What was Acme revenue in 2017?",
            "idempotency_key": str(uuid4()),
        },
    )
    assert created.status_code == 201
    turn = created.json()
    assert turn["turn_number"] == 1
    assert turn["conversation_id"] == conversation["id"]
    assert turn["run"]["query_text"] == "What was Acme revenue in 2017?"
    assert turn["run"]["retrieval_index_version_id"] == index_id
    assert turn["run"]["status"] == "queued"
    assert (await client.get(path, headers=headers)).json() == [turn]
    assert (await client.get(f"{path}/{turn['id']}", headers=headers)).json() == turn
    run = (await client.get(f"/v1/query-runs/{turn['run']['id']}", headers=headers)).json()
    assert run == turn["run"]
    assert (await client.get(f"/v1/conversations/{conversation['id']}", headers=headers)).json()[
        "next_turn_number"
    ] == 2


@pytest.mark.anyio
async def test_turn_replay_conflicts_and_active_turn_rule_preserve_order(conversation_env) -> None:
    client, factory, _ = conversation_env
    headers, _ = await searchable_workspace(client, factory)
    conversation = (await client.post("/v1/conversations", headers=headers, json={})).json()
    path = f"/v1/conversations/{conversation['id']}/turns"
    payload = {"query": "Revenue in 2017?", "idempotency_key": str(uuid4())}
    first = (await client.post(path, headers=headers, json=payload)).json()
    assert (await client.post(path, headers=headers, json=payload)).json() == first
    for change in (
        {"query": "Revenue in 2016?"},
        {"stream": False},
        {"filters": {"chunk_id": "other"}},
    ):
        assert (
            await client.post(path, headers=headers, json={**payload, **change})
        ).status_code == 409
    next_payload = {"query": "What about the prior year?", "idempotency_key": str(uuid4())}
    assert (await client.post(path, headers=headers, json=next_payload)).status_code == 409
    assert (await client.get(path, headers=headers)).json() == [first]
    async with factory() as session:
        await transition_query_run(
            session,
            tenant_id=UUID(headers["X-Tenant-ID"]),
            query_run_id=UUID(first["run"]["id"]),
            target_status=QueryRunStatus.CANCELLED,
            event_type="query.cancelled",
            payload={},
        )
        await session.commit()
    second_response = await client.post(path, headers=headers, json=next_payload)
    assert second_response.status_code == 201
    second = second_response.json()
    assert second["turn_number"] == 2
    assert second["run"]["query_text"] == "What about the prior year?"
    assert second["run"]["metadata"]["conversation"]["memory_mode"] == "independent"
    assert (await client.get(path, headers=headers)).json()[0]["run"]["status"] == "cancelled"


@pytest.mark.anyio
async def test_conversation_and_turn_paging_reject_foreign_cursors(conversation_env) -> None:
    client, factory, _ = conversation_env
    headers, _ = await searchable_workspace(client, factory)
    conversations = []
    turns = []
    for ordinal in range(3):
        conversation = (
            await client.post(
                "/v1/conversations", headers=headers, json={"title": f"Research {ordinal}"}
            )
        ).json()
        conversations.append(conversation)
        path = f"/v1/conversations/{conversation['id']}/turns"
        turn = (
            await client.post(
                path,
                headers=headers,
                json={
                    "query": "Revenue in 2017?",
                    "idempotency_key": str(uuid4()),
                },
            )
        ).json()
        turns.append(turn)
    page1 = (await client.get("/v1/conversations?limit=1", headers=headers)).json()
    page2 = (
        await client.get(f"/v1/conversations?limit=2&before_id={page1[0]['id']}", headers=headers)
    ).json()
    assert {row["id"] for row in page1 + page2} == {row["id"] for row in conversations}
    assert len(page1 + page2) == 3
    foreign = (await client.post("/v1/workspaces", json={"name": "Foreign cursors"})).json()
    foreign_headers = {"X-Tenant-ID": foreign["id"]}
    assert (
        await client.get(
            f"/v1/conversations?before_id={conversations[0]['id']}", headers=foreign_headers
        )
    ).status_code == 404
    path = f"/v1/conversations/{conversations[0]['id']}/turns"
    assert (
        await client.get(f"{path}?after_id={turns[1]['id']}", headers=headers)
    ).status_code == 404
    assert (await client.get(f"{path}/{turns[1]['id']}", headers=headers)).status_code == 404
    assert (await client.get(path, headers=foreign_headers)).status_code == 404
    assert (
        await client.post(
            path,
            headers=foreign_headers,
            json={
                "query": "secret",
                "idempotency_key": str(uuid4()),
            },
        )
    ).status_code == 404
    for limit in (0, 101):
        assert (await client.get(f"{path}?limit={limit}", headers=headers)).status_code == 422


@pytest.mark.anyio
async def test_archive_blocks_active_turns_and_reopens_without_erasing_runs(
    conversation_env,
) -> None:
    client, factory, _ = conversation_env
    headers, _ = await searchable_workspace(client, factory)
    conversation = (await client.post("/v1/conversations", headers=headers, json={})).json()
    path = f"/v1/conversations/{conversation['id']}"
    turn = (
        await client.post(
            f"{path}/turns",
            headers=headers,
            json={
                "query": "Revenue?",
                "idempotency_key": str(uuid4()),
            },
        )
    ).json()
    assert (
        await client.post(f"{path}/archive", headers=headers, json={"archived": True})
    ).status_code == 409
    async with factory() as session:
        await transition_query_run(
            session,
            tenant_id=UUID(headers["X-Tenant-ID"]),
            query_run_id=UUID(turn["run"]["id"]),
            target_status=QueryRunStatus.CANCELLED,
            event_type="query.cancelled",
            payload={},
        )
        await session.commit()
    archived = await client.post(f"{path}/archive", headers=headers, json={"archived": True})
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert (await client.get(path, headers=headers)).status_code == 404
    assert (await client.get("/v1/conversations", headers=headers)).json() == []
    assert (await client.get(f"{path}?include_archived=true", headers=headers)).status_code == 200
    assert (
        len((await client.get(f"{path}/turns?include_archived=true", headers=headers)).json()) == 1
    )
    assert (
        await client.post(
            f"{path}/turns",
            headers=headers,
            json={
                "query": "New turn",
                "idempotency_key": str(uuid4()),
            },
        )
    ).status_code == 404
    assert (
        await client.get(f"/v1/query-runs/{turn['run']['id']}", headers=headers)
    ).status_code == 200
    reopened = await client.post(f"{path}/archive", headers=headers, json={"archived": False})
    assert reopened.status_code == 200
    assert reopened.json()["archived_at"] is None
    assert reopened.json()["next_turn_number"] == 2
    readiness = (await client.get("/v1/system-readiness", headers=headers)).json()
    assert readiness["setup_capabilities"]["conversation_ledger"] is True
    assert readiness["setup_capabilities"]["chained_conversations"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("same_key", [True, False])
async def test_postgres_concurrent_turn_submission_is_serialized(
    conversation_env, same_key
) -> None:
    client, factory, backend = conversation_env
    if backend != "postgres":
        pytest.skip("Row-lock concurrency qualification requires PostgreSQL.")
    headers, _ = await searchable_workspace(client, factory)
    conversation = (await client.post("/v1/conversations", headers=headers, json={})).json()
    tenant_id = UUID(headers["X-Tenant-ID"])
    conversation_id = UUID(conversation["id"])
    first_key = uuid4()
    keys = [first_key, first_key if same_key else uuid4()]
    barrier = asyncio.Barrier(2)

    async def submit(key):
        async with factory() as session:
            await get_conversation(session, tenant_id=tenant_id, conversation_id=conversation_id)
            await barrier.wait()
            try:
                turn = await create_conversation_turn(
                    session,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    spec=ConversationTurnCreate(query="Revenue?", idempotency_key=key),
                )
                await session.commit()
                return str(turn.id)
            except ConflictError:
                await session.rollback()
                return "conflict"

    async with asyncio.timeout(10):
        results = await asyncio.gather(*(submit(key) for key in keys))
    if same_key:
        assert results[0] == results[1]
        assert "conflict" not in results
    else:
        assert results.count("conflict") == 1
    turns = (await client.get(f"/v1/conversations/{conversation_id}/turns", headers=headers)).json()
    assert len(turns) == 1
    assert turns[0]["turn_number"] == 1
    assert (await client.get(f"/v1/conversations/{conversation_id}", headers=headers)).json()[
        "next_turn_number"
    ] == 2


@pytest.mark.anyio
async def test_oidc_conversation_roles_and_revocation_are_enforced(client, oidc_auth) -> None:

    owner = {"Authorization": f"Bearer {oidc_auth('conversation-owner')}"}
    viewer = {"Authorization": f"Bearer {oidc_auth('conversation-viewer')}"}
    member = {"Authorization": f"Bearer {oidc_auth('conversation-member')}"}
    workspace = (
        await client.post("/v1/workspaces", headers=owner, json={"name": "OIDC conversations"})
    ).json()
    for subject, role in (("conversation-viewer", "viewer"), ("conversation-member", "member")):
        assert (
            await client.post(
                f"/v1/workspaces/{workspace['id']}/members",
                headers=owner,
                json={"oidc_subject": subject, "role": role},
            )
        ).status_code == 201
    owner["X-Tenant-ID"] = viewer["X-Tenant-ID"] = member["X-Tenant-ID"] = workspace["id"]
    created = await client.post(
        "/v1/conversations", headers=member, json={"title": "Shared research"}
    )
    assert created.status_code == 201
    path = f"/v1/conversations/{created.json()['id']}"
    assert (await client.get(path, headers=viewer)).status_code == 200
    assert (
        await client.patch(path, headers=member, json={"title": "Member renamed"})
    ).status_code == 200
    assert (
        await client.patch(path, headers=viewer, json={"title": "Viewer write"})
    ).status_code == 403
    assert (await client.get("/v1/conversations", headers=viewer, params={"q": "member"})).json()[
        0
    ]["title"] == "Member renamed"
    assert (await client.get(path, headers={"X-Tenant-ID": workspace["id"]})).status_code == 401
    assert (await client.post("/v1/conversations", headers=viewer, json={})).status_code == 403
    assert (
        await client.post(
            f"{path}/turns",
            headers=viewer,
            json={"query": "Revenue?", "idempotency_key": str(uuid4())},
        )
    ).status_code == 403

    assert (
        await client.post(f"{path}/archive", headers=member, json={"archived": True})
    ).status_code == 403
    # Setup simulates membership lifecycle; denial is observed only via HTTP.
    async for session in app.dependency_overrides[get_session]():
        membership = await session.scalar(
            select(WorkspaceMembership)
            .join(User)
            .where(
                WorkspaceMembership.tenant_id == UUID(workspace["id"]),
                User.oidc_subject == "conversation-member",
            )
        )
        membership.status = WorkspaceMembershipStatus.DISABLED
        await session.commit()
    assert (await client.get(path, headers=member)).status_code == 403
    assert (
        await client.patch(path, headers=member, json={"title": "Revoked write"})
    ).status_code == 403
    assert (
        await client.get("/v1/conversations", headers=member, params={"q": "member"})
    ).status_code == 403
    assert (await client.get(f"{path}/turns", headers=member)).status_code == 403
    assert (
        await client.post(
            f"{path}/turns",
            headers=member,
            json={"query": "Revenue?", "idempotency_key": str(uuid4())},
        )
    ).status_code == 403


@pytest.mark.anyio
async def test_ordered_turn_cursor_and_replay_survive_index_deprecation(conversation_env) -> None:
    client, factory, _ = conversation_env
    headers, index_id = await searchable_workspace(client, factory)
    conversation = (await client.post("/v1/conversations", headers=headers, json={})).json()
    path = f"/v1/conversations/{conversation['id']}/turns"
    turns = []
    payloads = []
    for number in range(3):
        payload = {"query": f"Question {number}", "idempotency_key": str(uuid4())}
        turn = (await client.post(path, headers=headers, json=payload)).json()
        turns.append(turn)
        payloads.append(payload)
        async with factory() as session:
            await transition_query_run(
                session,
                tenant_id=UUID(headers["X-Tenant-ID"]),
                query_run_id=UUID(turn["run"]["id"]),
                target_status=QueryRunStatus.CANCELLED,
                event_type="query.cancelled",
                payload={},
            )
            await session.commit()
    assert [turn["turn_number"] for turn in turns] == [1, 2, 3]
    page1 = (await client.get(f"{path}?limit=1", headers=headers)).json()
    page2 = (await client.get(f"{path}?limit=2&after_id={page1[0]['id']}", headers=headers)).json()
    assert [turn["id"] for turn in page1 + page2] == [turn["id"] for turn in turns]
    async with factory() as session:
        await deprecate_retrieval_index_version(session, version_id=UUID(index_id))
        await session.commit()
    replay = await client.post(path, headers=headers, json=payloads[0])
    assert replay.status_code == 201
    assert replay.json()["id"] == turns[0]["id"]
    assert replay.json()["run"]["status"] == "cancelled"
    assert (
        await client.post(
            path,
            headers=headers,
            json={
                "query": "New question",
                "idempotency_key": str(uuid4()),
            },
        )
    ).status_code == 404
    assert (await client.get(f"/v1/conversations/{conversation['id']}", headers=headers)).json()[
        "next_turn_number"
    ] == 4


@pytest.mark.anyio
async def test_queued_turn_can_be_cancelled_before_inference(conversation_env) -> None:
    client, factory, _ = conversation_env
    headers, _ = await searchable_workspace(client, factory)
    conversation = (await client.post("/v1/conversations", headers=headers, json={})).json()
    path = f"/v1/conversations/{conversation['id']}/turns"
    turn = (
        await client.post(
            path,
            headers=headers,
            json={
                "query": "Revenue?",
                "idempotency_key": str(uuid4()),
            },
        )
    ).json()
    cancelled = await client.post(f"{path}/{turn['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["run"]["status"] == "cancelled"
    assert (await client.post(f"{path}/{turn['id']}/cancel", headers=headers)).status_code == 200
    events = (
        await client.get(f"/v1/query-runs/{turn['run']['id']}/events", headers=headers)
    ).json()
    assert [event["event_type"] for event in events] == ["query.cancelled"]
    assert (
        await client.get(f"/v1/query-runs/{turn['run']['id']}/usage", headers=headers)
    ).json() == []
    assert (
        await client.post(
            path,
            headers=headers,
            json={
                "query": "Next question",
                "idempotency_key": str(uuid4()),
            },
        )
    ).status_code == 201


@pytest.mark.anyio
@pytest.mark.parametrize("terminal", [False, True])
async def test_queued_cancel_refuses_running_and_completed_turns(
    conversation_env, terminal
) -> None:
    client, factory, _ = conversation_env
    headers, _ = await searchable_workspace(client, factory)
    conversation = (await client.post("/v1/conversations", headers=headers, json={})).json()
    path = f"/v1/conversations/{conversation['id']}/turns"
    turn = (
        await client.post(
            path,
            headers=headers,
            json={
                "query": "Revenue?",
                "idempotency_key": str(uuid4()),
            },
        )
    ).json()
    async with factory() as session:
        await transition_query_run(
            session,
            tenant_id=UUID(headers["X-Tenant-ID"]),
            query_run_id=UUID(turn["run"]["id"]),
            target_status=QueryRunStatus.RUNNING,
            event_type="query.started",
            payload={},
        )
        if terminal:
            await transition_query_run(
                session,
                tenant_id=UUID(headers["X-Tenant-ID"]),
                query_run_id=UUID(turn["run"]["id"]),
                target_status=QueryRunStatus.COMPLETED,
                event_type="query.completed",
                payload={},
                answer_text="Fixture final answer.",
            )
        await session.commit()
    assert (await client.post(f"{path}/{turn['id']}/cancel", headers=headers)).status_code == 409
    observed = (await client.get(f"{path}/{turn['id']}", headers=headers)).json()
    assert observed["run"]["status"] == ("completed" if terminal else "running")
