# CurWork tests - Beta 0.011 - DRAFT - For Internal Use - updated 2026-11-22 22:40 UTC - modified by: mbitar
"""Tests for the managed admin settings in AWS Parameter Store (mocked with moto):
how CurWork reads them, the admin app's form and saves, and the biller policy (read, never write)."""
import json
import sys
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import curwork_admin as admin  # noqa: E402
import curwork_core as core  # noqa: E402

PARAM = "/curwork/admin-settings"
MANAGED = {"bucket": "managed-bucket", "browse_roots": ["converted/"],
           "output_stages": {"Priced": "priced/", "Reports": "reports/"}, "default_stage": "Reports",
           "_version": "2026-11 release"}


@pytest.fixture(autouse=True)
def aws_env(monkeypatch, tmp_path):
    for k, v in (("AWS_ACCESS_KEY_ID", "testing"), ("AWS_SECRET_ACCESS_KEY", "testing"),
                 ("AWS_SESSION_TOKEN", "testing"), ("AWS_DEFAULT_REGION", "us-east-1"),
                 ("AWS_CONFIG_FILE", str(tmp_path / "aws_config")),
                 ("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws_creds"))):
        monkeypatch.setenv(k, v)


def local_settings(tmp_path, **over):
    data = {"aws_profile": "", "settings_parameter": PARAM, "work_dir": str(tmp_path / "CurWork"),
            "bucket": "local-bucket-must-be-ignored"}
    data.update(over)
    return core.settings_from_dict(data)


# ---- how CurWork reads the managed settings ---------------------------------

def test_local_file_with_a_parameter_waits_for_aws_and_ignores_its_own_managed_keys(tmp_path):
    s = local_settings(tmp_path)
    assert s.needs_managed_settings and s.bucket == ""
    svc = core.S3Service(s, session=boto3.Session(region_name="us-east-1"))
    with pytest.raises(core.CurWorkError, match="hasn't read its admin settings"):
        svc.client()      # S3 is never used before the managed settings are read


def test_curwork_reads_managed_settings_from_parameter_store(tmp_path):
    with mock_aws():
        managed = {**MANAGED, "aws_profile": "someone-else", "sso": {"role_name": "Admin"}}   # local-only keys
        boto3.client("ssm", region_name="us-east-1").put_parameter(Name=PARAM, Value=json.dumps(managed), Type="String")
        svc = core.S3Service(local_settings(tmp_path, aws_profile="fpt-biller"),
                             session=boto3.Session(region_name="us-east-1"))
        s = svc.load_managed_settings()
    assert s.bucket == "managed-bucket" and s.default_stage == "Reports" and not s.needs_managed_settings
    assert s.aws_profile == "fpt-biller" and s.sso.get("role_name") == "", "Parameter Store can't change the sign-in"
    assert "Parameter Store version 1" in s.admin_version and "2026-11 release" in s.admin_version


def test_missing_or_broken_parameter_stops_curwork(tmp_path):
    with mock_aws():
        svc = core.S3Service(local_settings(tmp_path), session=boto3.Session(region_name="us-east-1"))
        with pytest.raises(core.CurWorkError, match="aren't in AWS Parameter Store yet"):
            svc.load_managed_settings()
        boto3.client("ssm", region_name="us-east-1").put_parameter(Name=PARAM, Value="{not json", Type="String")
        with pytest.raises(core.CurWorkError, match="aren't valid JSON"):
            svc.load_managed_settings()


def test_bad_parameter_name_is_refused(tmp_path):
    with pytest.raises(core.CurWorkError, match="Parameter Store name"):
        local_settings(tmp_path, settings_parameter="curwork settings")


def test_install_without_a_parameter_works_as_before(tmp_path):
    s = core.settings_from_dict({"bucket": "b", "aws_profile": "", "work_dir": str(tmp_path)})
    assert not s.needs_managed_settings and s.bucket == "b"


# ---- the admin app's form ----------------------------------------------------

def test_form_round_trip_and_validation():
    form = admin.managed_to_form(MANAGED)
    assert form["output_stages"] == "Priced = priced/\nReports = reports/"
    assert admin.form_to_managed(form)["output_stages"] == MANAGED["output_stages"]
    for field, value, message in (("output_stages", "Priced priced/", "line 1"),
                                  ("max_concurrency", "lots", "whole number"),
                                  ("bucket", "", "bucket"),
                                  ("browse_roots", "priced/", "overlap")):
        with pytest.raises(core.CurWorkError, match=message):
            admin.form_to_managed({**form, field: value})


