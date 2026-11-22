"""
CurWork Beta 0.011 - DRAFT - For Internal Use (FPT) - real AWS tests - modified by: mbitar

Runs CurWork's own code (curwork_core) against the real test bucket with the sign-in CurWork uses,
the way the window does, and reports PASS/FAIL for each step. No mocks.

What it changes in AWS: uploads two small test files (one result, one log) under _autotest-<time> names,
tries one upload that must be refused, then removes every version of what it made using the admin
profile (CURWORK_ADMIN_PROFILE) (the biller sign-in can't delete, by design) and checks they're gone.

Run from the CurWorks folder with CurWork's .venv:  CurWork-Beta-0.011/.venv/bin/python tools/real_aws_tests.py
Exit code 0 = everything passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path.cwd()
TOOL = HERE / "CurWork-Beta-0.011"
sys.path.insert(0, str(TOOL))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

import curwork_core as core  # noqa: E402

G, R, Y, B, N = "\033[1;32m", "\033[1;31m", "\033[1;33m", "\033[1m", "\033[0m"
SMALL_KEY = "converted/agency-a/2026-10/agency-a-cur-2026-10.xlsx"
BIG_KEY = "converted/agency-b/2026-10/agency-b-cur-2026-10.xlsx"
STAMP = time.strftime("%Y%m%d%H%M%S", time.gmtime())
results: list[bool] = []
made: list[str] = []          # keys this run created (cleaned up at the end)


def check(label: str, ok: bool, detail: str = "") -> bool:
    results.append(bool(ok))
    print(f"  {G + 'PASS' + N if ok else R + 'FAIL' + N}  {label}" + (f"\n          {detail}" if detail else ""))
    return bool(ok)


def step(title: str) -> None:
    print(f"\n{B}== {title}{N}")


def err(e: BaseException) -> str:
    if isinstance(e, ClientError):
        return f"{getattr(e, 'operation_name', '')}: {e.response.get('Error', {}).get('Code')} {e.response.get('Error', {}).get('Message', '')}".strip()
    return f"{type(e).__name__}: {e}"


def main() -> int:
    step("Settings CurWork will use")
    settings = core.load_settings(str(TOOL / core.CONFIG_FILE_NAME))
    expected_role = (settings.sso or {}).get("role_name", "")
    print(f"  Bucket {settings.bucket} ({settings.region}), profile {settings.aws_profile}, role {expected_role}")
    note = HERE / "test_bucket.txt"
    if note.exists():
        check("Admin settings use the current test bucket", note.read_text().split()[0] == settings.bucket,
              f"test_bucket.txt says {note.read_text().split()[0]}")
    check("Admin settings name the biller test role", expected_role == os.environ.get("CURWORK_ROLE", "CurWorkBillerTest"),
          f"role_name is {expected_role or '(none)'}. Run menu option 4 (Set up biller test access).")

    step("Sign in (same way CurWork does)")
    if core.ensure_sso_profile(settings):
        print(f"  Added profile {settings.aws_profile} to ~/.aws/config (CurWork does this at first Sign in).")
    svc = core.S3Service(settings)
    try:
        who = svc.whoami()
    except Exception as e:  # noqa: BLE001
        print(f"  Not signed in yet ({core.classify_error(e)[0]}). Opening the browser to sign in...")
        core.run_sso_login(settings.aws_profile, on_line=lambda line: print("   ", line), cli_path=settings.aws_cli_path)
        svc.reset()
        who = svc.whoami()
    role = who.rsplit("(", 1)[-1].rstrip(")") if "(" in who else ""
    if not check("Signed in with the role in the admin settings", role == expected_role, f"signed in as {who}"):
        print(f"  {Y}Stopping here: every other test would only show this same problem.{N}")
        return 1

    step("Browse")
    try:
        folders, _ = svc.list_level("converted/")
        check("List customer folders in converted/", {"converted/agency-a/", "converted/agency-b/"} <= set(folders), ", ".join(folders))
    except Exception as e:  # noqa: BLE001
        check("List customer folders in converted/", False, err(e))

    step("Download (small file, then the 116 MB file)")
    with tempfile.TemporaryDirectory(prefix="curwork-autotest-") as tmp:
        for key in (SMALL_KEY, BIG_KEY):
            try:
                files = svc.expand_selection([key])
                t0 = time.time()
                got = svc.download(files, Path(tmp))
                secs = max(time.time() - t0, 0.001)
                size = got[0].stat().st_size
                check(f"Download {key.split('/')[-1]}", size == files[0].size,
                      f"{core.human_size(size)} in {secs:.1f}s ({size / secs / 1048576:.1f} MB/s)")
            except Exception as e:  # noqa: BLE001
                check(f"Download {key.split('/')[-1]}", False, f"{err(e)}  ->  {core.classify_error(e)[1].splitlines()[-1]}")

        step("Upload results (allowed folder) and check it's there")
        dest = f"priced/_autotest-{STAMP}/"
        result = Path(tmp) / "autotest-result.xlsx"
        result.write_bytes(os.urandom(200_000))
        try:
            check("Existing-file check before upload", svc.exists(dest + result.name) is False)
            svc.upload([(result, result.name)], dest)
            made.append(dest + result.name)
            check(f"Upload a result to {dest}", svc.exists(dest + result.name) is True)
        except Exception as e:  # noqa: BLE001
            check(f"Upload a result to {dest}", False, err(e))

        step("Things billers must NOT be able to do")
        try:
            svc.check_destination("converted/agency-a/2026-10/")
            check("CurWork refuses results in converted/", False, "check_destination allowed it")
        except core.CurWorkError:
            check("CurWork refuses results in converted/", True)
        raw = svc.client
        bad_key = f"converted/_autotest-{STAMP}/must-be-refused.xlsx"
        try:
            raw.put_object(Bucket=settings.bucket, Key=bad_key, Body=b"x")
            made.append(bad_key)
            check("AWS refuses writing to converted/", False, "the upload was ALLOWED - the permission set is too broad")
        except ClientError as e:
            check("AWS refuses writing to converted/", e.response["Error"]["Code"] in ("AccessDenied", "403"), err(e))
        if made:
            try:
                raw.delete_object(Bucket=settings.bucket, Key=made[0])
                check("AWS refuses deleting a result", False, "the delete was ALLOWED")
            except ClientError as e:
                check("AWS refuses deleting a result", e.response["Error"]["Code"] in ("AccessDenied", "403"), err(e))
        try:
            raw.list_objects_v2(Bucket=settings.bucket, Prefix="", Delimiter="/")
            check("AWS refuses listing the whole bucket", False, "listing outside CurWork's folders was ALLOWED")
        except ClientError as e:
            check("AWS refuses listing the whole bucket", e.response["Error"]["Code"] in ("AccessDenied", "403"), err(e))

        step("Log upload (what Finish does)")
        log = Path(tmp) / f"curwork-autotest-{STAMP}.log"
        log.write_text(f"CurWork automated test {STAMP}\n")
        try:
            key = svc.upload_log(log)
            made.append(key)
            check("Upload the log to logs/", bool(key), key or "")
        except Exception as e:  # noqa: BLE001
            check("Upload the log to logs/", False, err(e))

    step("Remove what this test made (admin profile) and check it's gone")
    admin = boto3.Session(profile_name=os.environ["CURWORK_ADMIN_PROFILE"], region_name=settings.region).client("s3")
    for key in made:
        try:
            versions = admin.list_object_versions(Bucket=settings.bucket, Prefix=key)
            objs = [{"Key": v["Key"], "VersionId": v["VersionId"]}
                    for v in versions.get("Versions", []) + versions.get("DeleteMarkers", []) if v["Key"] == key]
            if objs:
                admin.delete_objects(Bucket=settings.bucket, Delete={"Objects": objs, "Quiet": True})
            left = [v for v in admin.list_object_versions(Bucket=settings.bucket, Prefix=key).get("Versions", []) if v["Key"] == key]
            check(f"Removed {key}", not left, f"{len(objs)} version(s) deleted")
        except Exception as e:  # noqa: BLE001
            check(f"Removed {key}", False, err(e))

    bad = results.count(False)
    print(f"\n  {G + f'All {len(results)} real AWS checks passed.' + N if not bad else R + f'{bad} of {len(results)} real AWS checks FAILED.' + N}")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - always end with a readable line
        print(f"  {R}FAIL{N}  The test itself stopped: {err(e)}")
        sys.exit(1)
