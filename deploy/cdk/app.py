#!/usr/bin/env python3
"""The AWS resources for FlintGraph (ADR 0077).

`cdk synth` needs no AWS credentials and creates nothing. Read docs/runbooks/aws-deployment.md
before running anything else, because `cdk deploy` starts spending money.
"""

import os

import aws_cdk as cdk
from flintgraph_infra.config import InfraConfig
from flintgraph_infra.foundation import FoundationStack
from flintgraph_infra.gpu import GpuStack

app = cdk.App()
config = InfraConfig.from_context(app.node.try_get_context)
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT") or None, region=config.region)
FoundationStack(app, "FlintGraphFoundation", config=config, env=env, termination_protection=True)
# Separate, because it cannot be created until AWS grants a GPU quota.
GpuStack(app, "FlintGraphGpu", config=config, env=env)
for stack in app.node.children:
    cdk.Tags.of(stack).add("project", "flintgraph")
cdk.Validations.of(app).acknowledge(
    cdk.Acknowledgment(
        id="CloudFormation-Validate::W9010",
        reason="Pinned on purpose: one Region, and a rebuilt server must get the same image.",
    ),
    cdk.Acknowledgment(
        id="Annotation::@aws-cdk/aws-ec2:noSubnetRouteTableId",
        reason="The default subnet's routes are not ours to change, so nothing reads them.",
    ),
)
app.synth()
