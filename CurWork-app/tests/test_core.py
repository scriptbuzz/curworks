# CurWork tests - Beta 0.016 - DRAFT - For Internal Use - updated 2026-11-23 01:23 UTC - modified by: mbitar
"""Tests for curwork_core using a mocked S3 (moto). Run: python -m pytest -q"""
import os
import sys
import threading
from pathlib import Path, PurePosixPath

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import curwork_core as core  # noqa: E402

BUCKET = "cur-test-bucket"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "aws_config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws_creds"))


def make_settings(tmp_path, **over):
    data = {"bucket": BUCKET, "aws_profile": "", "work_dir": str(tmp_path / "CurWork")}
    data.update(over)
    return core.settings_from_dict(data)


@pytest.fixture
def s3env(tmp_path):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        s3.put_object(Bucket=BUCKET, Key="converted/agency-a/2026-10/cur-part1.xlsx", Body=b"A" * 1000)
        s3.put_object(Bucket=BUCKET, Key="converted/agency-a/2026-10/cur-part2.xlsx", Body=b"B" * 2000)
        s3.put_object(Bucket=BUCKET, Key="converted/agency-a/2026-09/cur.xlsx", Body=b"C" * 10)
        s3.put_object(Bucket=BUCKET, Key="converted/agency-b/2026-10/cur.xlsx", Body=b"D" * 10)
        settings = make_settings(tmp_path)
        svc = core.S3Service(settings, session=boto3.Session(region_name="us-east-1"))
        work = core.WorkArea(settings.work_dir)
        work.ensure()
        yield s3, settings, svc, work


# ---- config ---------------------------------------------------------------

def test_config_requires_bucket(tmp_path):
    with pytest.raises(core.CurWorkError):
        core.settings_from_dict({"bucket": ""})
    with pytest.raises(core.CurWorkError):
        core.settings_from_dict({"bucket": "CHANGE-ME"})


def test_config_rejects_overlapping_prefixes():
    with pytest.raises(core.CurWorkError):
        core.settings_from_dict({"bucket": "b", "browse_roots": ["priced/"]})


def test_config_normalizes(tmp_path):
    s = core.settings_from_dict({"bucket": "b", "browse_roots": ["/converted"], "output_stages": {"P": "priced"},
                                 "default_stage": "nope", "work_dir": str(tmp_path)})
    assert s.browse_roots == ["converted/"]
    assert s.output_stages == {"P": "priced/"}
    assert s.default_stage == "P"


def test_load_settings_from_file(tmp_path):
    p = tmp_path / "curwork_admin_settings.json"
    p.write_text('{"_comment": "x", "region": "us-west-2", "sso": {"role_name": "Biller"}}', encoding="utf-8")
    s = core.load_settings(str(p))
    assert s.region == "us-west-2" and s.sso["role_name"] == "Biller" and s.source_path == p
    # Parameter Store is required: without a name in the file, CurWork reads the default parameter.
    assert s.settings_parameter == core.DEFAULT_PARAMETER and s.needs_managed_settings and s.bucket == ""


def test_laptop_file_with_settings_kept_in_aws_is_refused(tmp_path):
    p = tmp_path / "curwork_admin_settings.json"
    p.write_text('{"region": "us-east-1", "bucket": "old-bucket", "work_dir": "C:/CurWork"}', encoding="utf-8")
    with pytest.raises(core.CurWorkError, match="can only hold the settings CurWork needs to sign in.*bucket, work_dir"):
        core.load_settings(str(p))
    # The admin settings app still opens an older file, so it can copy those settings to AWS.
    s = core.load_settings(str(p), strict=False)
    assert s.bucket == "" and s.local_data["bucket"] == "old-bucket"


def test_only_sign_in_settings_stay_on_the_laptop():
    assert set(core.LOCAL_KEYS) == {"aws_profile", "region", "use_fips_endpoint", "aws_cli_path", "login_banner",
                                    "settings_parameter", "sso"}
    assert {"bucket", "work_dir", "user_settings_location", "kms_key_id"} <= set(core.MANAGED_KEYS)


