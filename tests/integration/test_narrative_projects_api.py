"""Public narrative project/revision contract; no retrieval or models required."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, event, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flint_graph.api.dependencies import get_session
from flint_graph.domain.enums import WorkspaceMembershipStatus
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.models import (
    NarrativeProject,
    NarrativeRevision,
    User,
    WorkspaceMembership,
)
from flint_graph.main import app
from flint_graph.narrative import Player, load_package


@pytest_asyncio.fixture(
    params=["sqlite", "postgres"] if os.getenv("FLINT_GRAPH_NARRATIVE_PG_URL") else ["sqlite"]
)
async def narrative_env(client, request, tmp_path) -> AsyncIterator[tuple]:
    # PostgreSQL is opt-in to an explicit owned database; never use the workspace default.
    schema = None
    if request.param == "postgres":
        schema = "narrative_test_" + uuid4().hex
        engine = create_async_engine(os.environ["FLINT_GRAPH_NARRATIVE_PG_URL"])
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await engine.dispose()
        engine = create_async_engine(
            os.environ["FLINT_GRAPH_NARRATIVE_PG_URL"],
            connect_args={"server_settings": {"search_path": schema + ",public"}},
            hide_parameters=True,
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'narrative.sqlite'}")

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        if schema is not None:

            def migrate(sync_connection):
                config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
                config.set_main_option(
                    "script_location", str(Path(__file__).parents[2] / "migrations")
                )
                config.attributes["connection"] = sync_connection
                config.attributes["configure_logger"] = False
                config.attributes["version_table_schema"] = schema
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
        else:
            await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def sessions():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = sessions
    try:
        yield client, factory, request.param
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.anyio
async def test_blank_project_is_playable_without_searchable_documents(
    narrative_env, tmp_path
) -> None:
    client, _, _ = narrative_env
    workspace = (await client.post("/v1/workspaces", json={"name": "Original game studio"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}

    created = await client.post(
        "/v1/narrative/projects",
        headers=headers,
        json={"name": "A new mystery", "idempotency_key": str(uuid4())},
    )

    assert created.status_code == 201
    project = created.json()
    assert project["name"] == "A new mystery"
    assert project["head_revision_id"]
    assert project["archived_at"] is None
    revision = await client.get(
        f"/v1/narrative/projects/{project['id']}/revisions/{project['head_revision_id']}",
        headers=headers,
    )
    assert revision.status_code == 200
    assert revision.json()["revision_number"] == 1
    assert revision.json()["conflicted"] is False
    assert revision.json()["parent_revision_id"] is None
    assert len(revision.json()["content_hash"]) == 64
    source = tmp_path / "portable"
    source.mkdir()
    (source / "story.json").write_text(revision.json()["story_json"], encoding="utf-8")
    (source / "NOTICES.txt").write_text(revision.json()["notices"], encoding="utf-8")
    package = load_package(source)
    assert package.content_hash == revision.json()["content_hash"]
    player = Player(package)
    assert player.view["type"] == "line"
    player.act("advance")
    assert player.state["status"] == "ended"


@pytest.mark.anyio
async def test_stale_edit_is_saved_as_recoverable_conflict_without_replacing_head(
    narrative_env,
) -> None:
    client, _, _ = narrative_env
    workspace = (await client.post("/v1/workspaces", json={"name": "Concurrent writers"})).json()
    headers = {"X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Shared story", "idempotency_key": str(uuid4())},
        )
    ).json()
    path = f"/v1/narrative/projects/{project['id']}"
    base = (
        await client.get(f"{path}/revisions/{project['head_revision_id']}", headers=headers)
    ).json()
    story = json.loads(base["story_json"])
    story["nodes"]["opening"]["text"] = "One author follows the lantern."
    first_payload = {
        "base_revision_id": base["id"],
        "idempotency_key": str(uuid4()),
        "story_json": json.dumps(story),
        "notices": "Original author notes.\n",
    }

    first = await client.post(f"{path}/revisions", headers=headers, json=first_payload)

    assert first.status_code == 201
    assert first.json()["revision_number"] == 2
    story["nodes"]["opening"]["text"] = "Another author studies the river."
    stale_payload = {
        **first_payload,
        "idempotency_key": str(uuid4()),
        "story_json": json.dumps(story),
    }
    stale = await client.post(f"{path}/revisions", headers=headers, json=stale_payload)
    assert stale.status_code == 409
    conflict_id = stale.json()["errors"][0]["conflict_revision_id"]
    recovered = await client.get(f"{path}/revisions/{conflict_id}", headers=headers)
    assert recovered.status_code == 200
    assert recovered.json()["conflicted"] is True
    assert recovered.json()["parent_revision_id"] == base["id"]
    assert recovered.json()["observed_head_revision_id"] == first.json()["id"]
    assert recovered.json()["revision_number"] == 3
    assert json.loads(recovered.json()["story_json"])["nodes"]["opening"]["text"] == (
        "Another author studies the river."
    )
    head = (await client.get(path, headers=headers)).json()
    assert head["head_revision_id"] == first.json()["id"]
    assert (await client.get(f"{path}/revisions/{base['id']}", headers=headers)).json() == base
    retry = await client.post(f"{path}/revisions", headers=headers, json=stale_payload)
    assert retry.status_code == 409
    assert retry.json() == stale.json()
    first_retry = await client.post(f"{path}/revisions", headers=headers, json=first_payload)
    assert first_retry.status_code == 201
    assert first_retry.json() == first.json()


async def blank_project(client, name="A text story", auth_headers=None):
    workspace = (
        await client.post("/v1/workspaces", json={"name": name}, headers=auth_headers)
    ).json()
    headers = {**(auth_headers or {}), "X-Tenant-ID": workspace["id"]}
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": name, "idempotency_key": str(uuid4())},
        )
    ).json()
    path = f"/v1/narrative/projects/{project['id']}"
    base = (
        await client.get(f"{path}/revisions/{project['head_revision_id']}", headers=headers)
    ).json()
    return headers, project, base, path


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case,code",
    [
        ("duplicate", "invalid_json"),
        ("asset", "assets_not_supported"),
        ("notice_nul", "invalid_text"),
        ("notice_utf8_size", "size_limit"),
    ],
)
async def test_invalid_source_returns_safe_diagnostics_and_keeps_head(narrative_env, case, code):
    client, _, _ = narrative_env
    headers, project, base, path = await blank_project(client)
    source = base["story_json"]
    notices = ""
    if case == "duplicate":
        source = '{"schema_version":"1",' + source[1:]
    elif case == "asset":
        story = json.loads(source)
        story["assets"] = {"sky": {"path": "assets/sky.png", "sha256": "0" * 64}}
        source = json.dumps(story)
    elif case == "notice_nul":
        notices = "private prose\x00"
    else:
        notices = "\U0001f30c" * (1024 * 1024 // 4 + 1)
    response = await client.post(
        f"{path}/revisions",
        headers=headers,
        json={
            "base_revision_id": base["id"],
            "idempotency_key": str(uuid4()),
            "story_json": source,
            "notices": notices,
        },
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == code
    assert "private prose" not in response.text
    assert (await client.get(path, headers=headers)).json()["head_revision_id"] == (
        project["head_revision_id"]
    )


@pytest.mark.anyio
async def test_database_commit_failure_hides_source_and_retry_does_not_duplicate(
    narrative_env, caplog
):
    client, factory, _ = narrative_env
    headers, project, base, path = await blank_project(client)
    canary = "ORIGINAL_PROSE_CANARY_night_lantern_6294"
    story = json.loads(base["story_json"])
    story["nodes"]["opening"]["text"] = canary
    payload = {
        "base_revision_id": base["id"],
        "idempotency_key": str(uuid4()),
        "story_json": json.dumps(story),
        "notices": canary,
    }
    engine = factory.kw["bind"].sync_engine

    def arm(connection, _cursor, statement, _parameters, _context, _many):
        if "insert into narrative_revisions" in statement.lower():
            connection.info["narrative_commit_fault"] = True

    def fail_commit(connection):
        if connection.info.pop("narrative_commit_fault", False):
            raise DBAPIError("COMMIT", {"story": canary}, Exception(canary))

    event.listen(engine, "before_cursor_execute", arm)
    event.listen(engine, "commit", fail_commit)
    try:
        failed = await client.post(f"{path}/revisions", headers=headers, json=payload)
    finally:
        event.remove(engine, "before_cursor_execute", arm)
        event.remove(engine, "commit", fail_commit)
    assert failed.status_code == 503
    assert canary not in failed.text
    assert canary not in caplog.text
    assert (await client.get(path, headers=headers)).json()["head_revision_id"] == (
        project["head_revision_id"]
    )
    retried = await client.post(f"{path}/revisions", headers=headers, json=payload)
    assert retried.status_code == 201
    assert retried.json()["revision_number"] == 2


@pytest.mark.anyio
async def test_revision_audits_are_transactional_idempotent_and_do_not_contain_prose(narrative_env):
    client, _, _ = narrative_env
    headers, _, base, path = await blank_project(client)
    payload = {
        "base_revision_id": base["id"],
        "idempotency_key": str(uuid4()),
        "story_json": base["story_json"],
        "notices": "private author notes canary",
    }
    assert (
        await client.post(f"{path}/revisions", headers=headers, json=payload)
    ).status_code == 201
    assert (
        await client.post(f"{path}/revisions", headers=headers, json=payload)
    ).status_code == 201
    payload["idempotency_key"] = str(uuid4())
    assert (
        await client.post(f"{path}/revisions", headers=headers, json=payload)
    ).status_code == 409
    audit = await client.get("/v1/audit-events", headers=headers)
    narrative = [row for row in audit.json() if row["action"].startswith("narrative.")]
    assert sorted(row["action"] for row in narrative) == [
        "narrative.project_created",
        "narrative.revision_conflicted",
        "narrative.revision_created",
    ]
    assert all(row["actor_user_id"] for row in narrative)
    assert "private author notes canary" not in audit.text
    assert "A new story begins" not in audit.text


@pytest.mark.anyio
async def test_oidc_roles_scope_and_archiving_apply_to_projects_and_revisions(
    narrative_env, oidc_auth
):
    client, _, _ = narrative_env
    owner = {"Authorization": "Bearer " + oidc_auth("story-owner")}
    headers, project, base, path = await blank_project(client, auth_headers=owner)
    for subject, role in [
        ("story-viewer", "viewer"),
        ("story-member", "member"),
        ("story-admin", "admin"),
    ]:
        added = await client.post(
            f"/v1/workspaces/{project['tenant_id']}/members",
            headers=owner,
            json={
                "oidc_issuer": "https://keycloak.example/realms/flintgraph",
                "oidc_subject": subject,
                "role": role,
            },
        )
        assert added.status_code == 201

    def user(subject):
        return {
            "X-Tenant-ID": project["tenant_id"],
            "Authorization": "Bearer " + oidc_auth(subject),
        }

    assert (await client.get(path, headers=user("story-viewer"))).status_code == 200
    create = {"name": "Forbidden", "idempotency_key": str(uuid4())}
    assert (
        await client.post("/v1/narrative/projects", headers=user("story-viewer"), json=create)
    ).status_code == 403
    edit = {
        "base_revision_id": base["id"],
        "idempotency_key": str(uuid4()),
        "story_json": base["story_json"],
        "notices": "",
    }
    assert (
        await client.post(f"{path}/revisions", headers=user("story-viewer"), json=edit)
    ).status_code == 403
    archive = {"base_revision_id": base["id"], "archived": True}
    assert (
        await client.post(f"{path}/archive", headers=user("story-member"), json=archive)
    ).status_code == 403
    assert (await client.get(path, headers=user("outsider"))).status_code == 403
    _foreign_headers, _, foreign_base, foreign_path = await blank_project(
        client, name="Another workspace", auth_headers=owner
    )
    assert (await client.get(foreign_path, headers=headers)).status_code == 404
    assert (
        await client.get(f"{path}/revisions/{foreign_base['id']}", headers=headers)
    ).status_code == 404
    assert (
        await client.post(
            f"{path}/revisions",
            headers=user("story-member"),
            json={**edit, "base_revision_id": foreign_base["id"]},
        )
    ).status_code == 404
    archived = await client.post(f"{path}/archive", headers=user("story-admin"), json=archive)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert (await client.get(path, headers=headers)).status_code == 404
    assert (
        await client.get(path + "?include_archived=true", headers=user("story-viewer"))
    ).status_code == 200
    assert (
        await client.post(f"{path}/revisions", headers=user("story-member"), json=edit)
    ).status_code == 409
    restored = await client.post(
        f"{path}/archive", headers=user("story-admin"), json={**archive, "archived": False}
    )
    assert restored.status_code == 200 and restored.json()["archived_at"] is None
    assert (
        await client.post(f"{path}/revisions", headers=user("story-member"), json=edit)
    ).status_code == 201


@pytest.mark.anyio
async def test_postgres_rejects_revision_overwrite_and_delete(narrative_env):
    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("Deployed PostgreSQL trigger qualification requires explicit owned DB URL")
    headers, _, base, path = await blank_project(client)
    for mutation in [
        update(NarrativeRevision).values(story_json="tampered"),
        delete(NarrativeRevision),
    ]:
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(mutation.where(NarrativeRevision.id == base["id"]))
            await session.rollback()
    assert (await client.get(f"{path}/revisions/{base['id']}", headers=headers)).json() == base


@pytest.mark.anyio
async def test_project_and_revision_lists_are_scoped_bounded_and_do_not_expand_source(
    narrative_env,
):
    client, _, _ = narrative_env
    headers, project, base, path = await blank_project(client)
    for name in ["Second story", "Third story"]:
        assert (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": name, "idempotency_key": str(uuid4())},
            )
        ).status_code == 201
    first_page = await client.get("/v1/narrative/projects?limit=1", headers=headers)
    assert first_page.status_code == 200 and len(first_page.json()) == 1
    second_page = await client.get(
        "/v1/narrative/projects",
        headers=headers,
        params={"limit": 2, "before_id": first_page.json()[0]["id"]},
    )
    assert len(second_page.json()) == 2
    assert len({row["id"] for row in first_page.json() + second_page.json()}) == 3
    assert (
        await client.get("/v1/narrative/projects?limit=101", headers=headers)
    ).status_code == 422
    accepted = (
        await client.post(
            f"{path}/revisions",
            headers=headers,
            json={
                "base_revision_id": base["id"],
                "idempotency_key": str(uuid4()),
                "story_json": base["story_json"],
                "notices": "Private revision notes",
            },
        )
    ).json()
    revisions = await client.get(f"{path}/revisions?limit=1", headers=headers)
    assert revisions.status_code == 200
    assert [row["id"] for row in revisions.json()] == [accepted["id"]]
    assert "story_json" not in revisions.json()[0] and "notices" not in revisions.json()[0]
    assert "Private revision notes" not in revisions.text
    earlier = await client.get(
        f"{path}/revisions", headers=headers, params={"before_id": accepted["id"], "limit": 1}
    )
    assert [row["id"] for row in earlier.json()] == [base["id"]]
    _other_headers, other, _, _ = await blank_project(client, name="Another workspace cursor")
    assert (
        await client.get(
            "/v1/narrative/projects", headers=headers, params={"before_id": other["id"]}
        )
    ).status_code == 404
    assert project["id"] != other["id"]


@pytest.mark.anyio
async def test_project_and_revision_idempotency_keys_cannot_replace_work(narrative_env):
    client, _, _ = narrative_env
    headers, project, base, path = await blank_project(client)
    key = str(uuid4())
    payload = {"name": "Stable project", "idempotency_key": key}
    first = await client.post("/v1/narrative/projects", headers=headers, json=payload)
    retry = await client.post(
        "/v1/narrative/projects", headers=headers, json={**payload, "name": "  Stable project  "}
    )
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    changed = await client.post(
        "/v1/narrative/projects", headers=headers, json={**payload, "name": "Different project"}
    )
    assert changed.status_code == 409
    write = {
        "base_revision_id": base["id"],
        "idempotency_key": str(uuid4()),
        "story_json": base["story_json"],
        "notices": "",
    }
    accepted = await client.post(f"{path}/revisions", headers=headers, json=write)
    assert accepted.status_code == 201
    semantic_retry = await client.post(
        f"{path}/revisions",
        headers=headers,
        json={**write, "story_json": json.dumps(json.loads(base["story_json"]), indent=2)},
    )
    assert semantic_retry.json() == accepted.json()
    changed_write = await client.post(
        f"{path}/revisions", headers=headers, json={**write, "notices": "Changed content"}
    )
    assert changed_write.status_code == 409
    assert (await client.get(path, headers=headers)).json()["head_revision_id"] == accepted.json()[
        "id"
    ]
    missing_base = {key: value for key, value in write.items() if key != "base_revision_id"}
    assert (
        await client.post(f"{path}/revisions", headers=headers, json=missing_base)
    ).status_code == 422
    assert len((await client.get(f"{path}/revisions", headers=headers)).json()) == 2
    assert project["id"] != first.json()["id"]


@pytest.mark.anyio
async def test_revoked_membership_denies_previously_readable_project(narrative_env, oidc_auth):
    from sqlalchemy import select

    client, factory, _ = narrative_env
    owner = {"Authorization": "Bearer " + oidc_auth("revoked-owner")}
    headers, project, base, path = await blank_project(client, auth_headers=owner)
    assert (await client.get(path, headers=headers)).status_code == 200
    async with factory() as session:
        user_id = await session.scalar(select(User.id).where(User.oidc_subject == "revoked-owner"))
        await session.execute(
            update(WorkspaceMembership)
            .where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.tenant_id == UUID(project["tenant_id"]),
            )
            .values(status=WorkspaceMembershipStatus.DISABLED)
        )
        await session.commit()
    assert (await client.get(path, headers=headers)).status_code == 403
    assert (await client.get(f"{path}/revisions/{base['id']}", headers=headers)).status_code == 403
    assert (
        await client.get(path, headers={"X-Tenant-ID": project["tenant_id"]})
    ).status_code == 401


@pytest.mark.anyio
async def test_postgres_independent_authors_serialize_and_preserve_both_edits(
    narrative_env, oidc_auth
):
    from sqlalchemy import select

    from flint_graph.infrastructure.db.models import NarrativeProject

    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("Real lock/concurrency proof requires the explicit owned PostgreSQL URL")
    owner = {"Authorization": "Bearer " + oidc_auth("concurrent-owner")}
    headers, project, base, path = await blank_project(client, auth_headers=owner)
    author_headers = []
    for subject in ["concurrent-one", "concurrent-two"]:
        assert (
            await client.post(
                f"/v1/workspaces/{project['tenant_id']}/members",
                headers=owner,
                json={
                    "oidc_issuer": "https://keycloak.example/realms/flintgraph",
                    "oidc_subject": subject,
                    "role": "member",
                },
            )
        ).status_code == 201
        actor = {
            "X-Tenant-ID": project["tenant_id"],
            "Authorization": "Bearer " + oidc_auth(subject),
        }
        assert (await client.get(path, headers=actor)).status_code == 200
        author_headers.append(actor)
    tasks = []
    async with factory() as locker:
        await locker.scalar(
            select(NarrativeProject)
            .where(NarrativeProject.id == UUID(project["id"]))
            .with_for_update()
        )
        try:
            for index, actor in enumerate(author_headers):
                story = json.loads(base["story_json"])
                story["nodes"]["opening"]["text"] = f"Independent author {index + 1}."
                tasks.append(
                    asyncio.create_task(
                        client.post(
                            f"{path}/revisions",
                            headers=actor,
                            json={
                                "base_revision_id": base["id"],
                                "idempotency_key": str(uuid4()),
                                "story_json": json.dumps(story),
                                "notices": "",
                            },
                        )
                    )
                )
            async with asyncio.timeout(5):
                while True:
                    async with factory() as observer:
                        waiting = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname=current_database() AND wait_event_type='Lock' "
                                "AND query LIKE '%narrative_projects%' AND pid<>pg_backend_pid()"
                            )
                        )
                    if waiting == 2:
                        break
                    await asyncio.sleep(0.02)
        finally:
            await locker.rollback()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    assert sorted(result.status_code for result in results) == [201, 409]
    accepted = next(result.json() for result in results if result.status_code == 201)
    conflict = next(result.json() for result in results if result.status_code == 409)
    conflict_id = conflict["errors"][0]["conflict_revision_id"]
    recovered = (await client.get(f"{path}/revisions/{conflict_id}", headers=headers)).json()
    assert recovered["conflicted"] is True
    assert recovered["observed_head_revision_id"] == accepted["id"]
    assert (await client.get(path, headers=headers)).json()["head_revision_id"] == accepted["id"]
    texts = {
        json.loads(row["story_json"])["nodes"]["opening"]["text"] for row in [accepted, recovered]
    }
    assert texts == {"Independent author 1.", "Independent author 2."}
    assert len((await client.get(f"{path}/revisions", headers=headers)).json()) == 3


@pytest.mark.anyio
async def test_postgres_composite_foreign_keys_reject_cross_project_head_and_parent(narrative_env):
    client, factory, backend = narrative_env
    if backend != "postgres":
        pytest.skip("Deployed PostgreSQL composite foreign-key qualification")
    headers, project, base, path = await blank_project(client)
    other = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Other project", "idempotency_key": str(uuid4())},
        )
    ).json()
    async with factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(NarrativeProject)
                .where(NarrativeProject.id == UUID(project["id"]))
                .values(head_revision_id=UUID(other["head_revision_id"]))
            )
        await session.rollback()
    async with factory() as session:
        forged = NarrativeRevision(
            tenant_id=UUID(project["tenant_id"]),
            project_id=UUID(project["id"]),
            revision_number=2,
            parent_revision_id=UUID(other["head_revision_id"]),
            observed_head_revision_id=UUID(base["id"]),
            conflicted=True,
            idempotency_key=uuid4(),
            request_hash="0" * 64,
            story_json=base["story_json"],
            notices="",
            content_hash=base["content_hash"],
            author_user_id=UUID(base["author_user_id"]),
        )
        session.add(forged)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    assert (await client.get(path, headers=headers)).json()["head_revision_id"] == base["id"]
