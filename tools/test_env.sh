# CurWork Beta 0.014 - DRAFT - For Internal Use (FPT) - test settings loader - updated 2026-11-23 00:16 UTC - modified by: mbitar
# Sourced by the test scripts. Loads your AWS details from curwork_test.env (kept out of Git) so no account
# number, profile name or sign-in URL is written into any script.
_here="${HERE:-$(pwd)}"
_env="$_here/curwork_test.env"
if [ ! -f "$_env" ]; then
  echo "STOPPED: $_env is missing. Copy curwork_test.env.example to curwork_test.env and fill in your AWS details."
  return 1 2>/dev/null || exit 1
fi
if git -C "$_here" ls-files --error-unmatch curwork_test.env >/dev/null 2>&1; then
  echo "STOPPED: curwork_test.env is tracked by Git. Run: git rm --cached curwork_test.env   (it must stay private)"
  return 1 2>/dev/null || exit 1
fi
set -a; . "$_env"; set +a
: "${CURWORK_SSO_REGION:=us-east-1}" "${CURWORK_SSO_SESSION:=curwork-test}" "${CURWORK_PROFILE:=curwork-biller}" "${CURWORK_ROLE:=CurWorkBillerTest}"
export CURWORK_SSO_REGION CURWORK_SSO_SESSION CURWORK_PROFILE CURWORK_ROLE
for _v in CURWORK_ACCOUNT CURWORK_ADMIN_PROFILE CURWORK_SSO_START_URL; do
  eval "_val=\${$_v:-}"
  case "$_val" in ""|000000000000|your-admin-profile|https://your-org.awsapps.com/start)
    echo "STOPPED: set $_v in curwork_test.env (it still has the example value)."; return 1 2>/dev/null || exit 1;;
  esac
done
case "$CURWORK_ACCOUNT" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "STOPPED: CURWORK_ACCOUNT in curwork_test.env must be 12 digits."; return 1 2>/dev/null || exit 1;; esac
unset _here _env _v _val