def test_switch_file_logging_moves_todays_lines(tmp_path):
    old = core.WorkArea(tmp_path / "old"); old.ensure()
    new = core.WorkArea(tmp_path / "new"); new.ensure()
    first = core.setup_file_logging(old)
    core.log.info("before the switch")
    moved = core.switch_file_logging(first, new)
    core.log.info("after the switch")
    for h in list(core.log.handlers):
        if getattr(h, "baseFilename", "") == str(moved):
            h.flush(); core.log.removeHandler(h); h.close()
    text = moved.read_text(encoding="utf-8")
    assert not first.exists() and text.index("before the switch") < text.index("after the switch")


# ---- paths ----------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../evil.xlsx", "a/../../b.xlsx", "a/b:c.xlsx", "con.xlsx", "a/trailing. ", ""])
def test_safe_relative_path_rejects(bad):
    with pytest.raises(core.CurWorkError):
        core.safe_relative_path(bad)


def test_safe_relative_path_ok():
    assert core.safe_relative_path("agency-a/2026-10/x.xlsx") == PurePosixPath("agency-a/2026-10/x.xlsx")


def test_context_for():
    roots = ["converted/"]
    assert core.context_for("converted/agency-a/2026-10/x.xlsx", roots) == "agency-a/2026-10/"
    assert core.context_for("converted/agency-a/2026-10/", roots) == "agency-a/2026-10/"
    assert core.context_for("converted/x.xlsx", roots) == ""


def test_ignored_names():
    assert core.is_ignored_name("~$cur.xlsx")
    assert core.is_ignored_name("cur.xlsx.part")
    assert not core.is_ignored_name("cur.xlsx")


# ---- S3 -------------------------------------------------------------------

def test_list_level(s3env):
    _, _, svc, _ = s3env
    folders, files = svc.list_level("converted/")
    assert folders == ["converted/agency-a/", "converted/agency-b/"]
    assert files == []
    folders, files = svc.list_level("converted/agency-a/2026-10/")
    assert [f.key for f in files] == ["converted/agency-a/2026-10/cur-part1.xlsx", "converted/agency-a/2026-10/cur-part2.xlsx"]


def test_download_folder(s3env):
    _, settings, svc, work = s3env
    files = svc.expand_selection(["converted/agency-a/2026-10/"])
    seen = []
    paths = svc.download(files, work.in_dir, on_progress=lambda d, t: seen.append((d, t)))
    assert [p.name for p in paths] == ["cur-part1.xlsx", "cur-part2.xlsx"]
    assert (work.in_dir / "agency-a" / "2026-10" / "cur-part2.xlsx").stat().st_size == 2000
    assert seen[-1] == (3000, 3000)
    assert not list(work.in_dir.rglob("*.part"))


def test_download_single_file(s3env):
    _, _, svc, work = s3env
    files = svc.expand_selection(["converted/agency-b/2026-10/cur.xlsx"])
    svc.download(files, work.in_dir)
    assert (work.in_dir / "agency-b" / "2026-10" / "cur.xlsx").exists()


def test_download_cancel(s3env):
    _, _, svc, work = s3env
    ev = threading.Event()
    ev.set()
    with pytest.raises(core.Cancelled):
        svc.download(svc.expand_selection(["converted/agency-a/"]), work.in_dir, cancel=ev)


def test_upload_and_status(s3env):
    s3, settings, svc, work = s3env
    out = work.out_dir / "agency-a_priced.xlsx"
    out.write_bytes(b"P" * 500)
    (work.out_dir / "~$agency-a_priced.xlsx").write_bytes(b"lock")  # pretend Excel still has it open
    assert work.out_files()[0].status == "Open in Excel"
    with pytest.raises(core.CurWorkError):
        svc.upload([(out, "agency-a_priced.xlsx")], "priced/agency-a/2026-10/")
    (work.out_dir / "~$agency-a_priced.xlsx").unlink()

    assert work.out_files()[0].status == "Not saved in S3"
    keys = svc.upload(
        [(f.path, f.rel) for f in work.out_files()], "priced/agency-a/2026-10/",
        on_uploaded=lambda p, rel, key: work.record_upload(rel, p, key),
    )
    assert keys == ["priced/agency-a/2026-10/agency-a_priced.xlsx"]
    head = s3.head_object(Bucket=BUCKET, Key=keys[0])
    assert head["ContentLength"] == 500
    assert head["Metadata"]["curwork-version"] == core.VERSION
    assert work.out_files()[0].status == "Saved in S3"

    # Change the file -> status changes
    os.utime(out, (out.stat().st_atime, out.stat().st_mtime + 10))
    assert work.out_files()[0].status == "Changed since saved"


