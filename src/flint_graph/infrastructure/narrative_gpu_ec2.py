"""The GPU machine as EC2 sees it. Only start, stop and describe, on one tagged instance."""

from asyncio import to_thread
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from flint_graph.application.services.narrative_gpu_control import InstanceView, NoCapacity

_CAPACITY = {"InsufficientInstanceCapacity", "InstanceLimitExceeded"}
# Asking a machine to do what it is already doing is not a failure.
_ALREADY = {"IncorrectInstanceState"}
_LIVE = ["pending", "running", "stopping", "stopped"]


@dataclass
class Ec2GpuInstance:
    client: Any
    tag_key: str
    tag_value: str
    # The usual type, and one to try when the cloud has none of it.
    instance_type: str | None = None
    fallback_type: str | None = None

    def _found(self) -> list[dict[str, Any]]:
        pages = self.client.describe_instances(
            Filters=[
                {"Name": f"tag:{self.tag_key}", "Values": [self.tag_value]},
                {"Name": "instance-state-name", "Values": _LIVE},
            ]
        )
        return [item for page in pages["Reservations"] for item in page["Instances"]]

    def _one(self) -> dict[str, Any] | None:
        found = self._found()
        # Two matches means a mistake in the tags, and guessing could stop the wrong machine.
        return found[0] if len(found) == 1 else None

    def _describe(self) -> InstanceView:
        item = self._one()
        if item is None:
            return InstanceView("missing")
        return InstanceView(item["State"]["Name"], item.get("LaunchTime"))

    def _start(self) -> None:
        item = self._one()
        if item is None:
            raise NoCapacity
        identity = item["InstanceId"]
        kinds: list[str | None] = [
            kind for kind in (self.instance_type, self.fallback_type) if kind
        ]
        for kind in kinds or [None]:
            if kind is not None and item.get("InstanceType") != kind:
                self.client.modify_instance_attribute(
                    InstanceId=identity, InstanceType={"Value": kind}
                )
                item = {**item, "InstanceType": kind}
            try:
                self.client.start_instances(InstanceIds=[identity])
                return
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code")
                if code in _ALREADY:
                    return
                if code not in _CAPACITY:
                    raise
        raise NoCapacity

    def _stop(self) -> None:
        item = self._one()
        if item is None:
            return
        try:
            self.client.stop_instances(InstanceIds=[item["InstanceId"]])
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in _ALREADY:
                raise

    async def describe(self) -> InstanceView:
        return await to_thread(self._describe)

    async def start(self) -> None:
        await to_thread(self._start)

    async def stop(self) -> None:
        await to_thread(self._stop)
