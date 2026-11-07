"""Everything a deployment may choose. This repository is public, so no account ID or email."""

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any

# Canonical Ubuntu 24.04 for amd64 in ap-southeast-2. Pinned, not looked up: a lookup would
# replace a running server whenever Canonical publishes a newer image.
UBUNTU_AMI = "ami-01e91e94accc42eec"
GPU_TAG_KEY = "flintgraph-gpu"
GPU_TAG_VALUE = "1"
# Lightsail's own network, which it peers with the Region's default VPC, the only one it can.
LIGHTSAIL_CIDR = "172.26.0.0/16"
DEFAULT_VPC_CIDR = "172.31.0.0/16"


@dataclass(frozen=True)
class InfraConfig:
    region: str = "ap-southeast-2"
    # Both servers share a zone, so traffic between them stays free.
    zone: str = "ap-southeast-2a"
    ami: str = UBUNTU_AMI
    repo_url: str = "https://github.com/mohripan/flint-graph.git"
    git_ref: str = "master"
    # 2 GB of memory, 60 GB of disk, an address and 1.5 TB of traffic, at a flat price.
    control_bundle: str = "small_3_2"
    control_blueprint: str = "ubuntu_24_04"
    # The cheapest GPU that runs what is deployed. Poses and training refuse it: they need native
    # bf16, which a T4 lacks, so adding them means changing this (ADR 0077).
    gpu_instance_type: str = "g4dn.xlarge"
    gpu_root_gb: int = 70
    # The project's default VPC and its subnet in `zone`, passed with `-c` when deploying. These
    # placeholders let `cdk synth` work without AWS, and a deployment using them simply fails.
    default_vpc_id: str = "vpc-00000000000000000"
    default_subnet_id: str = "subnet-00000000000000000"
    monthly_budget_usd: int = 50
    alert_email: str | None = None

    @classmethod
    def from_context(cls, get: Callable[[str], Any]) -> "InfraConfig":
        """Any field can be set with `cdk synth -c field=value`."""
        chosen: dict[str, Any] = {}
        for field in fields(cls):
            value = get(field.name)
            if value is not None:
                default = field.default
                chosen[field.name] = int(value) if isinstance(default, int) else str(value)
        return cls(**chosen)