def test_upload_existing_skip_and_overwrite(s3env):
    s3, _, svc, work = s3env
    s3.put_object(Bucket=BUCKET, Key="priced/a/x.xlsx", Body=b"old")
    f = work.out_dir / "x.xlsx"
    f.write_bytes(b"new-content")
    assert svc.upload([(f, "x.xlsx")], "priced/a/", on_exists=lambda k: "skip") == []
    assert s3.get_object(Bucket=BUCKET, Key="priced/a/x.xlsx")["Body"].read() == b"old"
    assert svc.upload([(f, "x.xlsx")], "priced/a/", on_exists=lambda k: "overwrite") == ["priced/a/x.xlsx"]
    assert s3.get_object(Bucket=BUCKET, Key="priced/a/x.xlsx")["Body"].read() == b"new-content"
    with pytest.raises(core.Cancelled):
        svc.upload([(f, "x.xlsx")], "priced/a/", on_exists=lambda k: "cancel")


def test_upload_blocks_input_prefix(s3env):
    _, _, svc, work = s3env
    f = work.out_dir / "x.xlsx"
    f.write_bytes(b"x")
    for bad in ("converted/agency-a/", "raw/", "", "priced/../converted/"):
        with pytest.raises(core.CurWorkError):
            svc.upload([(f, "x.xlsx")], bad)


def test_upload_skips_wrong_types(s3env):
    _, _, svc, work = s3env
    f = work.out_dir / "notes.exe"
    f.write_bytes(b"x")
    with pytest.raises(core.CurWorkError):
        svc.upload([(f, "notes.exe")], "priced/")


def test_upload_with_kms(s3env, tmp_path):
    s3, _, _, work = s3env
    kms = boto3.client("kms", region_name="us-east-1")
    key_id = kms.create_key()["KeyMetadata"]["KeyId"]
    settings = make_settings(tmp_path, kms_key_id=key_id)
    svc = core.S3Service(settings, session=boto3.Session(region_name="us-east-1"))
    f = work.out_dir / "k.xlsx"
    f.write_bytes(b"k")
    svc.upload([(f, "k.xlsx")], "reports/")
    head = s3.head_object(Bucket=BUCKET, Key="reports/k.xlsx")
    assert head["ServerSideEncryption"] == "aws:kms"


def test_upload_sends_a_sha256_checksum(s3env):
    """S3 checks the SHA-256 checksum on arrival, so a file damaged on the way is refused."""
    import base64
    import hashlib
    s3, _, svc, work = s3env
    body = b"checksum me" * 100
    f = work.out_dir / "c.xlsx"
    f.write_bytes(body)
    svc.upload([(f, "c.xlsx")], "reports/")
    head = s3.head_object(Bucket=BUCKET, Key="reports/c.xlsx", ChecksumMode="ENABLED")
    assert head.get("ChecksumSHA256") == base64.b64encode(hashlib.sha256(body).digest()).decode()


def test_expired_sign_in_errors_say_to_sign_in_again():
    from botocore.exceptions import TokenRetrievalError, UnauthorizedSSOTokenError
    for exc in (TokenRetrievalError(provider="sso", error_msg="Token has expired and refresh failed"),
                UnauthorizedSSOTokenError()):
        kind, msg = core.classify_error(exc)
        assert kind == "auth" and "Sign in" in msg


def test_upload_log(s3env):
    s3, _, svc, work = s3env
    lf = work.log_dir / "curwork-2026-11-22.log"
    lf.write_text("hello")
    key = svc.upload_log(lf)
    assert key.startswith("logs/") and key.endswith("curwork-2026-11-22.log")


# ---- work area ------------------------------------------------------------

