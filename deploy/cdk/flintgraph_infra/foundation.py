"""The network, the always-on server, its data disk, sign-in and the budget alarm."""

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Size, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from flintgraph_infra.common import provisioning, require_imdsv2
from flintgraph_infra.config import GPU_TAG_KEY, GPU_TAG_VALUE, InfraConfig

# k3s control traffic and the encrypted network between the two servers.
K3S_API = ec2.Port.tcp(6443)
KUBELET = ec2.Port.tcp(10250)
WIREGUARD = ec2.Port.udp(51820)


class FoundationStack(Stack):
    def __init__(self, scope: Construct, name: str, *, config: InfraConfig, **kwargs: Any) -> None:
        super().__init__(scope, name, **kwargs)
        self.config = config

        # One public subnet and no NAT gateway, which would cost more than the server does.
        # The CIDR must stay clear of k3s's own 10.42.0.0/16 and 10.43.0.0/16.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/24"),
            availability_zones=[config.zone],
            nat_gateways=0,
            restrict_default_security_group=False,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=25
                )
            ],
        )

        # No port 22 anywhere: shell access is through Systems Manager Session Manager.
        self.control_security_group = ec2.SecurityGroup(
            self, "ControlSecurityGroup", vpc=self.vpc, description="FlintGraph always-on server"
        )
        self.gpu_security_group = ec2.SecurityGroup(
            self, "GpuSecurityGroup", vpc=self.vpc, description="FlintGraph GPU server, no inbound"
        )
        for port in (ec2.Port.tcp(80), ec2.Port.tcp(443)):
            self.control_security_group.add_ingress_rule(ec2.Peer.any_ipv4(), port, "Public web")
        for port in (K3S_API, KUBELET, WIREGUARD):
            self.control_security_group.add_ingress_rule(
                self.gpu_security_group, port, "From the GPU server"
            )
        for port in (KUBELET, WIREGUARD):
            self.gpu_security_group.add_ingress_rule(
                self.control_security_group, port, "From the always-on server"
            )

        self.control_role = self._node_role("ControlRole")
        self.gpu_role = self._node_role("GpuRole")
        # Only this server may wake the GPU, and only the tagged instance (ADR 0070).
        self.control_role.add_to_policy(
            iam.PolicyStatement(actions=["ec2:DescribeInstances"], resources=["*"])
        )
        self.control_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:StartInstances", "ec2:StopInstances"],
                resources=[self.format_arn(service="ec2", resource="instance", resource_name="*")],
                conditions={"StringEquals": {f"aws:ResourceTag/{GPU_TAG_KEY}": GPU_TAG_VALUE}},
            )
        )
        self._allow_parameters(self.control_role, read="/flintgraph/*", write="/flintgraph/k3s/*")
        self._allow_parameters(self.gpu_role, read="/flintgraph/k3s/*")

        # Survives the server being replaced, and even this stack being deleted.
        self.data_volume = ec2.Volume(
            self,
            "DataVolume",
            availability_zone=config.zone,
            size=Size.gibibytes(config.data_gb),
            volume_type=ec2.EbsDeviceVolumeType.GP3,
            encrypted=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.control = ec2.Instance(
            self,
            "Control",
            instance_type=ec2.InstanceType(config.control_instance_type),
            machine_image=ec2.MachineImage.generic_linux({config.region: config.ami}),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=self.control_security_group,
            role=self.control_role,
            # Unlimited mode bills for sustained CPU without warning. Slower is better than that.
            credit_specification=ec2.CpuCredits.STANDARD,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        config.control_root_gb,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                    ),
                )
            ],
            user_data=provisioning(
                config,
                "control",
                {"flintgraph_data_volume": self.data_volume.volume_id},
            ),
            user_data_causes_replacement=False,
        )
        require_imdsv2(self.control)
        self.control.instance.add_property_override("DisableApiTermination", True)
        ec2.CfnVolumeAttachment(
            self,
            "DataVolumeAttachment",
            device="/dev/sdf",
            instance_id=self.control.instance_id,
            volume_id=self.data_volume.volume_id,
        )
        address = ec2.CfnEIP(
            self, "PublicAddress", domain="vpc", instance_id=self.control.instance_id
        )

        # The GPU server reads this to find the cluster.
        ssm.StringParameter(
            self,
            "K3sUrl",
            parameter_name="/flintgraph/k3s/url",
            string_value=f"https://{self.control.instance_private_ip}:6443",
        )

        self._sign_in()
        self._budget()
        CfnOutput(self, "PublicIp", value=address.attr_public_ip)
        CfnOutput(self, "ControlInstanceId", value=self.control.instance_id)

    def _node_role(self, name: str) -> iam.Role:
        return iam.Role(
            self,
            name,
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ],
        )

    def _allow_parameters(self, role: iam.Role, *, read: str, write: str | None = None) -> None:
        def arn(path: str) -> str:
            return self.format_arn(service="ssm", resource="parameter", resource_name=path[1:])

        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
                resources=[arn(read), arn(read.removesuffix("/*"))],
            )
        )
        if write:
            role.add_to_policy(
                iam.PolicyStatement(actions=["ssm:PutParameter"], resources=[arn(write)])
            )

    def _sign_in(self) -> None:
        """Who someone is. Whether they may use the Studio is the invitation check in the API, so
        anyone may create an account here and still get nowhere without an invitation."""
        users = cognito.UserPool(
            self,
            "Users",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            password_policy=cognito.PasswordPolicy(min_length=12),
            # Free for up to 10,000 people a month.
            feature_plan=cognito.FeaturePlan.LITE,
            removal_policy=RemovalPolicy.RETAIN,
        )
        users.add_domain(
            "SignInPage",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=self.config.sign_in_prefix),
        )
        studio = users.add_client(
            "Studio",
            # The browser cannot keep a secret. It proves itself with PKCE instead.
            generate_secret=False,
            prevent_user_existence_errors=True,
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[self.config.site_url],
                logout_urls=[self.config.site_url],
            ),
        )
        region = self.config.region
        issuer = f"https://cognito-idp.{region}.amazonaws.com/{users.user_pool_id}"
        CfnOutput(self, "SignInIssuer", value=issuer)
        CfnOutput(self, "SignInClientId", value=studio.user_pool_client_id)
        CfnOutput(
            self,
            "SignInLogoutUrl",
            value=f"https://{self.config.sign_in_prefix}.auth.{region}.amazoncognito.com/logout",
        )

    def _budget(self) -> None:
        email = self.config.alert_email
        subscribers = (
            [budgets.CfnBudget.SubscriberProperty(address=email, subscription_type="EMAIL")]
            if email
            else None
        )
        alerts = [
            budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator="GREATER_THAN",
                    notification_type=kind,
                    threshold=threshold,
                    threshold_type="PERCENTAGE",
                ),
                subscribers=subscribers,
            )
            for kind, threshold in (("ACTUAL", 50), ("ACTUAL", 80), ("FORECASTED", 100))
        ]
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=self.config.monthly_budget_usd, unit="USD"
                ),
            ),
            notifications_with_subscribers=alerts if email else None,
        )
