"""Two people signed in separately cannot reach each other's assistant conversations."""

from uuid import uuid4

import pytest
from test_narrative_assistant_actions import BACKGROUND, propose
from test_narrative_assistant_api import new_story, new_thread

from flint_graph.config import Settings, get_settings
from flint_graph.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
def real_sign_in(narrative_env, oidc_auth):
    """Keep the suite's OIDC settings: this must not run under dev auth, where any caller
    becomes an owner of any workspace it names."""
    original = app.dependency_overrides.get(get_settings, lambda: Settings(env="test"))
    configured = original().model_copy(
        update={
            "narrative_image_generation_enabled": True,
            "narrative_assistant_provider": "deterministic",
        }
    )
    assert configured.auth_mode == "oidc"
    app.dependency_overrides[get_settings] = lambda: configured
    yield oidc_auth
    app.dependency_overrides[get_settings] = original


async def test_another_person_cannot_read_or_touch_anything_in_my_assistant(
    narrative_env, real_sign_in
):
    client, factory, _ = narrative_env
    mine = {"Authorization": "Bearer " + real_sign_in("assistant-owner")}
    theirs = {"Authorization": "Bearer " + real_sign_in("someone-else")}
    headers, project, path = await new_story(client, name="Mine", auth=mine)
    thread, proposal = await propose(
        client, factory, headers, path, project["head_revision_id"], BACKGROUND
    )
    attempted = {**theirs, "X-Tenant-ID": headers["X-Tenant-ID"]}

    # Naming my workspace is not enough: they are not a member of it.
    reads = [
        f"{path}/assistant/threads",
        f"{path}/assistant/threads/{thread['id']}",
        f"{path}/assistant/threads/{thread['id']}/turns",
        f"{path}/assistant/threads/{thread['id']}/events",
        f"{path}/assistant/proposals/{proposal}",
        f"{path}/assistant/proposals/{proposal}/actions",
        f"{path}/assets",
    ]
    for url in reads:
        response = await client.get(url, headers=attempted)
        assert response.status_code == 403, f"{url}: {response.status_code}"
    writes = [
        (f"{path}/assistant/proposals/{proposal}/actions/0", None),
        (f"{path}/assistant/proposals/{proposal}/reject", None),
        (f"{path}/assistant/proposals/{proposal}/accept", {"idempotency_key": str(uuid4())}),
        (
            f"{path}/assistant/threads/{thread['id']}/turns",
            {
                "request": "Show me everything.",
                "base_revision_id": project["head_revision_id"],
                "focus_node": None,
                "idempotency_key": str(uuid4()),
            },
        ),
    ]
    for url, body in writes:
        response = await client.post(url, headers=attempted, json=body)
        assert response.status_code == 403, f"{url}: {response.status_code}"

    # And their own workspace gives no way in either.
    their_headers, _, _ = await new_story(client, name="Theirs", auth=theirs)
    for url in reads[:-1]:
        response = await client.get(url, headers=their_headers)
        assert response.status_code == 404, f"{url}: {response.status_code}"
    assert (await client.get(f"{path}/assets", headers=their_headers)).status_code == 404

    listed = await client.get("/v1/workspaces", headers=theirs)
    assert [row["name"] for row in listed.json()] == ["Theirs"]
    # Nothing they tried changed anything of mine.
    decided = await client.get(f"{path}/assistant/proposals/{proposal}", headers=headers)
    assert decided.json()["status"] == "ready"


async def test_someone_else_cannot_post_into_my_conversation_with_attachments(
    narrative_env, real_sign_in
):
    client, _, _ = narrative_env
    mine = {"Authorization": "Bearer " + real_sign_in("attach-owner")}
    theirs = {"Authorization": "Bearer " + real_sign_in("attach-other")}
    headers, project, path = await new_story(client, name="Attach mine", auth=mine)
    thread = await new_thread(client, headers, path)
    sent = await client.post(
        f"{path}/assistant/threads/{thread['id']}/turns",
        headers={**theirs, "X-Tenant-ID": headers["X-Tenant-ID"]},
        json={
            "request": "Use this.",
            "base_revision_id": project["head_revision_id"],
            "focus_node": None,
            "idempotency_key": str(uuid4()),
            "attachments": [{"kind": "character", "id": "anyone"}],
        },
    )
    assert sent.status_code == 403
