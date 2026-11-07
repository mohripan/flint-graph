"""Everything a deployment may choose. This repository is public, so no account ID or email."""

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any

# Canonical Ubuntu 24.04 for amd64 in ap-southeast-2. Pinned, not looked up: a lookup would
# replace a running server whenever Canonical publishes a newer image.
UBUNTU_AMI = "ami-01e91e94accc42eec"
GPU_TAG_KEY = "flintgraph-gpu"
GPU_TAG_VALUE = "1"
BACKUP_TAG_KEY = "flintgraph-backup"


@dataclass(frozen=True)
class InfraConfig:
    region: str = "ap-southeast-2"
    # g5.xlarge is only in zones a and c, so stay in a to keep it as the fallback.
    zone: str = "ap-southeast-2a"
    ami: str = UBUNTU_AMI
    repo_url: str = "https://github.com/mohripan/flint-graph.git"
    git_ref: str = "master"
    control_instance_type: str = "t3a.medium"
    control_root_gb: int = 20
    data_gb: int = 40
    gpu_instance_type: str = "g6.xlarge"
    gpu_root_gb: int = 70
    monthly_budget_usd: int = 75
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
