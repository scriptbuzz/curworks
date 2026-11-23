#!/bin/bash
# CurWork Beta 0.015 - DRAFT - For Internal Use (FPT) - test cleanup - updated 2026-11-23 00:55 UTC - modified by: mbitar
# Finds EVERYTHING the CurWork test created, even after a crash, lists it, and deletes only what you pick:
#   S3:      buckets named curwork-test-* or tagged Purpose=CurWork-test, in any Region (with every file
#            version and unfinished upload)
#   Identity Center: the biller test permission set (tagged Purpose=CurWork-test) and its assignments
#   AWS CLI: the CurWork test profiles and sign-in session in ~/.aws/config (names from curwork_test.env), the saved sign-in token
#            for that session, and config backups this cleanup made before
#   Mac:     CurWork's work folder (~/CurWork), crash log, preferences file, temp files, and the test
#            scripts' output and helper files
# Nothing is deleted until you type confirm. Every delete is re-checked and shown as PASS or FAIL.
# The CurWork program, the test scripts and the sample workbooks are never listed.
# Results are saved to delete_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
exec > >(tee "$HERE/delete_results.txt") 2>&1
echo "== CurWork test cleanup - $(date -u '+%Y-%m-%d %H:%M UTC')"
export AWS_PAGER="" PYTHONUNBUFFERED=1
pause() { [ "$CURWORK_RESET" = "1" ] || read -n1 -r -p "$1"; }   # no key wait when run by Reset everything
. "$HERE/tools/test_env.sh" || { read -n1 -r -p "Press any key to close."; exit 1; }
aws sts get-caller-identity --profile "$CURWORK_ADMIN_PROFILE" >/dev/null 2>&1 || aws sso login --profile "$CURWORK_ADMIN_PROFILE" || { pause "Sign-in failed. Press any key to close."; exit 1; }
# The Python code comes in on file descriptor 3, so the keyboard stays connected for your answers.
CurWork-app/.venv/bin/python /dev/fd/3 3<<'PY'
import datetime, glob, hashlib, json, os, re, shutil, sys, time
import boto3
from botocore.exceptions import ClientError

HL = lambda s: f"\033[1;30;43m {s} \033[0m"          # black on yellow: what to type
BOLD = lambda s: f"\033[1m{s}\033[0m"
G, R, N = "\033[1;32m", "\033[1;31m", "\033[0m"
HOME = os.path.expanduser("~")
HERE = os.getcwd()                                   # the CurWorks folder
TOOL = os.path.join(HERE, "CurWork-app")
E = os.environ
ACCOUNT = E["CURWORK_ACCOUNT"]

def settings_bucket():
    """The test bucket CurWork uses: setup saves it in Parameter Store and notes it in test_bucket.txt."""
    try:
        return open(os.path.join(HERE, "test_bucket.txt"), encoding="utf-8").read().split()[0]
    except (OSError, IndexError):
        return ""

def count_files(path):
    return sum(len(f) for _, _, f in os.walk(path))

in_use = settings_bucket()
session = boto3.Session(profile_name=E["CURWORK_ADMIN_PROFILE"])
s3 = session.client("s3")
items = []   # dicts: group, kind, name, detail, plus kind-specific keys

print(BOLD("Looking for everything the CurWork test created (S3, Identity Center and this Mac)..."))

# ---- 1. S3 buckets: by name OR by the Purpose=CurWork-test tag, in every Region ----
for b in s3.list_buckets().get("Buckets", []):
    name = b["Name"]
    by_name = name.startswith("curwork-test-")
    by_tag = False
    if not by_name:
        try:
            tags = {t["Key"]: t["Value"] for t in s3.get_bucket_tagging(Bucket=name)["TagSet"]}
            by_tag = tags.get("Purpose") == "CurWork-test"
        except ClientError:
            pass   # no tags, or no permission to read them: not ours
    if not (by_name or by_tag):
        continue
    try:
        region = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
        rc = session.client("s3", region_name=region)
        versions = sum(len(p.get("Versions", [])) + len(p.get("DeleteMarkers", []))
                       for p in rc.get_paginator("list_object_versions").paginate(Bucket=name))
        uploads = len(rc.list_multipart_uploads(Bucket=name).get("Uploads", []))
        made = b["CreationDate"].astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        detail = f"S3 bucket in {region}, created {made}, {versions} file version(s)"
        if uploads:
            detail += f", {uploads} unfinished upload(s)"
    except ClientError as e:
        region, detail = None, f"S3 bucket (couldn't read details: {e.response.get('Error', {}).get('Code')})"
    if name == in_use:
        detail += "  <- CurWork is set to use this one"
    if by_tag and not by_name:
        detail += "  (found by its CurWork-test tag)"
    items.append(dict(group="S3", kind="bucket", name=name, region=region, detail=detail))

