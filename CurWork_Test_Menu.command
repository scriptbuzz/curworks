#!/bin/bash
# CurWork Beta 0.015 - DRAFT - For Internal Use (FPT) - Mac test menu - updated 2026-11-23 00:55 UTC - modified by: mbitar
# One place to run every Mac test script, in the order they're meant to run. Under each option it says
# when to use it, exactly what it does, and what it changes. Each script still asks before it changes anything.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
B=$'\033[1m'; D=$'\033[2m'; G=$'\033[1;32m'; R=$'\033[1;31m'; Y=$'\033[1;33m'; N=$'\033[0m'
HL() { printf '\033[1;30;43m %s \033[0m' "$1"; }
WIDTH=$(( $(tput cols 2>/dev/null || echo 80) - 2 )); [ "$WIDTH" -lt 60 ] && WIDTH=60

wrap() {  # wrap <first-line prefix> <next-lines prefix> <text>
  local first="$1" rest="$2" text="$3" w=$(( WIDTH - ${#2} ))
  echo "$text" | fold -s -w "$w" | sed -e "1s/^/$first/" -e "2,\$s/^/$rest/"
}

status() {  # "Last run: 2026-11-22 15:59 UTC - PASS" from a results file
  local f="$HERE/$1"
  [ -f "$f" ] || { echo "${D}Last run: not run yet${N}"; return; }
  local when verdict
  when=$(head -n 3 "$f" | grep -o -m1 '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\} [0-9]\{2\}:[0-9]\{2\} UTC')
  if grep -q -E 'FAIL|STOPPED|[0-9]+ failed|Traceback' "$f"; then verdict="${R}FAIL - see $1${N}"
  elif grep -q -E '== Done|All .* (passed|confirmed gone)' "$f"; then verdict="${G}PASS${N}"
  else verdict="${Y}didn't finish${N}"; fi
  echo "Last run: ${when:-unknown} - $verdict"
}

# item <number> <title> <script> <results file or ""> <when> <changes> <what it does: one step per argument...>
item() {
  local n="$1" title="$2" script="$3" res="$4" when="$5" changes="$6"; shift 6
  printf "\n  ${B}%s. %s${N}   ${D}%s${N}\n" "$n" "$title" "$script"
  wrap "     When:    " "              " "$when"
  echo "     What it does:"
  for step in "$@"; do wrap "       - " "         " "$step"; done
  wrap "     Changes: " "              " "$changes"
  [ -n "$res" ] && echo "     $(status "$res")"
}

run() {
  [ -x "$HERE/$1" ] || { echo "${R}Can't find $1 in this folder.${N}"; sleep 2; return; }
  echo; echo "${B}Running $1 ...${N}"; echo
  bash "$HERE/$1"
  echo; echo "${B}Back to the menu.${N}"; sleep 1
}

SELF="$HERE/$(basename "$0")"; STARTED=$(stat -f %m "$SELF" 2>/dev/null || stat -c %Y "$SELF")
while true; do
  NOW=$(stat -f %m "$SELF" 2>/dev/null || stat -c %Y "$SELF")
  [ "$NOW" != "$STARTED" ] && exec bash "$SELF"      # the menu was updated: reload it so the numbers match
  clear
  BUCKET=$( [ -f test_bucket.txt ] && cut -d' ' -f1 test_bucket.txt || echo "none yet" )
  APP=$( [ -d CurWork-app/CurWork.app ] && echo "built" || echo "not built yet" )
  echo "${B}CurWork - Mac test menu${N}"
  echo "${D}DRAFT - For Internal Use · Beta 0.015 · Mac testing only; never give to billers.${N}"
  echo "Test bucket: $BUCKET"
  echo "CurWork.app: $APP"
  echo "Run them top to bottom. Run 8 before testing by hand. 11 starts over."

  item 1 "Check this Mac" run_mac_checks.command mac_check_results.txt \
    "First, once. Again after updating Python or CurWork's packages." \
    "Creates or refreshes the .venv folder inside CurWork-app. Nothing in AWS." \
    "Checks Python is 3.10 or newer (not Apple's built-in 3.9) and that Tk, the window toolkit, works." \
    "Checks the AWS CLI is installed and lists your AWS profile names (names only)." \
    "Creates .venv and installs CurWork's packages, checking each against its SHA-256 hash." \
    "Runs the automated tests and checks CurWork's window code loads."
  item 2 "Clean up old test items" delete_curwork_test_items.command delete_results.txt \
    "Before creating a new test bucket, if earlier tests (or a crash) left things behind. Skip it if there's nothing to clean." \
    "Deletes only the items you pick, after you type confirm." \
    "Signs in with your admin profile and searches every Region for buckets named curwork-test-* or tagged Purpose=CurWork-test." \
    "Finds the CurWork AWS profile, sign-in session and saved token, config backups, ~/CurWork, the crash log, your CurWork preferences, and the test scripts' helper files." \
    "Lists them in groups with numbers. You pick numbers or all, then type confirm." \
    "Deletes them (every file version for buckets), then re-checks each one and shows PASS or FAIL."
  item 3 "Create the test bucket" setup_test_bucket.command setup_results.txt \
    "After option 1 (and 2, if needed). Stops if a test bucket from an earlier run still exists." \
    "Creates one S3 bucket in the test account, uploads the sample files, rewrites CurWork's admin settings file to use it, and creates or updates the CurWorkBillerTest permission set." \
    "Signs in with your admin profile and checks it's the test account in curwork_test.env. Used only for this setup." \
    "Creates curwork-test-<account>-<date/time> with Block Public Access, Versioning, SSE-KMS encryption, a TLS 1.2+ only policy, a 30-day old-version cleanup and a Purpose=CurWork-test tag." \
    "Uploads the files in sample-data (the agency-b file is the large one, 116 MB)." \
    "Points CurWork at the bucket and runs option 4 to set up its biller test sign-in (CurWorkBillerTest)." \
    "Re-reads AWS and runs 11 PASS/FAIL checks, then option 4's checks."
  item 4 "Set up biller test access" setup_biller_access.command setup_biller_access_results.txt \
    "Once, if the test bucket already exists (option 3 does this for you), or after changing iam/biller_permission_set_policy.json." \
    "Creates or updates one Identity Center permission set (CurWorkBillerTest) and your assignment to it in the test account, and points CurWork's admin settings at it. Nothing in S3." \
    "Signs in with your admin profile and finds IAM Identity Center (needs Identity Center admin rights). You type confirm." \
    "Builds the policy from CurWork's own biller policy, limited to the test account's curwork-test-* buckets and the S3 encryption key." \
    "Creates the permission set (8-hour sessions, tagged Purpose=CurWork-test) or reuses it, and assigns it to you in the test account." \
    "Sets CurWork to sign in with profile curwork-biller, then re-reads AWS and runs 7 PASS/FAIL checks."
  item 5 "Upload the large sample" upload_large_sample.command upload_large_sample_results.txt \
    "When the test bucket already exists and you want the large file in it. Not needed right after option 3, which uploads it." \
    "Replaces one file in the test bucket. The small file stays as an older version for 30 days." \
    "Checks the large file is there (3.2 million made-up rows over 4 sheets, 116 MB) and the test bucket exists." \
    "Signs in with your admin profile and checks the account. You type confirm." \
    "Uploads it to converted/agency-b/2026-10/ with a SHA-256 checksum and the bucket's SSE-KMS encryption." \
    "Re-reads S3 and checks the size and encryption (PASS/FAIL)."
  item 6 "Check why something is refused" diagnose_download.command diagnose_results.txt \
    "When CurWork says AWS refused something, like the download error." \
    "Nothing. Read-only." \
    "With your admin profile: lists the policies on the CurWorkBillerTest role CurWork uses." \
    "With curwork-biller: tries to list files, read one file's details, and download it, and shows AWS's exact reason for any refusal." \
    "Copies the last 40 lines of today's CurWork log into diagnose_results.txt."
  item 7 "Build and open CurWork.app" build_mac_app.command build_mac_app_results.txt \
    "To run CurWork as a real Mac app. Rebuild after any change to CurWork's code. Use 7 or 9, not both at once." \
    "Creates or replaces CurWork-app/CurWork.app. Nothing in AWS." \
    "Builds CurWork.app with PyInstaller from CurWork's .venv, with its own name, version and icon." \
    "Runs the new app's self-test and opens it only if every check passes." \
    "Signs it for this Mac only (ad-hoc) and checks the signature." \
    "Puts it next to curwork_admin_settings.json, which it reads from there, and opens it."
  item 8 "Run all automated tests" run_automated_tests.command automated_tests_results.txt \
    "Before you test anything by hand, and after every change. If anything fails, send the results file for review first." \
    "Uploads two small test files to the test bucket and removes them afterwards (you type confirm). Nothing else." \
    "Script checks: every .command file and tool parses and can run." \
    "Code tests: CurWork's unit and window tests with a mocked S3, including the biller policy (windows flash up briefly)." \
    "Real AWS tests: CurWork's own code with its real sign-in: role check, browse, download (small and 116 MB), upload, things billers must not be able to do, log upload, then removes its test files." \
    "CurWork.app: built from the current code, signature valid, and its self-test passes." \
    "CurWork from source: the same self-test."
  item 9 "Start CurWork from source" start_curwork.command "" \
    "For a quick run after a code change, without building. The Dock shows it as Python." \
    "Nothing by itself. CurWork may add the curwork-biller profile to ~/.aws/config at first Sign in." \
    "Starts curwork.py with CurWork's .venv and saves its output to curwork_run_output.txt."
  item 10 "Clean up when finished" delete_curwork_test_items.command delete_results.txt \
    "When you're done testing, so nothing is left in AWS or on this Mac." \
    "Deletes only the items you pick, after you type confirm." \
    "Same as option 2: finds every test item (including the CurWorkBillerTest permission set), you pick numbers or all, type confirm, and each delete is re-checked."

  item 11 "Reset everything" reset_everything.command reset_results.txt \
    "When you want a clean start: after a crash, a messy test, or before showing the tool to someone." \
    "Deletes every test item in AWS and on this Mac, then creates a new test bucket. Keeps CurWork-app (program, .venv, CurWork.app), the scripts and sample-data." \
    "Part 1: finds every CurWork test item (like option 2), picks all of them, and deletes them after you type confirm. Each delete is re-checked." \
    "Stops there if you cancel or anything isn't confirmed deleted." \
    "Part 2: creates a fresh test bucket and uploads all samples, including the large one (like option 3), and sets up biller test access again (like option 4), after you type confirm. Ends with all the checks."

  echo
  printf "Type a number (1-11), or %s to close the menu: " "$(HL q)"
  read -r choice
  case "$choice" in
    1) run run_mac_checks.command ;;
    2|10) run delete_curwork_test_items.command ;;
    3) run setup_test_bucket.command ;;
    4) run setup_biller_access.command ;;
    5) run upload_large_sample.command ;;
    6) run diagnose_download.command ;;
    7) run build_mac_app.command ;;
    8) run run_automated_tests.command ;;
    9) run start_curwork.command ;;
    11) run reset_everything.command ;;
    q|Q) echo "Bye."; exit 0 ;;
    *) echo "${Y}Type a number from 1 to 11, or q.${N}"; sleep 1.5 ;;
  esac
done
