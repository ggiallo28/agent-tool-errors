"""template.yaml, parsed offline with the CloudFormation-tag aware loader of cfn-lint (Requirements 1-3, 7)."""
import json
import shutil
import subprocess

import pytest
from cfnlint.decode.cfn_yaml import load

from tests.helpers import ROOT

TEMPLATE = ROOT / "template.yaml"


def load_template() -> dict:
    loaded = load(str(TEMPLATE))
    return loaded[0] if isinstance(loaded, tuple) else loaded


@pytest.fixture(scope="module")
def tpl():
    return load_template()


def of_type(tpl, kind):
    return {name: r for name, r in tpl["Resources"].items() if r["Type"] == kind}


def test_transform_is_sam(tpl):
    assert tpl["Transform"] == "AWS::Serverless-2016-10-31"


def test_one_cluster_with_the_required_properties(tpl):
    clusters = of_type(tpl, "AWS::RDS::DBCluster")
    assert list(clusters) == ["Cluster"]
    props = clusters["Cluster"]["Properties"]
    assert props["Engine"] == "aurora-postgresql"
    assert str(props["EngineVersion"]) == "16.15"
    assert props["DatabaseName"] == "opsmemory"
    assert props["MasterUsername"] == "opsadmin"
    assert props["ManageMasterUserPassword"] is True
    assert props["EnableHttpEndpoint"] is True
    assert props["ServerlessV2ScalingConfiguration"] == {"MinCapacity": 0, "MaxCapacity": 2, "SecondsUntilAutoPause": 600}


def test_one_serverless_writer_instance(tpl):
    instances = of_type(tpl, "AWS::RDS::DBInstance")
    assert list(instances) == ["WriterInstance"]
    props = instances["WriterInstance"]["Properties"]
    assert props["DBInstanceClass"] == "db.serverless"
    assert props["Engine"] == "aurora-postgresql"
    assert props["DBClusterIdentifier"] == {"Ref": "Cluster"}


@pytest.mark.parametrize("name", ["Cluster", "WriterInstance"])
def test_delete_policies(tpl, name):
    resource = tpl["Resources"][name]
    assert resource["DeletionPolicy"] == "Delete" and resource["UpdateReplacePolicy"] == "Delete"


def test_two_role_secrets_without_punctuation(tpl):
    secrets = of_type(tpl, "AWS::SecretsManager::Secret")
    assert sorted(secrets) == ["AgentWriterSecret", "ApproverSecret"]
    users = set()
    for secret in secrets.values():
        gen = secret["Properties"]["GenerateSecretString"]
        users.add(json.loads(gen["SecretStringTemplate"])["username"])
        assert gen["GenerateStringKey"] == "password"
        assert gen["PasswordLength"] == 32 and gen["ExcludePunctuation"] is True
    assert users == {"agent_writer", "approver"}
    assert "opsadmin" not in users


def test_resources_are_exactly_these(tpl):
    assert sorted(tpl["Resources"]) == ["AgentWriterSecret", "ApproverSecret", "Cluster", "RunnerRole",
                                        "WriterInstance"]


def test_outputs_refer_to_their_resources(tpl):
    outputs = {key: value["Value"] for key, value in tpl["Outputs"].items()}
    assert outputs == {
        "ClusterArn": {"Fn::GetAtt": ["Cluster", "DBClusterArn"]},
        "AdminSecretArn": {"Fn::GetAtt": ["Cluster", "MasterUserSecret.SecretArn"]},
        "AgentWriterSecretArn": {"Ref": "AgentWriterSecret"},
        "ApproverSecretArn": {"Ref": "ApproverSecret"},
        "RunnerRoleArn": {"Fn::GetAtt": ["RunnerRole", "Arn"]},
    }


def statements(tpl):
    policy = tpl["Resources"]["RunnerRole"]["Properties"]["Policies"][0]["PolicyDocument"]
    return {s["Sid"]: s for s in policy["Statement"]}


def as_list(value):
    return value if isinstance(value, list) else [value]


def test_runner_role_lists_what_the_scripts_call(tpl):
    got = statements(tpl)
    assert sorted(got) == ["BedrockModels", "DataApi", "RoleSecrets"]
    assert got["DataApi"]["Action"] == "rds-data:ExecuteStatement"
    assert got["DataApi"]["Resource"] == {"Fn::GetAtt": ["Cluster", "DBClusterArn"]}
    assert got["RoleSecrets"]["Action"] == "secretsmanager:GetSecretValue"
    assert as_list(got["RoleSecrets"]["Resource"]) == [
        {"Fn::GetAtt": ["Cluster", "MasterUserSecret.SecretArn"]},
        {"Ref": "AgentWriterSecret"}, {"Ref": "ApproverSecret"}]
    assert sorted(got["BedrockModels"]["Action"]) == ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    assert all(s["Effect"] == "Allow" for s in got.values())


def test_runner_role_is_scoped_and_assumable_only_inside_the_account(tpl):
    props = tpl["Resources"]["RunnerRole"]["Properties"]
    principal = props["AssumeRolePolicyDocument"]["Statement"][0]["Principal"]["AWS"]
    assert "AWS::AccountId" in json.dumps(principal) and "*" not in json.dumps(principal).replace("root", "")
    for statement in statements(tpl).values():
        assert "*" not in as_list(statement["Action"]) and not any(a.endswith(":*") for a in as_list(statement["Action"]))
        assert statement["Resource"] != "*"


@pytest.mark.skipif(shutil.which("sam") is None, reason="sam not on PATH")
def test_sam_validate_lint():
    """Reads the template only; creates nothing on AWS."""
    result = subprocess.run(["sam", "validate", "--lint", "-t", str(TEMPLATE)], capture_output=True, text=True,
                            cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
