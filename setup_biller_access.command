#!/bin/bash
# CurWork Beta 0.011 - DRAFT - For Internal Use (FPT) - biller test access - updated 2026-11-22 16:51 UTC - modified by: mbitar
# Sets up the sign-in CurWork uses for testing: an IAM Identity Center permission set (CURWORK_ROLE, default CurWorkBillerTest),
# built from CurWork's own least-privilege biller policy (iam/biller_permission_set_policy.json), limited to
# test buckets (curwork-test-<account>-*), and assigned to you in the test account (CURWORK_ACCOUNT).
# Safe to run again: it reuses what's there and only fixes what differs. Ends with PASS/FAIL checks.
# Needs Identity Center admin rights: the organization's management account or a delegated admin account.
# If the admin profile isn't one, set CURWORK_IC_PROFILE in curwork_test.env, or run:  CURWORK_IC_PROFILE=<profile> ./setup_biller_access.command
# Results are saved to setup_biller_access_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
exec > >(tee "$HERE/setup_biller_access_results.txt") 2>&1
export AWS_PAGER="" PYTHONUNBUFFERED=1
. "$HERE/tools/test_env.sh" || { read -n1 -r -p "Press any key to close."; exit 1; }
pause() { [ "$CURWORK_RESET" = "1" ] || read -n1 -r -p "$1"; }
echo "== CurWork biller test access - $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "This creates or updates the Identity Center permission set $CURWORK_ROLE (least-privilege biller"
echo "policy, test buckets only) and assigns it to you in the test account."
echo "If the admin profile can't manage Identity Center, it finds the organization's management account and adds an"
echo "AWS CLI profile, curwork-ic-admin, for your admin role there (backup of ~/.aws/config first)."
if [ "$CURWORK_SKIP_CONFIRM" != "1" ]; then
  read -r -p "$(printf 'Type \033[1;30;43m confirm \033[0m to go ahead (anything else cancels): ')" CONFIRM
  [ "$CONFIRM" = "confirm" ] || { echo "You didn't type confirm. Nothing was changed."; pause "Press any key to close."; exit 3; }
fi
for P in "$CURWORK_ADMIN_PROFILE" ${CURWORK_IC_PROFILE:-}; do
  aws sts get-caller-identity --profile "$P" >/dev/null 2>&1 || aws sso login --profile "$P" || { echo "STOPPED: sign-in to $P failed."; pause "Press any key to close."; exit 1; }
done
CurWork-Beta-0.011/.venv/bin/python /dev/fd/3 3<<'PY'
import json, os, shutil, sys, time
import boto3
from botocore.exceptions import ClientError

E = os.environ
NAME, ACCOUNT, SSO_REGION = E["CURWORK_ROLE"], E["CURWORK_ACCOUNT"], E["CURWORK_SSO_REGION"]
ADMIN = E["CURWORK_ADMIN_PROFILE"]
BUCKETS = f"arn:aws:s3:::curwork-test-{ACCOUNT}-*"
G, R, N = "\033[1;32m", "\033[1;31m", "\033[0m"
def stop(msg):
    print(f"  {R}FAIL{N}  {msg}\nSTOPPED."); sys.exit(1)

import os
IC_PROFILE = os.environ.get("CURWORK_IC_PROFILE") or ADMIN   # who manages Identity Center
s = boto3.Session(profile_name=ADMIN)                       # the test account (S3, KMS, IAM role check)
me = s.client("sts").get_caller_identity()
if me["Account"] != ACCOUNT:
    stop(f"{ADMIN} is account {me['Account']}, not {ACCOUNT}.")
user_name = me["Arn"].split("/")[-1]          # SSO session name = your Identity Center user name
ic = boto3.Session(profile_name=IC_PROFILE) if IC_PROFILE != ADMIN else s
print(f"  Identity Center is managed with profile {IC_PROFILE} (account {ic.client('sts').get_caller_identity()['Account']})")
sso = ic.client("sso-admin", region_name=SSO_REGION)
ids = ic.client("identitystore", region_name=SSO_REGION)

print("\n== Find IAM Identity Center")
try:
    inst = sso.list_instances()["Instances"]
except ClientError as e:
    inst, why = [], e.response["Error"]["Code"]
else:
    why = "none visible"
if not inst:
    stop(f"Can't see an IAM Identity Center instance from {ADMIN} ({why}). Permission sets are managed from the "
         "organization's management account or a delegated admin account. Ask whoever runs Identity Center to run "
         "this script, or to create CurWorkBillerTest from iam/biller_permission_set_policy.json.")
arn, store = inst[0]["InstanceArn"], inst[0]["IdentityStoreId"]
print(f"  Instance: {arn}")

print("\n== Build the policy from iam/biller_permission_set_policy.json")
text = open("CurWork-Beta-0.011/iam/biller_permission_set_policy.json").read()
text = text.replace("arn:aws:s3:::BUCKET_NAME", BUCKETS)
try:
    key_arn = s.client("kms", region_name=SSO_REGION).describe_key(KeyId="alias/aws/s3")["KeyMetadata"]["Arn"]
except ClientError:
    stop("The S3 encryption key (alias/aws/s3) isn't there yet. Run 'Create the test bucket' first.")
text = text.replace("arn:aws:kms:REGION:ACCOUNT_ID:key/KMS_KEY_ID", key_arn)
text = text.replace("arn:aws:ssm:REGION:ACCOUNT_ID:parameter", f"arn:aws:ssm:{SSO_REGION}:{ACCOUNT}:parameter")
policy = json.loads(text)
print(f"  Buckets: {BUCKETS}\n  KMS key: {key_arn}")

print("\n== Permission set")
ps = None
def can_manage(client):
    try:
        client.list_permission_sets(InstanceArn=arn, MaxResults=1)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("AccessDeniedException", "AccessDenied"):
            return False
        raise

if not can_manage(sso):
    # The admin profile's account is a member account. Identity Center is managed from the organization's management account,
    # so find that account and a role you have there, add an AWS CLI profile for it, and use that.
    import configparser, hashlib, shutil, datetime
    print(f"  {IC_PROFILE} (account {me['Account']}) can't manage Identity Center. Looking for the management account...")
    try:
        mgmt = s.client("organizations").describe_organization()["Organization"]["MasterAccountId"]
    except ClientError as e:
        stop(f"Couldn't find the organization's management account: {e.response['Error']['Code']}")
    print(f"  Management account: {mgmt}")
    cfg_file = os.path.expanduser("~/.aws/config")
    cp = configparser.RawConfigParser(); cp.read(cfg_file)
    base = dict(cp.items(f"profile {ADMIN}"))
    sess_name = base.get("sso_session")
    if sess_name:
        sso_region = cp.get(f"sso-session {sess_name}", "sso_region", fallback=SSO_REGION)
        token_file = hashlib.sha1(sess_name.encode()).hexdigest()
    else:
        sso_region = base.get("sso_region", SSO_REGION)
        token_file = hashlib.sha1(base.get("sso_start_url", "").encode()).hexdigest()
    try:
        token = json.load(open(os.path.expanduser(f"~/.aws/sso/cache/{token_file}.json")))["accessToken"]
        roles = [r["roleName"] for r in boto3.client("sso", region_name=sso_region).list_account_roles(
                 accessToken=token, accountId=mgmt)["roleList"]]
    except (OSError, KeyError, ClientError) as e:
        stop(f"Couldn't list your roles in the management account {mgmt}: {e}")
    role = next((r for r in ("AWSAdministratorAccess", "AdministratorAccess") if r in roles),
                next((r for r in roles if "admin" in r.lower()), None))
    if not role:
        stop(f"Your Identity Center user has no admin role in the management account {mgmt} "
             f"(roles there: {', '.join(roles) or 'none'}). Ask the Identity Center admin to run this script.")
    IC_PROFILE = "curwork-ic-admin"
    if not cp.has_section(f"profile {IC_PROFILE}"):
        backup = cfg_file + ".curwork-backup-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(cfg_file, backup)
        lines = [f"[profile {IC_PROFILE}]"]
        if sess_name:
            lines.append(f"sso_session = {sess_name}")
        else:
            lines += [f"sso_start_url = {base.get('sso_start_url')}", f"sso_region = {sso_region}"]
        lines += [f"sso_account_id = {mgmt}", f"sso_role_name = {role}", f"region = {SSO_REGION}", ""]
        text = open(cfg_file).read()
        with open(cfg_file, "a") as fh:
            fh.write(("" if text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n") + "\n".join(lines))
        print(f"  Added AWS CLI profile {IC_PROFILE} ({role} in {mgmt}) to ~/.aws/config (backup: {backup})")
    ic = boto3.Session(profile_name=IC_PROFILE)
    sso = ic.client("sso-admin", region_name=SSO_REGION)
    ids = ic.client("identitystore", region_name=SSO_REGION)
    if not can_manage(sso):
        stop(f"{role} in the management account {mgmt} can't manage Identity Center either. Ask the Identity Center admin to run this script.")
    print(f"  Using {IC_PROFILE} to manage Identity Center.")
for page in sso.get_paginator("list_permission_sets").paginate(InstanceArn=arn):
    for p in page["PermissionSets"]:
        if sso.describe_permission_set(InstanceArn=arn, PermissionSetArn=p)["PermissionSet"]["Name"] == NAME:
            ps = p
created = ps is None
if created:
    ps = sso.create_permission_set(InstanceArn=arn, Name=NAME, SessionDuration="PT8H",
        Description="CurWork test: least-privilege biller access to curwork-test buckets",
        Tags=[{"Key": "Purpose", "Value": "CurWork-test"}])["PermissionSet"]["PermissionSetArn"]
    print(f"  Created {NAME}")
else:
    print(f"  Reusing {NAME}")
sso.put_inline_policy_to_permission_set(InstanceArn=arn, PermissionSetArn=ps, InlinePolicy=json.dumps(policy))

print(f"\n== Assign it to you ({user_name}) in {ACCOUNT}")
try:
    uid = ids.get_user_id(IdentityStoreId=store, AlternateIdentifier={
        "UniqueAttribute": {"AttributePath": "userName", "AttributeValue": user_name}})["UserId"]
except ClientError as e:
    stop(f"Couldn't find Identity Center user '{user_name}': {e.response['Error']['Code']}")
assigned = any(a["PrincipalId"] == uid for page in sso.get_paginator("list_account_assignments").paginate(
    InstanceArn=arn, AccountId=ACCOUNT, PermissionSetArn=ps) for a in page["AccountAssignments"])
def wait(get, rid, key):
    for _ in range(60):
        st = get(rid)[key]
        if st["Status"] != "IN_PROGRESS":
            return st
        time.sleep(3)
    return {"Status": "TIMED OUT"}
if not assigned:
    rid = sso.create_account_assignment(InstanceArn=arn, TargetId=ACCOUNT, TargetType="AWS_ACCOUNT",
        PermissionSetArn=ps, PrincipalType="USER", PrincipalId=uid)["AccountAssignmentCreationStatus"]["RequestId"]
    st = wait(lambda r: sso.describe_account_assignment_creation_status(InstanceArn=arn, AccountAssignmentCreationRequestId=r),
              rid, "AccountAssignmentCreationStatus")
    print(f"  Assignment: {st['Status']} {st.get('FailureReason', '')}")
else:
    rid = sso.provision_permission_set(InstanceArn=arn, PermissionSetArn=ps,
        TargetType="ALL_PROVISIONED_ACCOUNTS")["PermissionSetProvisioningStatus"]["RequestId"]
    st = wait(lambda r: sso.describe_permission_set_provisioning_status(InstanceArn=arn, ProvisionPermissionSetRequestId=r),
              rid, "PermissionSetProvisioningStatus")
    print(f"  Already assigned. Pushed the policy to the account: {st['Status']} {st.get('FailureReason', '')}")

print("\n== Point CurWork at this sign-in (admin settings file)")
cfg_path = "CurWork-Beta-0.011/curwork_admin_settings.json"
if not os.path.exists(cfg_path):   # fresh clone: start from the example (the real file is never in Git)
    shutil.copy("CurWork-Beta-0.011/curwork_admin_settings.example.json", cfg_path)
cfg = json.load(open(cfg_path, encoding="utf-8-sig"))
cfg["aws_profile"] = E["CURWORK_PROFILE"]
cfg.setdefault("sso", {}).update({"session_name": E["CURWORK_SSO_SESSION"], "start_url": E["CURWORK_SSO_START_URL"],
                                  "sso_region": SSO_REGION, "account_id": ACCOUNT, "role_name": NAME})
tmp = cfg_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2); fh.write("\n")
import os; os.replace(tmp, cfg_path)
print(f"  CurWork will sign in with profile {E['CURWORK_PROFILE']} ({NAME}).")

print("\n== Check everything (re-reads AWS)")
results = []
def check(label, ok, detail=""):
    results.append(ok); print(f"  {G+'PASS'+N if ok else R+'FAIL'+N}  {label}" + (f"  ({detail})" if detail else ""))
d = sso.describe_permission_set(InstanceArn=arn, PermissionSetArn=ps)["PermissionSet"]
check(f"Permission set {NAME} exists", d["Name"] == NAME)
check("Sessions last at most 8 hours", d.get("SessionDuration") == "PT8H", d.get("SessionDuration"))
got = json.loads(sso.get_inline_policy_for_permission_set(InstanceArn=arn, PermissionSetArn=ps)["InlinePolicy"] or "{}")
check("Policy matches CurWork's biller policy (test buckets only)", got == policy)
tags = {t["Key"]: t["Value"] for t in sso.list_tags_for_resource(InstanceArn=arn, ResourceArn=ps).get("Tags", [])}
check("Tagged Purpose=CurWork-test", tags.get("Purpose") == "CurWork-test")
assigned = any(a["PrincipalId"] == uid for page in sso.get_paginator("list_account_assignments").paginate(
    InstanceArn=arn, AccountId=ACCOUNT, PermissionSetArn=ps) for a in page["AccountAssignments"])
check(f"Assigned to {user_name} in {ACCOUNT}", assigned)
iam = s.client("iam")
role = None
for _ in range(20):
    roles = [r["RoleName"] for p in iam.get_paginator("list_roles").paginate(PathPrefix="/aws-reserved/sso.amazonaws.com/")
             for r in p["Roles"] if r["RoleName"].startswith(f"AWSReservedSSO_{NAME}_")]
    if roles:
        role = roles[0]; break
    time.sleep(3)
check("Its IAM role exists in the account", bool(role), role or "not there yet")
c = json.load(open(cfg_path, encoding="utf-8-sig"))
check("CurWork's admin settings use this sign-in", c.get("aws_profile") == E["CURWORK_PROFILE"] and c["sso"].get("role_name") == NAME,
      f"{c.get('aws_profile')} / {c['sso'].get('role_name')}")
bad = results.count(False)
print(f"\n  {G+'All '+str(len(results))+' checks passed.'+N if not bad else R+str(bad)+' of '+str(len(results))+' checks FAILED.'+N}")
sys.exit(1 if bad else 0)
PY
RC=$?
[ $RC -eq 0 ] && echo && echo "== Done. CurWork can now sign in as $CURWORK_ROLE (profile $CURWORK_PROFILE)."
pause "Press any key to close."
exit $RC
