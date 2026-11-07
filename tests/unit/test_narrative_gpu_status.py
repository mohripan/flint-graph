"""What people are told about the GPU comes from what the machine is doing (ADR 0069)."""

from datetime import UTC, datetime, timedelta

import pytest

from flint_graph.application.services.narrative_gpu import expected_kinds, gpu_view
from flint_graph.config import Settings
from flint_graph.infrastructure.db.narrative_gpu_models import NarrativeGpuStatus

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def row(name, seconds_ago=5, state="ready", detail=None):
    return NarrativeGpuStatus(
        name=name, state=state, detail=detail, updated_at=NOW - timedelta(seconds=seconds_ago)
    )


def view(*rows, sleeps=True, expected=("image", "voice"), wake_seconds=150):
    return gpu_view(rows, now=NOW, expected=expected, sleeps=sleeps, wake_seconds=wake_seconds)


def test_every_worker_up_means_nothing_waits():
    seen = view(row("image"), row("voice"))
    assert (seen.state, seen.waiting) == ("ready", ())


def test_a_worker_that_stopped_beating_counts_as_gone():
    assert view(row("image"), row("voice", seconds_ago=61)).waiting == ("voice",)
    assert view(row("image"), row("voice", seconds_ago=59)).waiting == ()


def test_work_this_server_does_not_run_is_not_waited_for():
    assert view(row("image"), expected=("image",)).state == "ready"


def test_a_laptop_never_promises_a_wake_up():
    seen = view(sleeps=False)
    assert (seen.state, seen.detail, seen.wake_seconds) == ("off", None, None)
    assert seen.waiting == ("image", "voice")


def test_a_stopped_machine_is_asleep():
    seen = view(row("controller", state="stopped"))
    assert (seen.state, seen.wake_seconds) == ("asleep", 150)


@pytest.mark.parametrize(
    ("controller", "detail", "state"),
    [
        ("starting", None, "starting"),
        ("ready", None, "starting"),
        ("stopping", None, "stopping"),
        ("unavailable", "no_capacity", "unavailable"),
        ("unavailable", "daily_cap", "unavailable"),
    ],
)
def test_the_controller_says_what_the_machine_is_doing(controller, detail, state):
    seen = view(row("controller", state=controller, detail=detail))
    assert (seen.state, seen.detail) == (state, detail)


def test_the_machine_being_up_with_a_worker_still_loading_is_starting():
    assert view(row("image"), row("controller", state="ready")).state == "starting"


@pytest.mark.parametrize("controller", [(), (row("controller", 301, state="stopped"),)])
def test_with_no_controller_nothing_can_wake_it_and_that_is_what_it_says(controller):
    seen = view(*controller)
    assert (seen.state, seen.detail) == ("unavailable", "controller_down")


def test_a_timestamp_read_back_without_a_zone_still_compares():
    naive = NarrativeGpuStatus(
        name="image", state="ready", updated_at=(NOW - timedelta(seconds=5)).replace(tzinfo=None)
    )
    assert view(naive, expected=("image",)).state == "ready"


def test_a_server_expects_only_what_it_is_set_up_to_run():
    assert expected_kinds(Settings(env="test")) == ()
    on = Settings(env="test").model_copy(
        update={
            "narrative_image_generation_enabled": True,
            "narrative_voice_generation_enabled": True,
            "narrative_assistant_provider": "ollama",
        }
    )
    assert expected_kinds(on) == ("image", "voice", "assistant")
    hosted = on.model_copy(update={"narrative_assistant_provider": "anthropic"})
    assert "assistant" not in expected_kinds(hosted)
