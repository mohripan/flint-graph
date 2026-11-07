"""What both servers share: how they are set up on first boot, and how they are locked down."""

from aws_cdk import aws_ec2 as ec2

from flintgraph_infra.config import InfraConfig

GPU_FIRST_BOOT_LIMIT_MINUTES = 300


def provisioning(config: InfraConfig, role: str, extra_vars: dict[str, str]) -> ec2.UserData:
    """First boot installs a service that runs Ansible until it succeeds. Installing the GPU
    driver reboots the machine partway through, so this must survive a reboot."""
    arguments = " ".join(
        f"-e {key}={value}" for key, value in {"flintgraph_role": role, **extra_vars}.items()
    )
    user_data = ec2.UserData.for_linux()
    if role == "gpu":
        # Before anything that can fail, so a broken first boot cannot run up a bill for days.
        # An instance launched by CloudFormation is running and billing from this moment.
        user_data.add_commands(f"shutdown -h +{GPU_FIRST_BOOT_LIMIT_MINUTES}")
    user_data.add_commands(
        "set -euo pipefail",
        "apt-get update -y",
        "apt-get install -y ansible-core git",
        "cat > /usr/local/sbin/flintgraph-provision <<'SCRIPT'",
        "#!/bin/bash",
        "set -euo pipefail",
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
    )
    return user_data


def require_imdsv2(instance: ec2.Instance) -> None:
    """Hop limit 2, so a pod can reach the instance role: the GPU controller needs it."""
    instance.instance.add_property_override(
        "MetadataOptions",
        {"HttpEndpoint": "enabled", "HttpTokens": "required", "HttpPutResponseHopLimit": 2},
    )