def test_leftovers_and_clean(s3env):
    _, _, svc, work = s3env
    svc.download(svc.expand_selection(["converted/agency-a/2026-10/"]), work.in_dir)
    (work.out_dir / "sub").mkdir()
    (work.out_dir / "sub" / "r.xlsx").write_bytes(b"r")
    assert work.leftovers() == (2, 1, 1)
    skipped = work.clean()
    assert skipped == []
    assert work.leftovers() == (0, 0, 0)
    assert list(work.in_dir.iterdir()) == [] and list(work.out_dir.iterdir()) == []
    assert work.log_dir.exists()


def test_classify_errors():
    from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
    assert core.classify_error(NoCredentialsError())[0] == "auth"
    assert core.classify_error(ClientError({"Error": {"Code": "ExpiredToken"}}, "x"))[0] == "auth"
    assert core.classify_error(ClientError({"Error": {"Code": "AccessDenied"}}, "x"))[0] == "denied"
    assert core.classify_error(EndpointConnectionError(endpoint_url="https://x"))[0] == "network"


# ---- sign-in profile ------------------------------------------------------

def test_ensure_sso_profile_appends_once(tmp_path):
    cfg = tmp_path / "aws_config"
    cfg.write_text("# my notes\n[profile other]\nregion = us-west-2\n", encoding="utf-8")
    s = make_settings(tmp_path, aws_profile="fpt-biller", sso={
        "session_name": "fpt", "start_url": "https://example.awsapps.com/start",
        "sso_region": "us-east-1", "account_id": "123456789012", "role_name": "Biller"})
    assert core.ensure_sso_profile(s) is True
    text = cfg.read_text()
    assert text.startswith("# my notes\n[profile other]")  # existing content untouched
    assert "[profile fpt-biller]" in text and "[sso-session fpt]" in text
    assert core.ensure_sso_profile(s) is False  # second call does nothing
    assert text == cfg.read_text()


def test_ensure_sso_profile_needs_details(tmp_path):
    s = make_settings(tmp_path, aws_profile="fpt-biller")
    assert core.ensure_sso_profile(s) is False


# ---- added after logic review (code 1.1.0, now Beta 0.011) -----------------------------------

def test_in_extras_and_move_to_out(s3env):
    _, _, svc, work = s3env
    svc.download(svc.expand_selection(["converted/agency-a/2026-10/"]), work.in_dir,
                 on_downloaded=work.record_download)
    assert work.in_extras() == []
    # A macro saved a result into In by mistake, and changed an input in place
    stray = work.in_dir / "agency-a" / "2026-10" / "priced.xlsx"
    stray.write_bytes(b"result")
    changed = work.in_dir / "agency-a" / "2026-10" / "cur-part1.xlsx"
    changed.write_bytes(b"changed in place")
    extras = {rel: why for _, rel, why in work.in_extras()}
    assert extras == {"agency-a/2026-10/priced.xlsx": "new", "agency-a/2026-10/cur-part1.xlsx": "changed"}
    # Moving never overwrites something already in Out
    (work.out_dir / "agency-a" / "2026-10").mkdir(parents=True)
    (work.out_dir / "agency-a" / "2026-10" / "priced.xlsx").write_bytes(b"already here")
    moved = work.move_to_out([(stray, "agency-a/2026-10/priced.xlsx")])
    assert moved == ["agency-a/2026-10/priced (2).xlsx"]
    assert (work.out_dir / "agency-a" / "2026-10" / "priced.xlsx").read_bytes() == b"already here"
    assert not stray.exists()
    # With the customer/month folder stripped, the file lands at the top of Out
    other = work.in_dir / "agency-a" / "2026-10" / "alloc.xlsx"
    other.write_bytes(b"a")
    assert work.move_to_out([(other, "agency-a/2026-10/alloc.xlsx")], strip_prefix="agency-a/2026-10/") == ["alloc.xlsx"]


def test_download_keeps_changed_local_copy_when_told(s3env):
    _, _, svc, work = s3env
    files = svc.expand_selection(["converted/agency-b/2026-10/cur.xlsx"])
    svc.download(files, work.in_dir, on_downloaded=work.record_download)
    local = work.in_dir / "agency-b" / "2026-10" / "cur.xlsx"
    local.write_bytes(b"my edits")
    assert work.input_changed(local)
    svc.download(files, work.in_dir, replace_local=lambda t: False)
    assert local.read_bytes() == b"my edits"
    svc.download(files, work.in_dir, replace_local=lambda t: True, on_downloaded=work.record_download)
    assert local.read_bytes() == b"D" * 10 and not work.input_changed(local)


