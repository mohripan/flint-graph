"""A generation card says what will be made, and its price is what is charged (ADR 0068)."""

import json

import pytest
from test_access_credits_api import joined_owner, me
from test_access_invitations_api import invite_mode
from test_narrative_assistant_actions import actions, press, propose, queue, with_character
from test_narrative_assistant_api import ask, new_thread, work
from test_narrative_characters_api import queue_job, run_job
from test_narrative_package_v2_api import configure, v2  # noqa: F401

from flint_graph.application.services.narrative_assistant_actions import dispatch_actions
from flint_graph.config import get_settings
from flint_graph.main import app

pytestmark = pytest.mark.anyio

SPRITE = {
    "op": "generate_character_images",
    "character": "mira",
    "appearance": "white hair, blue coat",
    "character_type": "woman",
    "framing": "full_body",
    "transparent": True,
}
PORTRAIT = {**SPRITE, "transparent": False, "framing": "portrait"}
EXPRESSIONS = {"op": "generate_expressions", "character": "mira", "expressions": ["happy", "sad"]}
CG = {"op": "generate_cg", "characters": ["mira"], "description": "Mira rings the bell"}
VOICE = {"op": "generate_voice", "character": "mira", "lines": ["hello", "sound"]}
CHILD = {"op": "start_child_session", "title": "Map", "task": "Draw the routes."}
BACKGROUND = {"op": "generate_backgrounds", "description": "rainy street"}
MUSIC = {"op": "generate_music", "description": "gentle piano, slow", "seconds": 90}


async def story_with_a_picture(client, factory, store, base, headers):
    """A saved story where Mira has lines and an approved picture, as CGs and expressions need."""
    project = (await client.get(base, headers=headers)).json()
    head = await with_character(client, headers, base, project)
    job, payload = await queue_job(client, headers, base, character="mira", count=1)
    assert (await run_job(factory, store, payload))["status"] == "completed"
    [picture] = (await client.get(f"{base}/image-jobs/{job['id']}", headers=headers)).json()[
        "assets"
    ]
    await client.post(f"{base}/assets/{picture['id']}/approve", headers=headers)
    return project, head


def price(status, quote) -> int:
    return sum(
        status["prices"][part["item"]]["credits"] * part["quantity"] for part in quote["parts"]
    )


async def test_every_card_costs_exactly_what_it_says(v2, oidc_auth):  # noqa: F811
    client, factory, store, owner, project = v2
    base, _ = await project("Cards", schema="2")
    invite_mode(
        narrative_image_max_active_jobs_per_workspace=50,
        narrative_voice_generation_enabled=True,
        narrative_voice_max_active_jobs_per_workspace=50,
        narrative_music_generation_enabled=True,
        narrative_assistant_provider="deterministic",
        narrative_assistant_max_active_turns_per_workspace=50,
    )
    await joined_owner(client, oidc_auth, owner, credits=5000)
    _, head = await story_with_a_picture(client, factory, store, base, owner)
    expected = {
        "sprite": ("image.high_res", 4),
        "portrait": ("image.standard", 4),
        "background": ("image.standard", 4),
        "expressions": ("image.expression", 2),
        "cg": ("image.cg", 4),
        "voice": ("voice.kokoro-82m", 2),
        "child": ("assistant.deterministic", 1),
        "music": ("music.track", 1),
    }
    operations = {
        "sprite": SPRITE,
        "portrait": PORTRAIT,
        "background": BACKGROUND,
        "expressions": EXPRESSIONS,
        "cg": CG,
        "voice": VOICE,
        "child": CHILD,
        "music": MUSIC,
    }
    for name, operation in operations.items():
        _, proposal = await propose(client, factory, owner, base, head, operation)
        [card] = await actions(client, owner, base, proposal)
        part = card["quote"]["parts"][0]
        assert (part["item"], part["quantity"]) == expected[name], name
        before = await me(client, owner)
        pressed = await press(client, owner, base, proposal)
        assert pressed.status_code == 202, f"{name}: {pressed.text}"
        after = await me(client, owner)
        assert before["credits"] - after["credits"] == price(before, card["quote"]), name


