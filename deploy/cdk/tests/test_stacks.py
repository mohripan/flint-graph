"""What must hold about the AWS resources, checked on the synthesized templates without AWS."""

import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from flintgraph_infra.config import DEFAULT_VPC_CIDR, GPU_TAG_KEY, LIGHTSAIL_CIDR, InfraConfig
from flintgraph_infra.foundation import FoundationStack
from flintgraph_infra.gpu import GpuStack


def build(**changes):
    app = cdk.App()
    config = InfraConfig(**changes)
    env = cdk.Environment(region=config.region)
    foundation = FoundationStack(app, "Foundation", config=config, env=env)
    gpu = GpuStack(app, "Gpu", config=config, env=env)
    return Template.from_stack(foundation), Template.from_stack(gpu)


@pytest.fixture(scope="module")
def templates():
    return build()


def control(template):
    rows = template.find_resources("AWS::Lightsail::Instance")
    assert len(rows) == 1
    return next(iter(rows.values()))


def gpu_instance(template):
    rows = template.find_resources("AWS::EC2::Instance")
    assert len(rows) == 1
    return next(iter(rows.values()))["Properties"]


def key_statements(foundation):
    return [
        statement
        for policy in foundation.find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]


def test_the_always_on_server_is_the_2_gb_lightsail_plan_on_ubuntu(templates):
    foundation, _ = templates
    properties = control(foundation)["Properties"]
    assert properties["BundleId"] == "small_3_2"
    assert properties["BlueprintId"] == "ubuntu_24_04"
    assert properties["AvailabilityZone"] == "ap-southeast-2a"


def test_only_web_traffic_is_open_to_the_internet(templates):
    foundation, _ = templates
    ports = control(foundation)["Properties"]["Networking"]["Ports"]
    public = [port for port in ports if "0.0.0.0/0" in port.get("Cidrs", [])]
    assert sorted(port["FromPort"] for port in public) == [80, 443]
    ssh = next(port for port in ports if port["FromPort"] == 22)
    assert ssh["CidrListAliases"] == ["lightsail-connect"]
    assert "Cidrs" not in ssh
    cluster = {port["FromPort"]: port for port in ports if port["FromPort"] > 443}
    assert set(cluster) == {6443, 10250, 51820}
    assert all(port["Cidrs"] == [DEFAULT_VPC_CIDR] for port in cluster.values())
    assert cluster[51820]["Protocol"] == "udp"


def test_nothing_on_the_internet_can_reach_the_gpu(templates):
    _, gpu = templates
    rules = [
        rule
        for group in gpu.find_resources("AWS::EC2::SecurityGroup").values()
        for rule in group["Properties"].get("SecurityGroupIngress", [])
    ]
    rules += [
        rule["Properties"] for rule in gpu.find_resources("AWS::EC2::SecurityGroupIngress").values()
    ]
    assert sorted(rule["FromPort"] for rule in rules) == [10250, 51820]
    assert all(rule["CidrIp"] == LIGHTSAIL_CIDR for rule in rules)


def test_there_is_no_nat_gateway_or_new_network_to_pay_for(templates):
    for template in templates:
        template.resource_count_is("AWS::EC2::NatGateway", 0)
        template.resource_count_is("AWS::EC2::VPC", 0)
        template.resource_count_is("AWS::EC2::EIP", 0)


def test_the_gpu_uses_the_default_vpc_given_when_deploying():
    _, gpu = build(default_vpc_id="vpc-111", default_subnet_id="subnet-222")
    assert gpu_instance(gpu)["SubnetId"] == "subnet-222"
    group = next(iter(gpu.find_resources("AWS::EC2::SecurityGroup").values()))
    assert group["Properties"]["VpcId"] == "vpc-111"


def test_the_gpu_requires_imdsv2_and_keeps_its_role_from_pods(templates):
    _, gpu = templates
    options = gpu_instance(gpu)["MetadataOptions"]
    assert options["HttpTokens"] == "required"
    assert options["HttpPutResponseHopLimit"] == 1


