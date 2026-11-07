"""The EC2 side: one tagged machine, and only start, stop and describe (ADR 0070)."""

from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from flint_graph.application.services.narrative_gpu_control import NoCapacity
from flint_graph.infrastructure.narrative_gpu_ec2 import Ec2GpuInstance

pytestmark = pytest.mark.anyio
LAUNCHED = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def refused(code):
    return ClientError({"Error": {"Code": code, "Message": "no"}}, "operation")


class FakeEc2:
    def __init__(self, instances=None, refuse=()):
        self.instances = instances if instances is not None else [machine()]
        self.refuse = list(refuse)
        self.calls = []

    def describe_instances(self, Filters):
        self.filters = Filters
        return {"Reservations": [{"Instances": self.instances}]}

    def start_instances(self, InstanceIds):
        self.calls.append(("start", InstanceIds))
        if self.refuse:
            raise refused(self.refuse.pop(0))

    def stop_instances(self, InstanceIds):
        self.calls.append(("stop", InstanceIds))
        if self.refuse:
            raise refused(self.refuse.pop(0))

    def modify_instance_attribute(self, InstanceId, InstanceType):
        self.calls.append(("type", InstanceId, InstanceType["Value"]))


def machine(state="stopped", kind="g5.xlarge", identity="i-1"):
    return {
        "InstanceId": identity,
        "State": {"Name": state},
        "LaunchTime": LAUNCHED,
        "InstanceType": kind,
    }


def gpu(client, **types):
    return Ec2GpuInstance(client, tag_key="role", tag_value="flint-gpu", **types)


async def test_it_only_looks_for_the_tagged_machine():
    client = FakeEc2([machine("running")])
    view = await gpu(client).describe()
    assert (view.state, view.launched_at) == ("running", LAUNCHED)
    assert {"Name": "tag:role", "Values": ["flint-gpu"]} in client.filters


async def test_no_match_or_two_matches_touch_nothing():
    for found in ([], [machine(), machine(identity="i-2")]):
        client = FakeEc2(found)
        assert (await gpu(client).describe()).state == "missing"
        await gpu(client).stop()
        assert client.calls == []
        with pytest.raises(NoCapacity):
            await gpu(client).start()
        assert client.calls == []


async def test_start_and_stop_are_for_that_one_machine():
    client = FakeEc2()
    await gpu(client).start()
    await gpu(client).stop()
    assert client.calls == [("start", ["i-1"]), ("stop", ["i-1"])]


@pytest.mark.parametrize("action", ["start", "stop"])
async def test_asking_a_machine_to_do_what_it_is_doing_is_not_a_failure(action):
    client = FakeEc2(refuse=["IncorrectInstanceState"])
    await getattr(gpu(client), action)()


async def test_no_capacity_is_its_own_answer():
    client = FakeEc2(refuse=["InsufficientInstanceCapacity"])
    with pytest.raises(NoCapacity):
        await gpu(client).start()


async def test_it_falls_back_to_the_second_type_when_the_first_has_no_capacity():
    client = FakeEc2(refuse=["InsufficientInstanceCapacity"])
    await gpu(client, instance_type="g5.xlarge", fallback_type="g6.xlarge").start()
    assert client.calls == [
        ("start", ["i-1"]),
        ("type", "i-1", "g6.xlarge"),
        ("start", ["i-1"]),
    ]


async def test_with_both_types_refused_the_job_keeps_waiting():
    client = FakeEc2(refuse=["InsufficientInstanceCapacity"] * 2)
    with pytest.raises(NoCapacity):
        await gpu(client, instance_type="g5.xlarge", fallback_type="g6.xlarge").start()


async def test_it_goes_back_to_the_usual_type_next_time():
    client = FakeEc2([machine(kind="g6.xlarge")])
    await gpu(client, instance_type="g5.xlarge", fallback_type="g6.xlarge").start()
    assert client.calls == [("type", "i-1", "g5.xlarge"), ("start", ["i-1"])]


async def test_any_other_refusal_is_not_mistaken_for_capacity():
    client = FakeEc2(refuse=["UnauthorizedOperation"])
    with pytest.raises(ClientError):
        await gpu(client).start()
