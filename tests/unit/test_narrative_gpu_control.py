"""Every decision about the GPU machine, with no machine (#197, #198, ADR 0070)."""

from datetime import UTC, datetime, timedelta

import pytest

from flint_graph.application.services.narrative_gpu_control import (
    InstanceView,
    Policy,
    Seen,
    decide,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
POLICY = Policy(
    idle=timedelta(minutes=5),
    max_session=timedelta(hours=4),
    boot_grace=timedelta(minutes=10),
    silent=timedelta(minutes=5),
    daily_cap=timedelta(hours=8),
)


def seen(state="running", *, age=timedelta(minutes=30), work=0, beat=timedelta(seconds=5), **more):
    return Seen(
        now=NOW,
        instance=InstanceView(state, NOW - age if state == "running" else None),
        work=work,
        last_beat=NOW - beat if beat is not None else None,
        idle_since=more.get("idle_since"),
        used_today=more.get("used", timedelta(hours=1)),
    )


def test_a_stopped_machine_with_nothing_to_do_stays_stopped():
    step = decide(seen("stopped"), POLICY)
    assert (step.state, step.action) == ("stopped", None)


def test_queued_work_starts_a_stopped_machine():
    step = decide(seen("stopped", work=1), POLICY)
    assert (step.state, step.action) == ("starting", "start")


def test_the_daily_cap_keeps_it_stopped_and_says_why():
    step = decide(seen("stopped", work=1, used=timedelta(hours=8)), POLICY)
    assert (step.state, step.action, step.detail, step.alarm) == (
        "unavailable",
        None,
        "daily_cap",
        "daily_cap",
    )


def test_no_cap_means_no_limit():
    plain = Policy(daily_cap=None)
    assert decide(seen("stopped", work=1, used=timedelta(hours=23)), plain).action == "start"


def test_a_running_machine_reaching_the_cap_stops():
    step = decide(seen(work=1, used=timedelta(hours=8)), POLICY)
    assert (step.action, step.detail) == ("stop", "daily_cap")


@pytest.mark.parametrize(
    ("instance", "state"),
    [("pending", "starting"), ("stopping", "stopping"), ("shutting-down", "stopping")],
)
def test_a_machine_already_changing_is_left_alone(instance, state):
    step = decide(seen(instance, work=1), POLICY)
    assert (step.state, step.action) == (state, None)


def test_a_job_arriving_during_a_stop_waits_and_then_wakes_it_again():
    assert decide(seen("stopping", work=1), POLICY).action is None
    assert decide(seen("stopped", work=1), POLICY).action == "start"


def test_no_machine_is_said_plainly():
    step = decide(seen("missing", work=1), POLICY)
    assert (step.state, step.detail, step.alarm) == (
        "unavailable",
        "instance_missing",
        "instance_missing",
    )


def test_work_keeps_it_up_and_clears_the_idle_clock():
    step = decide(seen(work=2, idle_since=NOW - timedelta(minutes=4)), POLICY)
    assert (step.state, step.action, step.idle_since) == ("ready", None, None)


def test_the_idle_clock_starts_when_the_work_runs_out():
    step = decide(seen(), POLICY)
    assert (step.state, step.action, step.idle_since) == ("ready", None, NOW)


def test_it_stays_up_until_the_idle_period_has_passed():
    almost = seen(idle_since=NOW - timedelta(minutes=4, seconds=59))
    assert decide(almost, POLICY).action is None
    assert decide(seen(idle_since=NOW - timedelta(minutes=5)), POLICY).action == "stop"


def test_a_session_past_its_limit_stops_even_if_busy_and_raises_the_alarm():
    step = decide(seen(work=3, age=timedelta(hours=4)), POLICY)
    assert (step.action, step.alarm) == ("stop", "session_too_long")


def test_a_silent_machine_gets_time_to_boot_then_is_stopped():
    assert decide(seen(work=1, age=timedelta(minutes=9), beat=None), POLICY).action is None
    late = decide(seen(work=1, age=timedelta(minutes=10), beat=None), POLICY)
    assert (late.action, late.alarm) == ("stop", "heartbeat_stale")
    stale = decide(seen(work=1, beat=timedelta(minutes=6)), POLICY)
    assert (stale.action, stale.alarm) == ("stop", "heartbeat_stale")
