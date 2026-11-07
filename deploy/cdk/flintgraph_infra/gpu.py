"""The GPU server. It runs its first boot to set itself up, and after that the controller on the
always-on server starts and stops it (ADR 0070)."""

from typing import Any

from aws_cdk import CfnOutput, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from flintgraph_infra.common import provisioning, require_imdsv2
from flintgraph_infra.config import GPU_TAG_KEY, GPU_TAG_VALUE, InfraConfig
from flintgraph_infra.foundation import FoundationStack


class GpuStack(Stack):
    def __init__(
        self,
        scope: Construct,
        name: str,
        *,
        foundation: FoundationStack,
        config: InfraConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, name, **kwargs)
        self.gpu = ec2.Instance(
            self,
            "Gpu",
            instance_type=ec2.InstanceType(config.gpu_instance_type),
            machine_image=ec2.MachineImage.generic_linux({config.region: config.ami}),
            vpc=foundation.vpc,
            # The public subnet gives it an address while running, which is released when it
            # stops, so it costs nothing asleep and needs no NAT gateway to reach the internet.
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=foundation.gpu_security_group,
            role=foundation.gpu_role,
            # Shutting down from inside must stop it, not delete it: the watchdog relies on this.
            instance_initiated_shutdown_behavior=ec2.InstanceInitiatedShutdownBehavior.STOP,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        config.gpu_root_gb,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                    ),
                )
            ],
            user_data=provisioning(config, "gpu", {}),
            user_data_causes_replacement=False,
        )
        require_imdsv2(self.gpu)
        Tags.of(self.gpu).add(GPU_TAG_KEY, GPU_TAG_VALUE)
        CfnOutput(self, "GpuInstanceId", value=self.gpu.instance_id)
