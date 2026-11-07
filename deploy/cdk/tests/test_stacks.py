"""What must hold about the AWS resources, checked on the synthesized templates without AWS."""

import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from flintgraph_infra.config import GPU_TAG_KEY, InfraConfig
from flintgraph_infra.foundation import FoundationStack
from flintgraph_infra.gpu import GpuStack


def build(**changes):
    app = cdk.App()
    config = InfraConfig(**changes)
    env = cdk.Environment(region=config.region)
    foundation = FoundationStack(app, "Foundation", config=config, env=env)
    gpu = GpuStack(app, "Gpu", foundation=foundation, config=config, env=env)
    return Template.from_stack(foundation), Template.from_stack(gpu)


@pytest.fixture(scope="module")
def templates():
    return build()


def only_instance(template):
    rows = template.find_resources("AWS::EC2::Instance")
    assert len(rows) == 1
    return next(iter(rows.values()))["Properties"]


def test_there_is_no_nat_gateway_because_it_would_cost_more_than_the_server(templates):
    foundation, gpu = templates
    foundation.resource_count_is("AWS::EC2::NatGateway", 0)
    gpu.resource_count_is("AWS::EC2::NatGateway", 0)


def test_only_web_traffic_is_open_to_the_internet_and_nothing_to_the_gpu(templates):
    foundation, _ = templates
    groups = foundation.find_resources("AWS::EC2::SecurityGroup")
    rules = foundation.find_resources("AWS::EC2::SecurityGroupIngress")
    inline = [
        rule
        for group in groups.values()
        for rule in group["Properties"].get("SecurityGroupIngress", [])
    ]
    standalone = [rule["Properties"] for rule in rules.values()]
    public = [rule for rule in inline + standalone if rule.get("CidrIp") == "0.0.0.0/0"]
    assert sorted(rule["FromPort"] for rule in public) == [80, 443]
    assert not any(rule.get("FromPort") == 22 for rule in inline + standalone), "no SSH"
    for group in groups.values():
        if "no inbound" in group["Properties"]["GroupDescription"]:
            assert "SecurityGroupIngress" not in group["Properties"]


def test_servers_require_imdsv2_with_a_hop_limit_a_pod_can_use(templates):
    for template in templates:
        options = only_instance(template)["MetadataOptions"]
        assert options["HttpTokens"] == "required"
        assert options["HttpPutResponseHopLimit"] == 2


def test_disks_are_encrypted_gp3(templates):
    foundation, gpu = templates
    for template in (foundation, gpu):
        ebs = only_instance(template)["BlockDeviceMappings"][0]["Ebs"]
        assert ebs["Encrypted"] is True
        assert ebs["VolumeType"] == "gp3"
    foundation.has_resource_properties("AWS::EC2::Volume", {"Encrypted": True, "VolumeType": "gp3"})


def test_the_data_disk_outlives_the_server_and_the_stack(templates):
    foundation, _ = templates
    volume = next(iter(foundation.find_resources("AWS::EC2::Volume").values()))
    assert volume["DeletionPolicy"] == "Retain"
    assert volume["UpdateReplacePolicy"] == "Retain"


def test_there_are_no_backups_because_the_owner_chose_none(templates):
    foundation, _ = templates
    foundation.resource_count_is("AWS::DLM::LifecyclePolicy", 0)


def test_the_always_on_server_cannot_run_up_a_surprise_cpu_bill(templates):
    foundation, _ = templates
    properties = only_instance(foundation)
    assert properties["CreditSpecification"] == {"CPUCredits": "standard"}
    assert properties["DisableApiTermination"] is True
    assert properties["InstanceType"] == "t3a.medium"


def test_the_gpu_stops_rather_than_terminates_when_it_shuts_itself_down(templates):
    _, gpu = templates
    properties = only_instance(gpu)
    assert properties["InstanceInitiatedShutdownBehavior"] == "stop"
    assert properties["InstanceType"] == "g4dn.xlarge"
    tags = {tag["Key"]: tag["Value"] for tag in properties["Tags"]}
    assert tags[GPU_TAG_KEY] == "1"
    gpu.resource_count_is("AWS::EC2::EIP", 0)


def test_only_the_tagged_gpu_can_be_started_or_stopped(templates):
    foundation, _ = templates
    policies = foundation.find_resources("AWS::IAM::Policy")
    statements = [
        statement
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    powerful = [
        statement
        for statement in statements
        if "ec2:StartInstances" in json.dumps(statement["Action"])
    ]
    assert len(powerful) == 1
    assert powerful[0]["Condition"] == {"StringEquals": {f"aws:ResourceTag/{GPU_TAG_KEY}": "1"}}
    assert "ec2:TerminateInstances" not in json.dumps(statements)
    assert "ec2:ModifyInstanceAttribute" not in json.dumps(statements)
    assert not any(
        statement["Resource"] == "*" and statement["Action"] != "ec2:DescribeInstances"
        for statement in statements
    )


def test_provisioning_survives_a_reboot_and_names_the_right_role(templates):
    foundation, gpu = templates
    for template, role in ((foundation, "control"), (gpu, "gpu")):
        script = json.dumps(only_instance(template)["UserData"])
        assert f"flintgraph_role={role}" in script
        assert "ConditionPathExists=!/var/lib/flintgraph-provisioned" in script
        assert "deploy/ansible/site.yml" in script


def test_a_broken_first_boot_cannot_leave_the_gpu_running_for_days(templates):
    foundation, gpu = templates
    script = json.dumps(only_instance(gpu)["UserData"])
    assert script.index("shutdown -h +300") < script.index("apt-get update")
    assert "shutdown" not in json.dumps(only_instance(foundation)["UserData"])


def test_a_budget_alarm_exists_and_emails_when_given_an_address():
    foundation, _ = build()
    foundation.resource_count_is("AWS::Budgets::Budget", 1)
    with_email, _ = build(alert_email="alerts@example.com")
    budget = next(iter(with_email.find_resources("AWS::Budgets::Budget").values()))
    alerts = budget["Properties"]["NotificationsWithSubscribers"]
    assert len(alerts) == 3
    assert alerts[0]["Subscribers"][0]["Address"] == "alerts@example.com"


def test_no_email_or_account_is_written_into_the_defaults():
    config = InfraConfig()
    assert config.alert_email is None
    assert config.ami.startswith("ami-"), "pinned, so a new image never replaces a running server"
