"""Generation suggested in chat is a durable, accepted, idempotent project action."""

import asyncio
import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from test_narrative_assistant_api import (
    ask,
    new_story,
    new_thread,
    turns,
    work,
)

from flint_graph.config import get_settings
from flint_graph.main import app


@pytest.fixture
def assistant_settings(narrative_env):
    from flint_graph.config import Settings

    settings = Settings(env="test")
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


async def image_proposal(client, factory, headers, path, project, operations):
    thread = await new_thread(client, headers, path)
    turn = (await ask(client, headers, path, thread, project["head_revision_id"])).json()
    await work(
        factory,
        turn["id"],
        json.dumps(
            {
                "reply": "Review these pictures.",
                "proposal": {
                    "summary": "Pictures",
                    "operations": operations,
                },
            }
        ),
    )
    return (await turns(client, headers, path, thread))[0]["proposal"]["id"]


@pytest.mark.anyio
async def test_distinct_suggestions_keep_distinct_jobs_even_with_identical_descriptions(
    narrative_env, assistant_settings
):
    client, factory, _ = narrative_env
    app.dependency_overrides[get_settings] = lambda: assistant_settings.model_copy(
        update={"narrative_image_generation_enabled": True}
    )
    headers, project, path = await new_story(client)
    proposal = await image_proposal(
        client,
        factory,
        headers,
        path,
        project,
        [
            {"op": "generate_backgrounds", "description": "courtyard at night"},
            {"op": "generate_backgrounds", "description": "courtyard at night"},
        ],
    )
    accepted = await client.post(
        f"{path}/assistant/proposals/{proposal}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    assert accepted.status_code == 201, accepted.text
    url = f"{path}/assistant/proposals/{proposal}/image-actions"
    first = await client.post(f"{url}/0", headers=headers)
    second = await client.post(f"{url}/1", headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert (
        len((await client.get(f"{path}/assets/background-jobs", headers=headers)).json()["jobs"])
        == 2
    )


@pytest.mark.anyio
async def test_postgres_concurrent_clicks_resolve_to_one_job(narrative_env, assistant_settings):
    client, factory, _ = narrative_env
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock qualification")
    app.dependency_overrides[get_settings] = lambda: assistant_settings.model_copy(
        update={"narrative_image_generation_enabled": True}
    )
    headers, project, path = await new_story(client)
    proposal = await image_proposal(
        client,
        factory,
        headers,
        path,
        project,
        [{"op": "generate_backgrounds", "description": "courtyard at night"}],
    )
    await client.post(
        f"{path}/assistant/proposals/{proposal}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    url = f"{path}/assistant/proposals/{proposal}/image-actions/0"
    responses = await asyncio.gather(*(client.post(url, headers=headers) for _ in range(3)))
    assert all(response.status_code == 202 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert (
        len((await client.get(f"{path}/assets/background-jobs", headers=headers)).json()["jobs"])
        == 1
    )


@pytest.mark.anyio
async def test_background_action_survives_navigation_and_replays_without_another_job(
    narrative_env, assistant_settings
):
    client, factory, _ = narrative_env
    app.dependency_overrides[get_settings] = lambda: assistant_settings.model_copy(
        update={"narrative_image_generation_enabled": True}
    )
    headers, project, path = await new_story(client)
    proposal = await image_proposal(
        client,
        factory,
        headers,
        path,
        project,
        [{"op": "generate_backgrounds", "description": "school courtyard at night"}],
    )
    actions = f"{path}/assistant/proposals/{proposal}/image-actions"
    assert (await client.get(actions, headers=headers)).json() == [{"index": 0, "job": None}]
    assert (await client.post(f"{actions}/0", headers=headers)).status_code == 409
    assert (
        await client.post(
            f"{path}/assistant/proposals/{proposal}/accept",
            headers=headers,
            json={"idempotency_key": str(uuid4())},
        )
    ).status_code == 201
    first = await client.post(f"{actions}/0", headers=headers)
    assert first.status_code == 202, first.text
    second = await client.post(f"{actions}/0", headers=headers)
    assert second.status_code == 202 and second.json()["id"] == first.json()["id"]
    restored = (await client.get(actions, headers=headers)).json()
    assert restored[0]["job"]["id"] == first.json()["id"]
    assert restored[0]["job"]["status"] == "queued"
    listed = (await client.get(f"{path}/assets/background-jobs", headers=headers)).json()["jobs"]
    assert [job["id"] for job in listed] == [first.json()["id"]]
    _, _, other = await new_story(client, name="Other story")
    assert (
        await client.get(f"{other}/assistant/proposals/{proposal}/image-actions", headers=headers)
    ).status_code == 404
    assert (await client.post(f"{actions}/9", headers=headers)).status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("hires", [None, False])
async def test_character_action_defaults_transparent_sprites_to_hires_but_keeps_opt_out(
    narrative_env, assistant_settings, hires
):
    client, factory, _ = narrative_env
    app.dependency_overrides[get_settings] = lambda: assistant_settings.model_copy(
        update={"narrative_image_generation_enabled": True}
    )
    headers, project, path = await new_story(client)
    action = {
        "op": "generate_character_images",
        "character": "ren",
        "appearance": "white hair, blue coat",
        "character_type": "boy",
        "framing": "full_body",
        "transparent": True,
    }
    if hires is not None:
        action["hires"] = hires
    proposal = await image_proposal(
        client,
        factory,
        headers,
        path,
        project,
        [{"op": "upsert_character", "id": "ren", "name": "Ren"}, action],
    )
    assert (
        await client.post(
            f"{path}/assistant/proposals/{proposal}/accept",
            headers=headers,
            json={"idempotency_key": str(uuid4())},
        )
    ).status_code == 201
    url = f"{path}/assistant/proposals/{proposal}/image-actions/1"
    started = await client.post(url, headers=headers)
    assert started.status_code == 202, started.text
    data = started.json()
    assert data["transparent"] is True
    assert (data["hires"] is not None) is (hires is None)
    assert (await client.post(url, headers=headers)).json()["id"] == data["id"]


@pytest.mark.anyio
async def test_pre_fix_matching_background_jobs_are_recovered_without_mutating_or_starting(
    narrative_env, assistant_settings
):
    client, factory, _ = narrative_env
    app.dependency_overrides[get_settings] = lambda: assistant_settings.model_copy(
        update={"narrative_image_generation_enabled": True}
    )
    headers, project, path = await new_story(client)
    proposal = await image_proposal(
        client,
        factory,
        headers,
        path,
        project,
        [{"op": "generate_backgrounds", "description": "courtyard at night"}],
    )
    from flint_graph.infrastructure.db.models import (
        NarrativeAssistantProposal,
        NarrativeAssistantTurn,
        NarrativeImageJob,
    )
    from flint_graph.narrative.assistant.prompts import PINNED_PROMPTS

    async with factory() as session:
        record = await session.get(NarrativeAssistantProposal, UUID(proposal))
        turn = await session.get(NarrativeAssistantTurn, record.turn_id)
        turn.prompt_sha256 = PINNED_PROMPTS["narrative-assistant/v2"]
        await session.commit()
    await client.post(
        f"{path}/assistant/proposals/{proposal}/accept",
        headers=headers,
        json={"idempotency_key": str(uuid4())},
    )
    created = []
    for _ in range(2):
        response = await client.post(
            f"{path}/assets/background-jobs",
            headers=headers,
            json={"description": "courtyard at night", "count": 4, "idempotency_key": str(uuid4())},
        )
        assert response.status_code == 202, response.text
        created.append(response.json()["id"])
    async with factory() as session:
        record = await session.get(NarrativeAssistantProposal, UUID(proposal))
        for index, job_id in enumerate(created):
            job = await session.get(NarrativeImageJob, UUID(job_id))
            job.created_at = record.decided_at + timedelta(seconds=index + 1)
        await session.commit()
    actions = f"{path}/assistant/proposals/{proposal}/image-actions"
    assert (await client.get(actions, headers=headers)).json()[0]["job"]["id"] == created[-1]
    assert (await client.post(f"{actions}/0", headers=headers)).json()["id"] == created[-1]
    assert (
        len((await client.get(f"{path}/assets/background-jobs", headers=headers)).json()["jobs"])
        == 2
    )