# ---- 1b. Identity Center: CurWork test permission sets (by name CurWork* AND tag Purpose=CurWork-test) ----
sso = session.client("sso-admin", region_name=E["CURWORK_SSO_REGION"])
try:
    instances = sso.list_instances()["Instances"]
except ClientError:
    instances = []          # no Identity Center admin rights: nothing to find here
for inst in instances:
    for page in sso.get_paginator("list_permission_sets").paginate(InstanceArn=inst["InstanceArn"]):
        for ps in page["PermissionSets"]:
            d = sso.describe_permission_set(InstanceArn=inst["InstanceArn"], PermissionSetArn=ps)["PermissionSet"]
            tags = {t["Key"]: t["Value"] for t in sso.list_tags_for_resource(InstanceArn=inst["InstanceArn"], ResourceArn=ps).get("Tags", [])}
            if d["Name"].startswith("CurWork") and tags.get("Purpose") == "CurWork-test":
                accts = [a for p2 in sso.get_paginator("list_accounts_for_provisioned_permission_set").paginate(
                         InstanceArn=inst["InstanceArn"], PermissionSetArn=ps) for a in p2["AccountIds"]]
                items.append(dict(group="Identity Center", kind="permset", name=d["Name"], arn=ps, instance=inst["InstanceArn"],
                                  accounts=accts, detail=f"Permission set for CurWork's biller test sign-in, in {len(accts)} account(s)"))

# ---- 2. AWS CLI settings CurWork added on this Mac ----
cfg_path = os.path.join(HOME, ".aws", "config")
cfg_text = open(cfg_path).read() if os.path.exists(cfg_path) else ""
for header, what in ((f"[profile {E['CURWORK_PROFILE']}]", "AWS CLI profile CurWork added (biller test sign-in)"),
                     ("[profile curwork-readonly]", "AWS CLI profile CurWork added (old read-only sign-in)"),
                     ("[profile curwork-ic-admin]", "AWS CLI profile the test added to manage Identity Center (management account)"),
                     (f"[sso-session {E['CURWORK_SSO_SESSION']}]", "AWS CLI sign-in session CurWork added")):
    if header in cfg_text:
        items.append(dict(group="AWS CLI", kind="config", name=header, detail=f"{what}, in ~/.aws/config"))
token = os.path.join(HOME, ".aws", "sso", "cache", hashlib.sha1(E["CURWORK_SSO_SESSION"].encode()).hexdigest() + ".json")
if os.path.exists(token):
    items.append(dict(group="AWS CLI", kind="file", name=token, detail="Saved sign-in token for the curwork-test session"))
for f in sorted(glob.glob(os.path.join(HOME, ".aws", "config.curwork-backup-*"))):
    items.append(dict(group="AWS CLI", kind="file", name=f, detail="Backup of ~/.aws/config made by this cleanup"))

# ---- 3. Files CurWork and the test scripts made on this Mac ----
work = os.path.join(HOME, "CurWork")                       # CurWork's work folder on a Mac
if os.path.isdir(work):
    items.append(dict(group="This Mac", kind="folder", name=work,
                      detail=f"CurWork work folder (In, Out, Logs, state): {count_files(work)} file(s), may hold sample workbooks"))
for f, what in ((os.path.join(HOME, "CurWork-crash.log"), "CurWork crash report"),
                (os.path.join(TOOL, "curwork_user_settings.json"), "Your CurWork preferences (recent and pinned folders, layout)"),
                (os.path.join(HERE, "test_bucket.txt"), "Note of which test bucket setup made"),
                (os.path.join(HERE, ".bucket_policy_test.json"), "Copy of the bucket policy setup applied"),
                (os.path.join(HERE, "setup_results.txt"), "Output of the last setup run"),
                (os.path.join(HERE, "curwork_run_output.txt"), "Output of the last CurWork run"),
                (os.path.join(HERE, "mac_check_results.txt"), "Output of the Mac check")):
    if os.path.exists(f):
        items.append(dict(group="This Mac", kind="file", name=f, detail=what))