def test_multiple_roots_keep_root_folder(s3env, tmp_path):
    s3, _, _, work = s3env
    s3.put_object(Bucket=BUCKET, Key="rules/agency-a/2026-10/cur-part1.xlsx", Body=b"rules")
    settings = make_settings(tmp_path, browse_roots=["converted/", "rules/"])
    svc = core.S3Service(settings, session=boto3.Session(region_name="us-east-1"))
    svc.download(svc.expand_selection(["converted/agency-a/2026-10/cur-part1.xlsx",
                                       "rules/agency-a/2026-10/cur-part1.xlsx"]), work.in_dir)
    assert (work.in_dir / "converted/agency-a/2026-10/cur-part1.xlsx").stat().st_size == 1000
    assert (work.in_dir / "rules/agency-a/2026-10/cur-part1.xlsx").read_bytes() == b"rules"


def test_stale_owner_file_is_ignored_on_windows(monkeypatch, tmp_path):
    f = tmp_path / "r.xlsx"
    f.write_bytes(b"x")
    (tmp_path / "~$r.xlsx").write_bytes(b"owner")
    monkeypatch.setattr(core.os, "name", "nt")
    monkeypatch.setattr(core, "_write_blocked", lambda p: False)  # nobody holds either file
    assert core.is_open_elsewhere(f) is False
    monkeypatch.setattr(core, "_write_blocked", lambda p: p.name.startswith("~$"))  # Excel holds owner file
    assert core.is_open_elsewhere(f) is True
    monkeypatch.setattr(core, "_write_blocked", lambda p: p.name == "r.xlsx")  # Excel holds the workbook
    assert core.is_open_elsewhere(f) is True


def test_profile_exists_reads_file_even_if_aws_profile_env_is_bad(monkeypatch, tmp_path):
    (tmp_path / "aws_config").write_text("[profile fpt-biller]\nregion = us-east-1\n")
    monkeypatch.setenv("AWS_PROFILE", "does-not-exist")
    assert core.profile_exists("fpt-biller") is True
    s = make_settings(tmp_path, aws_profile="fpt-biller", sso={
        "session_name": "fpt", "start_url": "https://x.awsapps.com/start",
        "sso_region": "us-east-1", "account_id": "123456789012", "role_name": "Biller"})
    assert core.ensure_sso_profile(s) is False  # no duplicate section


def test_find_aws_cli_ignores_current_folder(monkeypatch, tmp_path):
    planted = tmp_path / "aws"
    planted.write_text("evil")
    monkeypatch.chdir(tmp_path)
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(core.shutil, "which", lambda name: str(planted))
    assert core.find_aws_cli() is None
    good = tmp_path / "bin" / "aws.exe"
    good.parent.mkdir()
    good.write_text("ok")
    assert core.find_aws_cli(str(good)) == str(good)
    assert core.find_aws_cli(str(tmp_path / "missing.exe")) is None


def test_friendly_identity():
    arn = "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_CUR_Biller_0123456789abcdef/jane@example.com"
    assert core.friendly_identity(arn) == "jane@example.com (CUR_Biller)"
    assert core.friendly_identity("arn:aws:sts::1:assumed-role/MyRole/sess") == "sess (MyRole)"
    assert core.friendly_identity("arn:aws:iam::1:user/bob") == "arn:aws:iam::1:user/bob"


def test_config_with_bom_and_bad_types(tmp_path):
    p = tmp_path / "curwork_admin_settings.json"
    p.write_bytes(b"\xef\xbb\xbf" + b'{"region": "us-west-2"}')
    assert core.load_settings(str(p)).region == "us-west-2"
    p.write_text('{"sso": "not an object"}')
    with pytest.raises(core.CurWorkError):
        core.load_settings(str(p))
    p.write_text('{"aws_cli_path": "C:\\aws"}')  # invalid escape \a
    with pytest.raises(core.CurWorkError, match="double backslashes"):
        core.load_settings(str(p))
    p.write_text('{"aws_cli_path": "C:\\new"}')  # valid JSON, but \n is a newline
    with pytest.raises(core.CurWorkError, match="double backslashes"):
        core.load_settings(str(p))


