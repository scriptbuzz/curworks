#!/bin/bash
# CurWork Beta 0.017 - DRAFT - For Internal Use (FPT) - test bucket setup - updated 2026-11-23 01:38 UTC - modified by: mbitar
# Creates a NEW test bucket in the test account (CURWORK_ACCOUNT in curwork_test.env), set up the way the Admin and Security Guide describes,
# uploads the made-up sample workbooks, and points CurWork's admin settings file at the bucket.
# The admin profile (CURWORK_ADMIN_PROFILE) is used ONLY for this setup. CurWork itself signs in with the CurWorkBillerTest permission
# set (least-privilege biller policy) through its own profile, curwork-biller, which CurWork adds to
# ~/.aws/config at the first Sign in. The last step runs setup_biller_access.command to create or update it.
# It doesn't touch any existing bucket. Results are saved to setup_results.txt next to this file.

HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
exec > >(tee "$HERE/setup_results.txt") 2>&1
export AWS_PAGER=""
pause() { [ "$CURWORK_RESET" = "1" ] || read -n1 -r -p "$1"; }   # no key wait when run by Reset everything
. "$HERE/tools/test_env.sh" || { read -n1 -r -p "Press any key to close."; exit 1; }
PROFILE="$CURWORK_ADMIN_PROFILE"
step() { echo; echo "== $1"; shift; "$@" || { echo "STOPPED: that step failed. Nothing after it was done."; pause "Press any key to close."; exit 1; }; }

echo "== CurWork test bucket setup - $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "This will create a new S3 bucket named curwork-test-<account>-<date/time> in the $PROFILE account, with:"
echo "  Block Public Access, Versioning, SSE-KMS default encryption, a TLS-only bucket policy,"
echo "  and a rule that removes old versions after 30 days. Then it uploads the made-up sample workbooks"
echo "  (one is 116 MB) and creates or updates CurWork's biller test access (permission set CurWorkBillerTest)."
read -r -p "$(printf 'Type \033[1;30;43m confirm \033[0m to go ahead (anything else cancels): ')" CONFIRM
[ "$CONFIRM" = "confirm" ] || { echo "You didn't type confirm. Nothing was created."; pause "Press any key to close."; exit 1; }

if ! aws sts get-caller-identity --profile "$PROFILE" >/dev/null 2>&1; then
  step "Signing in to $PROFILE (finish it in the browser)" aws sso login --profile "$PROFILE"
fi
ACCOUNT="$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)" || exit 1
REGION="$(aws configure get region --profile "$PROFILE")"; REGION="${REGION:-us-east-1}"
if [ -f "$HERE/test_bucket.txt" ]; then
  read -r OLD _ < "$HERE/test_bucket.txt"
  if aws s3api head-bucket --bucket "$OLD" --profile "$PROFILE" >/dev/null 2>&1; then
    echo "STOPPED: a CurWork test bucket already exists ($OLD), so no new one was created."
    echo "Keep using it, or run delete_curwork_test_items.command first if you want a fresh one."
    pause "Press any key to close."; exit 2
  fi
fi
BUCKET="curwork-test-${ACCOUNT}-$(date -u +%Y%m%d%H%M)"
if [ "$ACCOUNT" != "$CURWORK_ACCOUNT" ]; then echo "STOPPED: $PROFILE is account $ACCOUNT, but the CurWork test account is $CURWORK_ACCOUNT. Nothing was created."; pause "Press any key to close."; exit 1; fi
echo "Account: $ACCOUNT   Region: $REGION   Bucket: $BUCKET"
A=(--profile "$PROFILE" --region "$REGION")

if [ "$REGION" = "us-east-1" ]; then
  step "Create the bucket" aws s3api create-bucket --bucket "$BUCKET" "${A[@]}"
else
  step "Create the bucket" aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration "LocationConstraint=$REGION" "${A[@]}"
fi
echo "$BUCKET $REGION" > "$HERE/test_bucket.txt"
step "Block Public Access" aws s3api put-public-access-block --bucket "$BUCKET" "${A[@]}" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
step "Turn on Versioning" aws s3api put-bucket-versioning --bucket "$BUCKET" "${A[@]}" --versioning-configuration Status=Enabled
step "Default encryption: SSE-KMS" aws s3api put-bucket-encryption --bucket "$BUCKET" "${A[@]}" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}'
step "Remove old versions after 30 days" aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" "${A[@]}" \
  --lifecycle-configuration '{"Rules":[{"ID":"curwork-test-old-versions","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":30},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}'
