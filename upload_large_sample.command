#!/bin/bash
# CurWork Beta 0.014 - DRAFT - For Internal Use (FPT) - large sample upload - updated 2026-11-23 00:16 UTC - modified by: mbitar
# Uploads the large made-up workbook (sample-data/agency-b-cur-2026-10.xlsx: 3.2 million rows over 4 sheets)
# to the current test bucket, replacing the small agency-b file there. Uses the admin profile (CURWORK_ADMIN_PROFILE)
# because CurWork's read-only role can't upload. The old small file stays as an older version (Versioning),
# which the bucket's lifecycle rule removes after 30 days.
# Results are saved to upload_large_sample_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
exec > >(tee "$HERE/upload_large_sample_results.txt") 2>&1
export AWS_PAGER=""
. "$HERE/tools/test_env.sh" || { read -n1 -r -p "Press any key to close."; exit 1; }
PROFILE="$CURWORK_ADMIN_PROFILE"; ACCOUNT="$CURWORK_ACCOUNT"
FILE="sample-data/agency-b-cur-2026-10.xlsx"; KEY="converted/agency-b/2026-10/agency-b-cur-2026-10.xlsx"
stop() { echo "  FAIL  $1"; echo "STOPPED. Nothing was uploaded."; read -n1 -r -p "Press any key to close."; exit 1; }
echo "== CurWork large sample upload - $(date -u '+%Y-%m-%d %H:%M UTC')"

[ -f test_bucket.txt ] || stop "No test bucket yet. Run 'Create the test bucket' first."
read -r BUCKET REGION < test_bucket.txt
[ -f "$FILE" ] || stop "$FILE is missing. Make it with: python3 tools/make_large_sample.py $FILE (needs xlsxwriter)."
SIZE=$(stat -f %z "$FILE" 2>/dev/null || stat -c %s "$FILE")
[ "$SIZE" -gt 50000000 ] || stop "$FILE is only $SIZE bytes, so it isn't the large sample. Make it with tools/make_large_sample.py."

aws sts get-caller-identity --profile "$PROFILE" >/dev/null 2>&1 || aws sso login --profile "$PROFILE" || stop "Sign-in to $PROFILE"
ACC=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
[ "$ACC" = "$ACCOUNT" ] || stop "Signed in to account $ACC, not the test account $ACCOUNT."
aws s3api head-bucket --bucket "$BUCKET" --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1 || stop "Bucket $BUCKET isn't there. Run 'Create the test bucket' first."

echo
echo "This will upload $FILE ($((SIZE / 1048576)) MB, 3.2 million made-up rows over 4 sheets)"
echo "to s3://$BUCKET/$KEY"
echo "It replaces the small agency-b file there (kept as an older version for 30 days)."
read -r -p "$(printf 'Type \033[1;30;43m confirm \033[0m to go ahead (anything else cancels): ')" CONFIRM
[ "$CONFIRM" = "confirm" ] || { echo "You didn't type confirm. Nothing was uploaded."; read -n1 -r -p "Press any key to close."; exit 1; }

echo; echo "== Upload (multipart, SHA-256 checksum, bucket's default SSE-KMS encryption)"
aws s3 cp "$FILE" "s3://$BUCKET/$KEY" --profile "$PROFILE" --region "$REGION" --checksum-algorithm SHA256 --only-show-errors \
  || stop "Upload"

echo; echo "== Check it in S3 (re-reads AWS)"
read -r GOT ENC < <(aws s3api head-object --bucket "$BUCKET" --key "$KEY" --profile "$PROFILE" --region "$REGION" \
  --query '[ContentLength, ServerSideEncryption]' --output text)
OK=0
[ "$GOT" = "$SIZE" ] && echo "  PASS  Size in S3 matches ($GOT of $SIZE bytes)" || { echo "  FAIL  Size in S3 is $GOT, expected $SIZE"; OK=1; }
[ "$ENC" = "aws:kms" ] && echo "  PASS  Encrypted with SSE-KMS" || { echo "  FAIL  Encryption is $ENC, expected aws:kms"; OK=1; }
echo
[ $OK -eq 0 ] && echo "== Done. The large file is in the test bucket. In CurWork, download agency-b/2026-10 to test it." \
              || echo "STOPPED with failures. See FAIL lines above."
read -n1 -r -p "Press any key to close."