def test_work_dir_with_dollar_sign_is_kept(tmp_path):
    s = core.settings_from_dict({"bucket": "b-test", "work_dir": str(tmp_path / "john$" / "CurWork")})
    assert s.work_dir == tmp_path / "john$" / "CurWork"


def test_sync_folder_warning(tmp_path):
    assert core.sync_folder_warning(Path("C:/Users/jane/OneDrive - Company/CurWork"))
    assert core.sync_folder_warning(Path("C:/Users/jane/Box/CurWork"))
    assert core.sync_folder_warning(Path("C:/Users/jane/AppData/Local/CurWork")) is None


# ---- user preferences (unprotected) vs admin settings (protected) ---------

def _store(tmp_path, settings, writable=True):
    tool = tmp_path / "tool"
    tool.mkdir(exist_ok=True)
    if not writable:
        os.chmod(tool, 0o555)
    return core.UserSettingsStore(settings, [tool / core.USER_SETTINGS_FILE_NAME,
                                             settings.work_dir / core.USER_SETTINGS_FILE_NAME])


def test_user_prefs_round_trip(tmp_path):
    s = make_settings(tmp_path)
    store = _store(tmp_path, s)
    assert store.path.parent.name == "tool" and not store.fallback_used
    p = store.load()
    assert p == core.UserPrefs()  # no file yet: defaults
    p.add_recent("agency-a/2026-10")
    p.add_pinned("converted/agency-a/")
    p.last_result_type = "Allocated"
    p.window_geometry = "1200x800+10+20"
    p.column_widths = {"tree.#0": 300}
    store.save(p)
    again = _store(tmp_path, s).load()
    assert again.recent_folders == ["agency-a/2026-10/"]
    assert again.pinned_folders == ["converted/agency-a/"]
    assert again.last_result_type == "Allocated" and again.window_geometry == "1200x800+10+20"
    assert again.column_widths == {"tree.#0": 300}


def test_user_file_cannot_change_admin_settings(tmp_path):
    s = make_settings(tmp_path)
    store = _store(tmp_path, s)
    store.path.write_text(
        '{"bucket": "someone-elses-bucket", "use_fips_endpoint": false, "output_stages": {"X": "converted/"},'
        ' "work_dir": "D:/OneDrive", "recent_limit": 3}', encoding="utf-8")
    p = store.load()
    assert set(store.ignored) == {"bucket", "use_fips_endpoint", "output_stages", "work_dir"}
    assert p.recent_limit == 3
    assert s.bucket == BUCKET and s.output_stages["Priced"] == "priced/"  # admin settings untouched
    assert not hasattr(p, "bucket")


def test_user_prefs_bad_values_are_cleaned(tmp_path):
    s = make_settings(tmp_path)
    p, ignored = core.prefs_from_dict({
        "remember_result_type": "yes",          # wrong type -> default
        "recent_limit": 999,                    # clamped
        "recent_folders": ["agency-a/2026-10", "../etc", "a:b", 5, "agency-a/2026-10/"],
        "pinned_folders": ["converted/agency-a/", "priced/agency-a/", "../x/"],  # only browse roots allowed
        "window_geometry": "huge",
        "column_widths": {"tree.#0": 5000, "bad key": 100, "tree.size": "wide"},
    }, s)
    assert ignored == []
    assert p.remember_result_type is True and p.recent_limit == core.MAX_RECENT
    assert p.recent_folders == ["agency-a/2026-10/"]
    assert p.pinned_folders == ["converted/agency-a/"]
    assert p.window_geometry == "" and p.column_widths == {"tree.#0": 1200}


def test_recent_folders_keep_newest_first_and_limit(tmp_path):
    p = core.UserPrefs(recent_limit=2)
    for f in ("a/2026-08", "b/2026-09", "a/2026-08", "c/2026-10"):
        p.add_recent(f)
    assert p.recent_folders == ["c/2026-10/", "a/2026-08/"]
    off = core.UserPrefs(recent_limit=0)
    assert off.add_recent("a/2026-08") is False and off.recent_folders == []