sed "s/BUCKET_NAME/$BUCKET/g" CurWork-app/iam/bucket_policy_additions.json > "$HERE/.bucket_policy_test.json"
step "Bucket policy: TLS 1.2 or higher only" aws s3api put-bucket-policy --bucket "$BUCKET" "${A[@]}" --policy "file://$HERE/.bucket_policy_test.json"
step "Tag the bucket" aws s3api put-bucket-tagging --bucket "$BUCKET" "${A[@]}" \
  --tagging 'TagSet=[{Key=Purpose,Value=CurWork-test},{Key=Data,Value=sample-only}]'

step "Upload sample workbooks" aws s3 cp sample-data/agency-a-cur-2026-09.xlsx "s3://$BUCKET/converted/agency-a/2026-09/" "${A[@]}"
step "Upload sample workbooks" aws s3 cp sample-data/agency-a-cur-2026-10.xlsx "s3://$BUCKET/converted/agency-a/2026-10/" "${A[@]}"
step "Upload sample workbooks" aws s3 cp sample-data/agency-b-cur-2026-10.xlsx "s3://$BUCKET/converted/agency-b/2026-10/" "${A[@]}"

step "Point CurWork at the test bucket (read-only sign-in)" CurWork-app/.venv/bin/python - "$BUCKET" "$REGION" "$PROFILE" <<'PY'
import json, sys, datetime, configparser, os
bucket, region, setup_profile = sys.argv[1:4]
# Find the SSO Region the admin profile uses (names and Regions only; no tokens are read).
cfg = configparser.RawConfigParser(); cfg.read(os.path.expanduser("~/.aws/config"))
sec = cfg["profile " + setup_profile]
sso_region = sec.get("sso_region") or (cfg["sso-session " + sec["sso_session"]].get("sso_region") if sec.get("sso_session") else None) or region
sys.path.insert(0, "CurWork-app")
import curwork_core as core, curwork_admin as admin
p = "CurWork-app/curwork_admin_settings.json"
if not os.path.exists(p):   # fresh clone: start from the example (the real file is never in Git)
    import shutil; shutil.copy("CurWork-app/curwork_admin_settings.example.json", p)
d = json.load(open(p, encoding="utf-8-sig"))
# The laptop file only holds the sign-in settings (CurWork refuses anything else). Notes for them stay.
d = {k: v for k, v in d.items() if k in core.LOCAL_KEYS or k in ("_version", "_help")
     or (k.startswith("_") and k.endswith("_help") and k[1:-5] in core.LOCAL_KEYS)}
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
d["_version"] = f"Admin settings for CurWork Beta 0.017 - DRAFT - For Internal Use (FPT) - Mac TEST settings - updated {stamp} - modified by: mbitar"
E = os.environ
d["region"], d["aws_profile"] = region, E["CURWORK_PROFILE"]
d["settings_parameter"] = d.get("settings_parameter") or core.DEFAULT_PARAMETER
d["sso"] = {"session_name": E["CURWORK_SSO_SESSION"], "start_url": E["CURWORK_SSO_START_URL"],
            "sso_region": sso_region, "account_id": E["CURWORK_ACCOUNT"], "role_name": E["CURWORK_ROLE"]}
json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
print(f"CurWork will sign in as {E['CURWORK_ROLE']} (profile {E['CURWORK_PROFILE']}, SSO Region {sso_region}).")
# The bucket is kept in Parameter Store. Save it there with the admin profile (billers can't change it).
store = admin.AdminStore(d["settings_parameter"], region, profile=setup_profile)
managed, version = store.load()
managed = dict(managed or {})
managed["bucket"] = bucket
managed["_version"] = f"Mac TEST settings - updated {stamp}"
print(f"Saved bucket {bucket} in Parameter Store {d['settings_parameter']} (version {store.save(managed, version)}).")
PY