def test_managed_settings_cant_hold_sign_in_keys():
    with pytest.raises(core.CurWorkError, match="aws_profile"):
        core.validate_managed({**MANAGED, "aws_profile": "x"})


def test_changes_are_listed_before_saving():
    after = {**MANAGED, "bucket": "new-bucket"}
    assert admin.describe_changes(MANAGED, after) == ['S3 bucket: "managed-bucket" -> "new-bucket"']


# ---- saving from the admin app -------------------------------------------------

def test_admin_saves_versions_and_refuses_to_overwrite_someone_elses_change():
    with mock_aws():
        store = admin.AdminStore(PARAM, "us-east-1", session=boto3.Session(region_name="us-east-1"))
        assert store.load() == (None, None)
        assert store.save(MANAGED, None) == 1
        changed = {**MANAGED, "bucket": "second-bucket"}
        assert store.save(changed, 1) == 2
        with pytest.raises(core.CurWorkError, match="Someone else saved"):
            store.save({**MANAGED, "bucket": "stale"}, 1)
        assert store.load() == (changed, 2)
        rows = store.history()
        assert [r["version"] for r in rows] == [2, 1] and rows[0]["label"] == "2026-11 release"
        tags = boto3.client("ssm", region_name="us-east-1").list_tags_for_resource(
            ResourceType="Parameter", ResourceId=PARAM)["TagList"]
        assert {"Key": "Purpose", "Value": "CurWork"} in tags


def test_admin_save_without_permission_says_only_the_admin_role_can():
    with mock_aws():
        store = admin.AdminStore(PARAM, "us-east-1", session=boto3.Session(region_name="us-east-1"))
        store.save(MANAGED, None)

        class DeniedSSM:     # reads work, saves are refused, as for a biller's sign-in
            def __init__(self, client):
                self.client = client

            def __getattr__(self, name):
                return getattr(self.client, name)

            def put_parameter(self, **_kw):
                raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "PutParameter")

        real = store._client
        store._client = lambda name: DeniedSSM(real(name)) if name == "ssm" else real(name)
        with pytest.raises(core.CurWorkError, match="Only the AWS admin role can"):
            store.save({**MANAGED, "bucket": "x"}, 1)


# ---- the biller policy: read the parameter, never change it ------------------------

def test_biller_policy_reads_but_cannot_change_the_settings_parameter():
    from moto.core import set_initial_no_auth_action_count
    policy = (Path(__file__).resolve().parent.parent / "iam" / "biller_permission_set_policy.json").read_text()
    policy = policy.replace("arn:aws:ssm:REGION:ACCOUNT_ID:", "arn:aws:ssm:us-east-1:123456789012:")
    statement = next(st for st in json.loads(policy)["Statement"] if st["Sid"] == "ReadCurWorkAdminSettings")
    assert statement["Action"] == ["ssm:GetParameter"]
    assert statement["Resource"] == "arn:aws:ssm:us-east-1:123456789012:parameter/curwork/*"
    # moto checks SSM actions but not resources, so the mock gets Resource "*". The real AWS tests
    # (menu option 8) check that the biller can't read other parameters.
    only_ssm = {"Version": "2012-10-17", "Statement": [{**statement, "Resource": "*"}]}

    @set_initial_no_auth_action_count(4)
    @mock_aws
    def run():
        boto3.client("ssm", region_name="us-east-1").put_parameter(Name=PARAM, Value=json.dumps(MANAGED), Type="String")  # 1
        iam = boto3.client("iam", region_name="us-east-1")
        iam.create_user(UserName="biller")                                                          # 2
        iam.put_user_policy(UserName="biller", PolicyName="biller", PolicyDocument=json.dumps(only_ssm))  # 3
        key = iam.create_access_key(UserName="biller")["AccessKey"]                                   # 4
        biller = boto3.client("ssm", region_name="us-east-1", aws_access_key_id=key["AccessKeyId"],
                              aws_secret_access_key=key["SecretAccessKey"], aws_session_token=None)
        assert json.loads(biller.get_parameter(Name=PARAM)["Parameter"]["Value"])["bucket"] == "managed-bucket"
        for call in (lambda: biller.put_parameter(Name=PARAM, Value="{}", Type="String", Overwrite=True),
                     lambda: biller.delete_parameter(Name=PARAM)):
            with pytest.raises(ClientError) as e:
                call()
            assert e.value.response["Error"]["Code"] in ("AccessDeniedException", "AccessDenied", "403")
    run()