def test_user_prefs_fall_back_when_tool_folder_locked(tmp_path):
    if os.name == "nt" or os.geteuid() == 0:
        pytest.skip("needs a non-root POSIX user to make a folder read-only")
    s = make_settings(tmp_path)
    store = _store(tmp_path, s, writable=False)
    assert store.fallback_used and store.path.parent == s.work_dir
    store.save(core.UserPrefs(recent_limit=4))
    assert _store(tmp_path, s, writable=False).load().recent_limit == 4


def test_unreadable_user_file_uses_defaults(tmp_path):
    s = make_settings(tmp_path)
    store = _store(tmp_path, s)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.load() == core.UserPrefs()


def test_user_settings_location_setting(tmp_path):
    s = make_settings(tmp_path, user_settings_location="work_folder")
    assert core.user_settings_candidates(s) == [s.work_dir / core.USER_SETTINGS_FILE_NAME]
    with pytest.raises(core.CurWorkError):
        make_settings(tmp_path, user_settings_location="desktop")


def test_clean_up_keeps_user_preferences(tmp_path):
    s = make_settings(tmp_path, user_settings_location="work_folder")
    work = core.WorkArea(s.work_dir)
    work.ensure()
    store = core.UserSettingsStore(s)
    store.save(core.UserPrefs(recent_limit=7))
    (work.in_dir / "x.xlsx").write_bytes(b"1")
    work.clean()
    assert store.path.is_file() and core.UserSettingsStore(s).load().recent_limit == 7


def test_oversized_user_file_is_ignored_and_save_leaves_no_temp_files(tmp_path):
    s = make_settings(tmp_path)
    store = _store(tmp_path, s)
    store.path.write_text('{"recent_limit": 3, "x": "' + "a" * (core.MAX_SETTINGS_BYTES + 10) + '"}', encoding="utf-8")
    assert store.load() == core.UserPrefs()
    store.save(core.UserPrefs(recent_limit=5))
    leftovers = [p.name for p in store.path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [] and store.load().recent_limit == 5


def test_oversized_admin_file_is_refused(tmp_path):
    p = tmp_path / core.CONFIG_FILE_NAME
    p.write_text('{"bucket": "b", "_pad": "' + "a" * (core.MAX_SETTINGS_BYTES + 10) + '"}', encoding="utf-8")
    with pytest.raises(core.CurWorkError):
        core.load_settings(str(p))


def test_exists_matches_exact_key_only(s3env, tmp_path):
    s3, _settings, svc, _work = s3env
    s3.put_object(Bucket=BUCKET, Key="priced/agency-a/2026-10/r.xlsx.bak", Body=b"1")
    assert svc.exists("priced/agency-a/2026-10/r.xlsx") is False
    s3.put_object(Bucket=BUCKET, Key="priced/agency-a/2026-10/r.xlsx", Body=b"1")
    assert svc.exists("priced/agency-a/2026-10/r.xlsx") is True


def test_tool_folder_frozen_windows_and_mac(monkeypatch, tmp_path):
    exe = tmp_path / "CurWork.exe"; exe.write_bytes(b"")
    monkeypatch.setattr(core.sys, "frozen", True, raising=False)
    monkeypatch.setattr(core.sys, "executable", str(exe))
    assert core.tool_folder() == tmp_path.resolve()
    mac = tmp_path / "CurWork.app" / "Contents" / "MacOS"; mac.mkdir(parents=True)
    (mac / "CurWork").write_bytes(b"")
    monkeypatch.setattr(core.sys, "executable", str(mac / "CurWork"))
    assert core.tool_folder() == tmp_path.resolve()   # next to CurWork.app, never inside it


def test_app_icons_are_present():
    from pathlib import Path
    assets = Path(__file__).resolve().parent.parent / "assets"
    for name in ("curwork.png", "curwork-256.png", "curwork-64.png", "curwork.ico", "curwork.icns"):
        assert (assets / name).stat().st_size > 1000, name


def test_denied_message_names_the_refused_call():
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "403", "Message": "Forbidden"},
                       "ResponseMetadata": {"HTTPStatusCode": 403}}, "HeadObject")
    kind, msg = core.classify_error(err)
    assert kind == "denied" and "s3:GetObject" in msg and "Forbidden" not in msg
    err = ClientError({"Error": {"Code": "AccessDenied", "Message": "not authorized to perform: s3:GetObject"}},
                      "GetObject")
    kind, msg = core.classify_error(err)
    assert kind == "denied" and "AWS's reason: not authorized to perform: s3:GetObject" in msg