for f in sorted(glob.glob(os.path.join(TOOL, ".curwork-*.tmp")) + glob.glob(os.path.join(TOOL, ".curwork-write-test-*"))
                + glob.glob(os.path.join(work, ".curwork-*.tmp"))):
    items.append(dict(group="This Mac", kind="file", name=f, detail="Temporary file left by an interrupted save"))

if in_use and not any(i["kind"] == "bucket" and i["name"] == in_use for i in items):
    print(f"Note: CurWork is set to use {in_use}, which doesn't exist anymore. Run setup_test_bucket.command before testing CurWork again.")
if not items:
    print("Nothing from the CurWork test was found. Nothing to delete."); sys.exit(0)

print()
group = None
for i, it in enumerate(items, 1):
    if it["group"] != group:
        group = it["group"]; print(BOLD(f"  {group}"))
    shown = it["name"].replace(HOME, "~")
    print(f"   {BOLD(str(i))}. {shown}\n        {it['detail']}")
print()
if os.environ.get("CURWORK_RESET") == "1":
    pick = "all"
    print(BOLD("Reset everything: all items above are picked."))
else:
    pick = input(f"Type the numbers to delete (for example 1 3), a range like 2-5, or {HL('all')} for everything. Press Enter to cancel: ").strip().lower()
if not pick:
    print("Cancelled. Nothing was deleted."); sys.exit(3)   # 3 = cancelled
if pick == "all":
    chosen = items
else:
    nums = set()
    for part in re.split(r"[\s,]+", pick):          # accepts 1 3, 1,3, 2-5 and 1.
        part = part.strip(".")
        m = re.fullmatch(r"(\d+)-(\d+)", part)
        if m:
            nums.update(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            nums.add(int(part))
    nums = sorted(nums)
    chosen = [items[n - 1] for n in nums if 1 <= n <= len(items)]
if not chosen:
    print(f"\"{pick}\" doesn't match any number from 1 to {len(items)}. Nothing was deleted. Type numbers like 1 3, a range like 2-5, or all."); sys.exit(3)   # 3 = cancelled

print("\n" + BOLD("These will be PERMANENTLY deleted:"))
for it in chosen:
    print(f"  - {it['name'].replace(HOME, '~')}  ({it['detail'].strip()})")
if input(f"\nType {HL('confirm')} to delete them (anything else cancels): ").strip() != "confirm":
    print("You didn't type confirm. Nothing was deleted."); sys.exit(3)   # 3 = cancelled

results = []   # (name, ok, detail)

def bucket_gone(rc, name):
    for _ in range(5):                      # S3 can take a moment to report a deleted bucket as gone
        try:
            rc.head_bucket(Bucket=name)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchBucket", "NotFound"):
                return True
            raise
        time.sleep(2)
    return False

for it in [c for c in chosen if c["kind"] == "bucket"]:
    name = it["name"]
    try:
        rc = session.client("s3", region_name=it["region"] or "us-east-1")
        for up in rc.list_multipart_uploads(Bucket=name).get("Uploads", []):
            rc.abort_multipart_upload(Bucket=name, Key=up["Key"], UploadId=up["UploadId"])
        failed = []
        for page in rc.get_paginator("list_object_versions").paginate(Bucket=name):
            objs = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in page.get("Versions", []) + page.get("DeleteMarkers", [])]
            for i in range(0, len(objs), 1000):
                resp = rc.delete_objects(Bucket=name, Delete={"Objects": objs[i:i + 1000], "Quiet": True})
                failed += [f"{e['Key']} ({e.get('Code')})" for e in resp.get("Errors", [])]
        if failed:
            results.append((name, False, f"{len(failed)} file version(s) couldn't be deleted: " + "; ".join(failed[:5])))
            continue
        rc.delete_bucket(Bucket=name)
        ok = bucket_gone(rc, name)
        results.append((name, ok, "bucket and every file version deleted; S3 confirms it's gone" if ok
                        else "delete was accepted but S3 still reports the bucket"))
    except ClientError as e:
        err = e.response.get("Error", {})
        results.append((name, False, f"{err.get('Code')}: {err.get('Message')}"))