step "Check everything was created (re-reads AWS)" CurWork-app/.venv/bin/python - "$BUCKET" "$REGION" "$PROFILE" <<'PY'
import json, os, sys, boto3
from botocore.exceptions import ClientError
bucket, region, profile = sys.argv[1:4]
s3 = boto3.Session(profile_name=profile, region_name=region).client("s3")
G, R, N = "\033[1;32m", "\033[1;31m", "\033[0m"
results = []
def check(name, fn):
    try:
        ok, detail = fn()
    except ClientError as e:
        ok, detail = False, e.response.get("Error", {}).get("Code", str(e))
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)
    results.append(ok)
    print(f"  {G+'PASS'+N if ok else R+'FAIL'+N}  {name}" + (f"  ({detail})" if detail else ""))
def bucket_exists():
    s3.head_bucket(Bucket=bucket); return True, ""
def versioning():
    st = s3.get_bucket_versioning(Bucket=bucket).get("Status"); return st == "Enabled", st or "off"
def encryption():
    r = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"][0]
    alg = r["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]; return alg == "aws:kms", alg
def public_block():
    c = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]; return all(c.values()), ""
def tls_policy():
    sids = {st.get("Sid") for st in json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])["Statement"]}
    return {"DenyNonTlsRequests", "DenyOldTls"} <= sids, ", ".join(sorted(x for x in sids if x))
def lifecycle():
    ids = [r["ID"] for r in s3.get_bucket_lifecycle_configuration(Bucket=bucket)["Rules"]]
    return "curwork-test-old-versions" in ids, ""
def tags():
    t = {x["Key"]: x["Value"] for x in s3.get_bucket_tagging(Bucket=bucket)["TagSet"]}; return t.get("Purpose") == "CurWork-test", ""
print(f"Checking s3://{bucket}")
check("Bucket exists", bucket_exists)
check("Versioning is on", versioning)
check("Default encryption is SSE-KMS", encryption)
check("Block Public Access is on (all 4 settings)", public_block)
check("Bucket policy refuses non-TLS and TLS older than 1.2", tls_policy)
check("Old-version cleanup rule is set", lifecycle)
check("Tagged Purpose=CurWork-test", tags)
for local, key in (("agency-a-cur-2026-09.xlsx", "converted/agency-a/2026-09/agency-a-cur-2026-09.xlsx"),
                   ("agency-a-cur-2026-10.xlsx", "converted/agency-a/2026-10/agency-a-cur-2026-10.xlsx"),
                   ("agency-b-cur-2026-10.xlsx", "converted/agency-b/2026-10/agency-b-cur-2026-10.xlsx")):
    def same_size(local=local, key=key):
        want = os.path.getsize(os.path.join("sample-data", local)); got = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
        return want == got, f"{got} of {want} bytes"
    check(f"In S3: {key}", same_size)
local = json.load(open("CurWork-app/curwork_admin_settings.json", encoding="utf-8-sig"))
def laptop_file_is_sign_in_only():
    sys.path.insert(0, "CurWork-app"); import curwork_core as core
    extra = sorted(k for k in local if not k.startswith("_") and k not in core.LOCAL_KEYS)
    return not extra, ", ".join(extra) or "sign-in settings only"
check("The laptop settings file only holds the sign-in settings", laptop_file_is_sign_in_only)
param = local.get("settings_parameter") or "/curwork/admin-settings"
if param:
    def parameter_points_here():
        got = json.loads(boto3.Session(profile_name=profile, region_name=region).client("ssm")
                         .get_parameter(Name=param)["Parameter"]["Value"]).get("bucket")
        return got == bucket, f"{param} says {got}"
    check("The admin settings in Parameter Store use this bucket", parameter_points_here)
bad = results.count(False)
print(f"\n  {G+'All '+str(len(results))+' checks passed.'+N if not bad else R+str(bad)+' of '+str(len(results))+' checks FAILED.'+N}")
sys.exit(1 if bad else 0)
PY

echo; echo "== Biller test access (CurWorkBillerTest permission set)"
CURWORK_SKIP_CONFIRM=1 CURWORK_RESET=1 bash "$HERE/setup_biller_access.command" || { echo "STOPPED: the bucket is ready, but biller test access isn't. See above, then run setup_biller_access.command."; pause "Press any key to close this window."; exit 1; }
echo; echo "== Done. Bucket $BUCKET and biller test access are ready. Next: build or start CurWork and click Sign in (it signs in as CurWorkBillerTest)."
pause "Press any key to close this window."