def test_built_mac_app_finds_admin_settings_next_to_the_app(monkeypatch, tmp_path):
    mac = tmp_path / "CurWork.app" / "Contents" / "MacOS"; mac.mkdir(parents=True)
    (mac / "CurWork").write_bytes(b"")
    monkeypatch.setattr(core.sys, "frozen", True, raising=False)
    monkeypatch.setattr(core.sys, "executable", str(mac / "CurWork"))
    monkeypatch.delenv("CURWORK_CONFIG", raising=False)
    assert core.candidate_config_paths()[0] == tmp_path.resolve() / core.CONFIG_FILE_NAME


def _frozen_app(monkeypatch, tmp_path):
    """Pretend to be the built CurWork.exe in tmp_path/tool, with a biller's own settings file elsewhere."""
    tool = tmp_path / "tool"; tool.mkdir()
    (tool / "CurWork.exe").write_bytes(b"")
    monkeypatch.setattr(core.sys, "frozen", True, raising=False)
    monkeypatch.setattr(core.sys, "executable", str(tool / "CurWork.exe"))
    good = {"region": "us-west-2", "settings_parameter": "/curwork/installed"}
    own = dict(good, settings_parameter="/curwork/bypass")
    mine = tmp_path / "mine.json"; mine.write_text(__import__("json").dumps(own), encoding="utf-8")
    appdata = tmp_path / "appdata"; (appdata / "CurWork").mkdir(parents=True)
    (appdata / "CurWork" / core.CONFIG_FILE_NAME).write_text(__import__("json").dumps(own), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("CURWORK_CONFIG", str(mine))
    return tool, good, mine


def test_built_app_always_uses_installed_admin_settings(monkeypatch, tmp_path):
    tool, good, mine = _frozen_app(monkeypatch, tmp_path)
    (tool / core.CONFIG_FILE_NAME).write_text(__import__("json").dumps(good), encoding="utf-8")
    s = core.load_settings(str(mine))
    assert s.settings_parameter == "/curwork/installed"
    assert s.source_path == tool.resolve() / core.CONFIG_FILE_NAME
    assert s.ignored_config_overrides == [f"--config {mine}", f"CURWORK_CONFIG={mine}"]
    assert core.candidate_config_paths(str(mine)) == [tool.resolve() / core.CONFIG_FILE_NAME]


def test_built_app_without_installed_settings_refuses_other_files(monkeypatch, tmp_path):
    tool, good, mine = _frozen_app(monkeypatch, tmp_path)
    with pytest.raises(core.CurWorkError) as e:
        core.load_settings(str(mine))   # --config, CURWORK_CONFIG and %APPDATA% all hold a usable file
    assert str(tool.resolve() / core.CONFIG_FILE_NAME) in str(e.value)
    assert "mine.json" not in str(e.value) and "appdata" not in str(e.value).lower()


def test_running_from_source_still_accepts_config_override(monkeypatch, tmp_path):
    monkeypatch.setattr(core.sys, "frozen", False, raising=False)
    mine = tmp_path / "mine.json"
    mine.write_text('{"settings_parameter": "/curwork/dev"}', encoding="utf-8")
    monkeypatch.delenv("CURWORK_CONFIG", raising=False)
    s = core.load_settings(str(mine))
    assert s.settings_parameter == "/curwork/dev" and s.ignored_config_overrides == []


def test_running_from_source_refuses_a_named_settings_file_that_is_missing(monkeypatch, tmp_path):
    """A missing --config or CURWORK_CONFIG file stops CurWork instead of falling back to another file."""
    monkeypatch.setattr(core.sys, "frozen", False, raising=False)
    monkeypatch.delenv("CURWORK_CONFIG", raising=False)
    missing = tmp_path / "nope.json"
    with pytest.raises(core.CurWorkError) as e:
        core.load_settings(str(missing))
    assert f"--config {missing}" in str(e.value)
    monkeypatch.setenv("CURWORK_CONFIG", str(missing))
    with pytest.raises(core.CurWorkError) as e:
        core.load_settings(None)
    assert f"CURWORK_CONFIG={missing}" in str(e.value)