async def test_a_card_says_what_it_will_make_in_the_creators_words(v2, oidc_auth):  # noqa: F811
    client, factory, store, owner, project = v2
    base, _ = await project("Words", schema="2")
    configure(narrative_voice_generation_enabled=True, narrative_assistant_provider="deterministic")
    _, head = await story_with_a_picture(client, factory, store, base, owner)
    _, proposal = await propose(
        client, factory, owner, base, head, SPRITE, CG, VOICE, BACKGROUND, MUSIC
    )
    sprite, cg, voice, background, music = await actions(client, owner, base, proposal)

    facts = lambda card: [fact["text"] for fact in card["quote"]["facts"]]  # noqa: E731
    assert sprite["quote"]["kind"] == "Sprite of Mira"
    assert sprite["quote"]["title"] == "white hair, blue coat"
    assert facts(sprite) == [
        "Animagine XL 4.0",
        "4 options",
        "Transparent sprite",
        "High resolution",
    ]
    assert (sprite["quote"]["button"], sprite["quote"]["opens"]) == (
        "Generate sprites",
        "characters",
    )
    assert cg["quote"]["title"] == "Mira rings the bell"
    assert facts(cg) == ["Animagine XL 4.0", "4 options", "Widescreen", "Mira"]
    assert voice["quote"]["kind"] == "Voice of Mira"
    assert voice["quote"]["title"].endswith("and 1 more")
    assert "Good" in voice["quote"]["title"]
    assert facts(voice) == ["Kokoro-82M", "2 lines"]
    assert music["quote"]["title"] == "gentle piano, slow"
    assert facts(music) == ["ACE-Step 3.5B", "1 minute 30 seconds", "Instrumental, loops"]
    assert music["quote"]["button"] == "Generate music"
    assert (background["quote"]["button"], background["quote"]["opens"]) == (
        "Generate backgrounds",
        "assets",
    )


async def test_a_press_the_queue_held_back_still_costs_what_the_card_said(
    v2,  # noqa: F811
    oidc_auth,
):
    """The worker has no request, so it must carry this deployment's prices itself."""
    client, factory, store, owner, project = v2
    base, _ = await project("Prices", schema="2")
    invite_mode(
        access_credit_prices={"image.standard": 7}, narrative_assistant_provider="deterministic"
    )
    await joined_owner(client, oidc_auth, owner, credits=500)
    configured = app.dependency_overrides[get_settings]()
    created = (await client.get(base, headers=owner)).json()
    _, proposal = await propose(
        client, factory, owner, base, created["head_revision_id"], BACKGROUND
    )
    [card] = await actions(client, owner, base, proposal)
    before = await me(client, owner)
    assert price(before, card["quote"]) == 28
    await queue(factory, owner, created, proposal)
    assert await dispatch_actions(factory, settings=configured, store=store) == 1
    assert before["credits"] - (await me(client, owner))["credits"] == 28


async def test_open_mode_charges_nothing_even_through_the_worker(v2, oidc_auth):  # noqa: F811
    client, factory, store, owner, project = v2
    base, _ = await project("Open", schema="2")
    invite_mode(narrative_assistant_provider="deterministic")
    await joined_owner(client, oidc_auth, owner, credits=100)
    configure(access_mode="open")
    configured = app.dependency_overrides[get_settings]()
    created = (await client.get(base, headers=owner)).json()
    _, proposal = await propose(
        client, factory, owner, base, created["head_revision_id"], BACKGROUND
    )
    await queue(factory, owner, created, proposal)
    assert await dispatch_actions(factory, settings=configured, store=store) == 1
    invite_mode()
    assert (await me(client, owner))["credits"] == 100


async def test_a_chat_message_costs_credits_and_says_so(v2, oidc_auth):  # noqa: F811
    client, factory, _, owner, project = v2
    base, _ = await project("Chat", schema="2")
    invite_mode(narrative_assistant_provider="ollama")
    await joined_owner(client, oidc_auth, owner, credits=3)
    status = await me(client, owner)
    assert status["assistant_item"] == "assistant.ollama"
    created = (await client.get(base, headers=owner)).json()
    thread = await new_thread(client, owner, base)
    head = created["head_revision_id"]
    first = await ask(client, owner, base, thread, head)
    assert first.status_code == 202, first.text
    assert (await me(client, owner))["credits"] == 1
    await work(factory, first.json()["id"], json.dumps({"reply": "Hi.", "proposal": None}))
    second = await ask(client, owner, base, thread, head)
    assert second.status_code == 402, "out of credits means no more GPU time"
