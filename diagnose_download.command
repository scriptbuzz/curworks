#!/bin/bash
# CurWork Beta 0.011 - DRAFT - For Internal Use (FPT) - download check - updated 2026-11-22 16:52 UTC - modified by: mbitar
# Finds out why a download is refused. Read-only: it creates and changes nothing in AWS.
#   1. With the admin profile: lists the policies on the biller test role CurWork uses.
#   2. With $CURWORK_PROFILE (the sign-in CurWork uses): tries list, head and get on one sample file.
#   3. Copies the last 40 lines of today's CurWork log (~/CurWork/Logs) into the results file.
# Results are saved to diagnose_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
exec > >(tee "$HERE/diagnose_results.txt") 2>&1
export AWS_PAGER=""
. "$HERE/tools/test_env.sh" || { read -n1 -r -p "Press any key to close."; exit 1; }
echo "== CurWork download check - $(date -u '+%Y-%m-%d %H:%M UTC')"
read -r BUCKET REGION < test_bucket.txt
KEY="converted/agency-a/2026-10/agency-a-cur-2026-10.xlsx"
echo "Bucket: $BUCKET  Region: $REGION  File: $KEY"

echo; echo "== 1. Policies on the biller test role (checked with the admin profile)"
aws sts get-caller-identity --profile "$CURWORK_ADMIN_PROFILE" >/dev/null 2>&1 || aws sso login --profile "$CURWORK_ADMIN_PROFILE"
ROLE=$(aws iam list-roles --profile "$CURWORK_ADMIN_PROFILE" --path-prefix /aws-reserved/sso.amazonaws.com/ \
  --query "Roles[?contains(RoleName,'$CURWORK_ROLE')].RoleName | [0]" --output text)
echo "Role: $ROLE"
echo "Managed policies:"; aws iam list-attached-role-policies --profile "$CURWORK_ADMIN_PROFILE" --role-name "$ROLE" \
  --query "AttachedPolicies[].PolicyArn" --output text | tr '\t' '\n' | sed 's/^/  /'
echo "Inline policies:";  aws iam list-role-policies --profile "$CURWORK_ADMIN_PROFILE" --role-name "$ROLE" \
  --query "PolicyNames" --output text | tr '\t' '\n' | sed 's/^/  /'

echo; echo "== 2. What the CurWork role can do ($CURWORK_PROFILE)"
if ! aws configure list-profiles 2>/dev/null | grep -qx $CURWORK_PROFILE; then
  echo "  SKIPPED  The $CURWORK_PROFILE profile isn't on this Mac yet (a reset removes it)."
  echo "           CurWork adds it when it starts. Start CurWork, click Sign in, then run this check again."
else
aws sts get-caller-identity --profile $CURWORK_PROFILE >/dev/null 2>&1 || aws sso login --profile $CURWORK_PROFILE
aws sts get-caller-identity --profile $CURWORK_PROFILE --query Arn --output text
try() { local label="$1"; shift; local out; if out=$("$@" 2>&1); then echo "  PASS  $label"; else echo "  FAIL  $label"; echo "$out" | sed 's/^/          /'; fi; }
try "List files (s3:ListBucket)"  aws s3api list-objects-v2 --profile $CURWORK_PROFILE --region "$REGION" --bucket "$BUCKET" --prefix converted/ --max-items 1
try "Read file details (HeadObject, needs s3:GetObject)" aws s3api head-object --profile $CURWORK_PROFILE --region "$REGION" --bucket "$BUCKET" --key "$KEY"
TMPF="$(mktemp -t curwork-check)"
try "Download file (s3:GetObject + KMS decrypt)" aws s3api get-object --profile $CURWORK_PROFILE --region "$REGION" --bucket "$BUCKET" --key "$KEY" "$TMPF"
rm -f "$TMPF"
fi

echo; echo "== 3. Last 40 lines of today's CurWork log"
LOG="$HOME/CurWork/Logs/curwork-$(date '+%Y-%m-%d').log"
if [ -f "$LOG" ]; then tail -n 40 "$LOG"; else echo "  No log at $LOG"; ls "$HOME/CurWork/Logs" 2>/dev/null | tail -3; fi
echo; echo "== Done."
read -n1 -r -p "Press any key to close."
