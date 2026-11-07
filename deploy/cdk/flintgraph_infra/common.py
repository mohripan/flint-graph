"""How both servers set themselves up on first boot."""

from flintgraph_infra.config import InfraConfig

GPU_FIRST_BOOT_LIMIT_MINUTES = 300
# Lightsail has no instance role. An operator puts a key here, then starts provisioning.
CONTROL_KEY_FILE = "/root/.aws/credentials"


def provisioning(config: InfraConfig, role: str, extra_vars: dict[str, str]) -> list[str]:
    """First boot installs a service that runs Ansible until it succeeds. Installing the GPU
    driver reboots the machine partway through, so this must survive a reboot."""
    arguments = " ".join(
        f"-e {key}={value}" for key, value in {"flintgraph_role": role, **extra_vars}.items()
    )
    commands: list[str] = []
    if role == "gpu":
        # Before anything that can fail, so a broken first boot cannot run up a bill for days.
        # An instance launched by CloudFormation is running and billing from this moment.
        commands.append(f"shutdown -h +{GPU_FIRST_BOOT_LIMIT_MINUTES}")
    commands += [
        "set -eu",
        "apt-get update -y",
        "apt-get install -y ansible-core git",
        "cat > /usr/local/sbin/flintgraph-provision <<'SCRIPT'",
        "#!/bin/bash",
        "set -euo pipefail",
        "export HOME=/root",
        f"ansible-pull -U {config.repo_url} -C {config.git_ref} -d /opt/flintgraph/src "
        f"-i localhost, {arguments} deploy/ansible/site.yml",
        "touch /var/lib/flintgraph-provisioned",
        "SCRIPT",
        "chmod 700 /usr/local/sbin/flintgraph-provision",
        "cat > /etc/systemd/system/flintgraph-provision.service <<'UNIT'",
        "[Unit]",
        "Description=Set up this FlintGraph server",
        "After=network-online.target",
        "Wants=network-online.target",
        "ConditionPathExists=!/var/lib/flintgraph-provisioned",
        *([f"ConditionPathExists={CONTROL_KEY_FILE}"] if role == "control" else []),
        "[Service]",
        "Type=oneshot",
        "ExecStart=/usr/local/sbin/flintgraph-provision",
        "TimeoutStartSec=3h",
        "[Install]",
        "WantedBy=multi-user.target",
        "UNIT",
        "systemctl daemon-reload",
        "systemctl enable flintgraph-provision.service",
        # Not --now and waited for: cloud-init should finish, and the service logs to the journal.
        "systemctl start --no-block flintgraph-provision.service",
    ]
    return commands
