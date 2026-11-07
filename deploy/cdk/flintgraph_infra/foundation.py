"""The always-on Lightsail server, the key it uses to reach AWS, and the budget alarm."""

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lightsail as lightsail
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from flintgraph_infra.common import provisioning
from flintgraph_infra.config import DEFAULT_VPC_CIDR, GPU_TAG_KEY, GPU_TAG_VALUE, InfraConfig

SERVER_NAME = "flintgraph-control"
PORT = lightsail.CfnInstance.PortProperty


class FoundationStack(Stack):
    def __init__(self, scope: Construct, name: str, *, config: InfraConfig, **kwargs: Any) -> None:
        super().__init__(scope, name, **kwargs)
        self.config = config

        self.control = lightsail.CfnInstance(
            self,
            "Control",
            instance_name=SERVER_NAME,
            blueprint_id=config.control_blueprint,
            bundle_id=config.control_bundle,
            availability_zone=config.zone,
            user_data="\n".join(provisioning(config, "control", {})),
            networking=lightsail.CfnInstance.NetworkingProperty(ports=self._ports()),
        )
        address = lightsail.CfnStaticIp(
            self, "PublicAddress", static_ip_name=SERVER_NAME, attached_to=SERVER_NAME
        )
        address.add_dependency(self.control)
        # Every project lives on this server's disk, and there are no backups, so deleting the
        # stack must not delete the server. Removing it is a deliberate act in the console.
        self.control.apply_removal_policy(RemovalPolicy.RETAIN)
        address.apply_removal_policy(RemovalPolicy.RETAIN)

        self._key_user()

        # The GPU server reads this to find the cluster, over the private network.
        ssm.StringParameter(
            self,
            "K3sUrl",
            parameter_name="/flintgraph/k3s/url",
            string_value=f"https://{self.control.attr_private_ip_address}:6443",
        )

        self._budget()
        CfnOutput(self, "PublicIp", value=address.attr_ip_address)

    def _ports(self) -> list[PORT]:
        public = [
            PORT(from_port=port, to_port=port, protocol="tcp", cidrs=["0.0.0.0/0"])
            for port in (80, 443)
        ]
        # Only Lightsail's own browser console can reach SSH.
        console = PORT(
            from_port=22, to_port=22, protocol="tcp", cidr_list_aliases=["lightsail-connect"]
        )
        # k3s control traffic and the encrypted network between the two servers.
        from_gpu = [
            PORT(from_port=port, to_port=port, protocol=protocol, cidrs=[DEFAULT_VPC_CIDR])
            for port, protocol in ((6443, "tcp"), (10250, "tcp"), (51820, "udp"))
        ]
        return [*public, console, *from_gpu]

    def _key_user(self) -> None:
        """Lightsail has no instance role, so this server needs a key. It is created by hand and
        never here, because CloudFormation would keep its secret in the stack."""
        user = iam.User(self, "ControlUser", user_name=SERVER_NAME)
        # Only this server may wake the GPU, and only the tagged instance (ADR 0070).
        user.add_to_policy(iam.PolicyStatement(actions=["ec2:DescribeInstances"], resources=["*"]))
        user.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:StartInstances", "ec2:StopInstances"],
                resources=[self.format_arn(service="ec2", resource="instance", resource_name="*")],
                conditions={"StringEquals": {f"aws:ResourceTag/{GPU_TAG_KEY}": GPU_TAG_VALUE}},
            )
        )

        def parameters(path: str) -> str:
            return self.format_arn(service="ssm", resource="parameter", resource_name=path)

        user.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
                resources=[parameters("flintgraph/*"), parameters("flintgraph")],
            )
        )
        user.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:PutParameter"], resources=[parameters("flintgraph/k3s/*")]
            )
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