def wait_status(get):
    for _ in range(60):
        st = get()
        if st["Status"] != "IN_PROGRESS":
            return st
        time.sleep(3)
    return {"Status": "TIMED OUT"}

for it in [c for c in chosen if c["kind"] == "permset"]:
    inst, ps = it["instance"], it["arn"]
    try:
        for acct in it["accounts"]:                      # remove every assignment first, then the set itself
            for page in sso.get_paginator("list_account_assignments").paginate(InstanceArn=inst, AccountId=acct, PermissionSetArn=ps):
                for a in page["AccountAssignments"]:
                    rid = sso.delete_account_assignment(InstanceArn=inst, TargetId=acct, TargetType="AWS_ACCOUNT",
                        PermissionSetArn=ps, PrincipalType=a["PrincipalType"], PrincipalId=a["PrincipalId"]
                        )["AccountAssignmentDeletionStatus"]["RequestId"]
                    st = wait_status(lambda: sso.describe_account_assignment_deletion_status(
                        InstanceArn=inst, AccountAssignmentDeletionRequestId=rid)["AccountAssignmentDeletionStatus"])
                    if st["Status"] != "SUCCEEDED":
                        raise RuntimeError(f"removing an assignment in {acct}: {st['Status']} {st.get('FailureReason', '')}")
        sso.delete_permission_set(InstanceArn=inst, PermissionSetArn=ps)
        try:
            sso.describe_permission_set(InstanceArn=inst, PermissionSetArn=ps); ok = False
        except ClientError:
            ok = True
        results.append((it["name"], ok, "assignments and permission set deleted; Identity Center confirms it's gone" if ok
                        else "delete was accepted but Identity Center still lists it"))
    except (ClientError, RuntimeError) as e:
        msg = f"{e.response['Error']['Code']}: {e.response['Error']['Message']}" if isinstance(e, ClientError) else str(e)
        results.append((it["name"], False, msg))

cfg_targets = [c["name"] for c in chosen if c["kind"] == "config"]
if cfg_targets:
    backup = cfg_path + ".curwork-backup-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        shutil.copy2(cfg_path, backup)
        out, skip = [], False
        for line in cfg_text.splitlines(keepends=True):
            if line.strip().startswith("["):
                skip = line.strip() in cfg_targets
            if not skip:
                out.append(line)
        open(cfg_path, "w").write("".join(out))
        now = open(cfg_path).read()
        for t in cfg_targets:
            ok = t not in now
            results.append((t, ok, f"removed from ~/.aws/config (backup: {backup.replace(HOME, '~')})" if ok
                            else "still in ~/.aws/config"))
    except OSError as e:
        for t in cfg_targets:
            results.append((t, False, f"couldn't update ~/.aws/config: {e}"))

for it in [c for c in chosen if c["kind"] in ("file", "folder")]:
    path = it["name"]
    try:
        if it["kind"] == "folder":
            shutil.rmtree(path)
        else:
            os.remove(path)
        ok = not os.path.exists(path)
        results.append((path.replace(HOME, "~"), ok, "deleted; confirmed gone" if ok else "still there after deleting"))
    except OSError as e:
        results.append((path.replace(HOME, "~"), False, f"couldn't delete: {e.strerror or e}"))

print("\n" + BOLD("Result (re-checked after deleting):"))
for name, ok, detail in results:
    print(f"  {G + 'PASS' + N if ok else R + 'FAIL' + N}  {name}\n          {detail}")
bad = sum(1 for _, ok, _ in results if not ok)
print("\n  " + (G + f"All {len(results)} item(s) deleted and confirmed gone." + N if not bad
                 else R + f"{bad} of {len(results)} item(s) NOT confirmed deleted. See FAIL lines above." + N))
if any(n == in_use and ok for n, ok, _ in results):
    print("  CurWork was set to use a bucket you deleted. Run setup_test_bucket.command before testing again.")
sys.exit(1 if bad else 0)
PY
RC=$?
pause "Press any key to close."
exit $RC
