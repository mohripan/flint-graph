"""The GPU server. It runs its first boot to set itself up, and after that the controller on the
always-on server starts and stops it (ADR 0070). It lives in the default VPC, because that is the
only network Lightsail can reach privately."""

from typing import Any

from aws_cdk import CfnOutput, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

from flintgraph_infra.common import provisioning
from flintgraph_infra.config import GPU_TAG_KEY, GPU_TAG_VALUE, LIGHTSAIL_CIDR, InfraConfig


class GpuStack(Stack):
    def __init__(self, scope: Construct, name: str, *, config: InfraConfig, **kwargs: Any) -> None:
        super().__init__(scope, name, **kwargs)
        vpc = ec2.Vpc.from_vpc_attributes(
            self,
            "DefaultVpc",
            vpc_id=config.default_vpc_id,
            availability_zones=[config.zone],
            public_subnet_ids=[config.default_subnet_id],
        )

        # No port 22, and nothing from the internet: shell access is through Session Manager.
        security_group = ec2.SecurityGroup(
            self,
            "GpuSecurityGroup",
            vpc=vpc,
            description="FlintGraph GPU server, no public inbound",
        )
        for port, why in (
            (ec2.Port.tcp(10250), "k3s to the kubelet"),
            (ec2.Port.udp(51820), "The encrypted network between the servers"),
        ):
            security_group.add_ingress_rule(ec2.Peer.ipv4(LIGHTSAIL_CIDR), port, why)

        role = iam.Role(
            self,
            "GpuRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ],
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    self.format_arn(
                        service="ssm", resource="parameter", resource_name="flintgraph/k3s/*"
                    )
                ],
            )
        )

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(*provisioning(config, "gpu", {}))

        self.gpu = ec2.Instance(
            self,
            "Gpu",
            instance_type=ec2.InstanceType(config.gpu_instance_type),
            machine_image=ec2.MachineImage.generic_linux({config.region: config.ami}),
            vpc=vpc,
            # The public subnet gives it an address while running, which is released when it
            # stops, so it costs nothing asleep and needs no NAT gateway to reach the internet.
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=security_group,
            role=role,
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
            user_data=user_data,
            user_data_causes_replacement=False,
        )
        # IMDSv2 only, and no pod can use the role: see deploy/k8s/base/network-policy.yaml.
        self.gpu.instance.add_property_override(
            "MetadataOptions",
            {"HttpEndpoint": "enabled", "HttpTokens": "required", "HttpPutResponseHopLimit": 1},
        )
        Tags.of(self.gpu).add(GPU_TAG_KEY, GPU_TAG_VALUE)
        CfnOutput(self, "GpuInstanceId", value=self.gpu.instance_id)
