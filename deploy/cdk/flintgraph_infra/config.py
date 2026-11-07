"""Everything a deployment may choose. This repository is public, so no account ID or email."""

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any

# Canonical Ubuntu 24.04 for amd64 in ap-southeast-2. Pinned, not looked up: a lookup would
# replace a running server whenever Canonical publishes a newer image.
UBUNTU_AMI = "ami-01e91e94accc42eec"
GPU_TAG_KEY = "flintgraph-gpu"
GPU_TAG_VALUE = "1"


@dataclass(frozen=True)
class InfraConfig:
    region: str = "ap-southeast-2"
    zone: str = "ap-southeast-2a"
    ami: str = UBUNTU_AMI
    repo_url: str = "https://github.com/mohripan/flint-graph.git"
    git_ref: str = "master"
    # The cheapest 2 GB server the Free Plan can launch. t3a.small is $1.90 a month less but
    # needs the Paid Plan, and Lightsail refused its 2 GB plan on this account (ADR 0077).
    control_instance_type: str = "t3.small"
    control_root_gb: int = 20
    # Disks can grow but not shrink, so this starts small.
    data_gb: int = 20
    # The cheapest GPU that runs what is deployed. Poses and training refuse it: they need native
    # bf16, which a T4 lacks, so adding them means changing this (ADR 0077).
    gpu_instance_type: str = "g4dn.xlarge"
    gpu_root_gb: int = 70
    # Where people reach the Studio, which sign-in must return them to exactly.
    site_url: str = "https://flintgraph.digital"
    # The free name for the public address, which keeps working beside it.
    fallback_site_url: str = "https://54-253-96-189.sslip.io"
    sign_in_prefix: str = "flintgraph-studio"
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