def test_the_gpu_disk_is_encrypted_gp3(templates):
    _, gpu = templates
    ebs = gpu_instance(gpu)["BlockDeviceMappings"][0]["Ebs"]
    assert ebs["Encrypted"] is True
    assert ebs["VolumeType"] == "gp3"
    assert ebs["VolumeSize"] == 70


def test_deleting_the_stack_cannot_delete_the_only_copy_of_every_project(templates):
    foundation, _ = templates
    assert control(foundation)["DeletionPolicy"] == "Retain"
    assert control(foundation)["UpdateReplacePolicy"] == "Retain"
    address = next(iter(foundation.find_resources("AWS::Lightsail::StaticIp").values()))
    assert address["DeletionPolicy"] == "Retain"


def test_there_are_no_backups_because_the_owner_chose_none(templates):
    foundation, _ = templates
    foundation.resource_count_is("AWS::DLM::LifecyclePolicy", 0)
    assert "AddOns" not in control(foundation)["Properties"]


def test_the_gpu_stops_rather_than_terminates_when_it_shuts_itself_down(templates):
    _, gpu = templates
    properties = gpu_instance(gpu)
    assert properties["InstanceInitiatedShutdownBehavior"] == "stop"
    assert properties["InstanceType"] == "g4dn.xlarge"
    tags = {tag["Key"]: tag["Value"] for tag in properties["Tags"]}
    assert tags[GPU_TAG_KEY] == "1"


def test_only_the_tagged_gpu_can_be_started_or_stopped_with_the_key(templates):
    foundation, _ = templates
    statements = key_statements(foundation)
    powerful = [s for s in statements if "ec2:StartInstances" in json.dumps(s["Action"])]
    assert len(powerful) == 1
    assert powerful[0]["Condition"] == {"StringEquals": {f"aws:ResourceTag/{GPU_TAG_KEY}": "1"}}
    assert "ec2:TerminateInstances" not in json.dumps(statements)
    assert "ec2:ModifyInstanceAttribute" not in json.dumps(statements)
    assert not any(
        s["Resource"] == "*" and s["Action"] != "ec2:DescribeInstances" for s in statements
    )


def test_the_keys_secret_never_enters_the_stack(templates):
    foundation, _ = templates
    foundation.resource_count_is("AWS::IAM::User", 1)
    foundation.resource_count_is("AWS::IAM::AccessKey", 0)


def test_provisioning_survives_a_reboot_and_names_the_right_role(templates):
    foundation, gpu = templates
    scripts = (
        ("control", json.dumps(control(foundation)["Properties"]["UserData"])),
        ("gpu", json.dumps(gpu_instance(gpu)["UserData"])),
    )
    for role, script in scripts:
        assert f"flintgraph_role={role}" in script
        assert "ConditionPathExists=!/var/lib/flintgraph-provisioned" in script
        assert "deploy/ansible/site.yml" in script


def test_the_always_on_server_waits_for_its_key_and_the_gpu_has_a_role_instead(templates):
    foundation, gpu = templates
    wanted = "ConditionPathExists=/root/.aws/credentials"
    assert wanted in json.dumps(control(foundation)["Properties"]["UserData"])
    assert wanted not in json.dumps(gpu_instance(gpu)["UserData"])
    assert "IamInstanceProfile" in gpu_instance(gpu)


def test_a_broken_first_boot_cannot_leave_the_gpu_running_for_days(templates):
    foundation, gpu = templates
    script = json.dumps(gpu_instance(gpu)["UserData"])
    assert script.index("shutdown -h +300") < script.index("apt-get update")
    assert "shutdown" not in json.dumps(control(foundation)["Properties"]["UserData"])


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
    assert set(config.default_vpc_id[4:]) == {"0"}, "the real ID is passed when deploying"
