#!/bin/bash
# CurWork Beta 0.011 - DRAFT - For Internal Use (FPT) - automated tests - updated 2026-11-22 18:05 UTC - modified by: mbitar
# Runs every automated check before you test by hand, and saves one PASS/FAIL report:
#   1. Script checks: every .command file parses and can run.
#   2. Code tests: CurWork's unit tests, then each window test in its own process (windows flash up briefly;
#      mocked S3). Full output goes to code_tests_output.txt.
#   3. Real AWS tests: CurWork's own code against the test bucket with CurWork's sign-in. Uploads two small
#      test files, checks what must be refused is refused, then removes the test files (admin profile) and checks.
#   4. CurWork.app: built from the current code, signature valid, and its self-test passes
#      (settings next to the app, icon, About, Settings, and the signed-in role).
#   5. CurWork from source: the same self-test.
# Results are saved to automated_tests_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
exec > >(tee "$HERE/automated_tests_results.txt") 2>&1
export AWS_PAGER="" PYTHONUNBUFFERED=1
. "$HERE/tools/test_env.sh" || { read -n1 -r -p "Press any key to close."; exit 1; }
B=$'\033[1m'; G=$'\033[1;32m'; R=$'\033[1;31m'; Y=$'\033[1;33m'; N=$'\033[0m'
TOOL="$HERE/CurWork-Beta-0.011"; PY="$TOOL/.venv/bin/python"; APP="$TOOL/CurWork.app"
FAILS=0; PARTS=()
pass() { echo "  ${G}PASS${N}  $1"; }
fail() { echo "  ${R}FAIL${N}  $1"; FAILS=$((FAILS + 1)); }
part() { PARTS+=("$1: $2"); }
limit() { perl -e 'alarm shift; exec @ARGV' "$@"; }     # run with a time limit (macOS has no timeout command)
selftest_report() {   # print the self-test JSON as PASS/FAIL lines; exit code = passed or not
  "$PY" -c 'import json,sys
t=sys.stdin.read(); i=t.find("{")
if i<0: print("  \033[1;31mFAIL\033[0m  no self-test report:", t.strip()[-300:]); sys.exit(1)
r=json.loads(t[i:])
for c in r["checks"]:
    print(("  \033[1;33mSKIP\033[0m  " if c.get("skipped") else "  \033[1;32mPASS\033[0m  " if c["ok"] else "  \033[1;31mFAIL\033[0m  ")+c["check"]+(("\n          "+c["detail"]) if c["detail"] else ""))
sys.exit(0 if r["passed"] else 1)'
}

echo "== CurWork automated tests - $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "Runs script checks, code tests, real AWS tests, and CurWork's self-test (built app and source)."
echo "The real AWS tests upload two small test files to the test bucket and remove them afterwards."
read -r -p "$(printf 'Type \033[1;30;43m confirm \033[0m to go ahead (anything else cancels): ')" CONFIRM
[ "$CONFIRM" = "confirm" ] || { echo "You didn't type confirm. Nothing was run."; read -n1 -r -p "Press any key to close."; exit 3; }
[ -x "$PY" ] || { echo "STOPPED: CurWork's .venv isn't set up. Run menu option 1 first."; read -n1 -r -p "Press any key to close."; exit 1; }

echo; echo "${B}== 1 of 5. Script checks${N}"
before=$FAILS
for f in *.command; do
  if bash -n "$f" 2>/tmp/curwork-syntax.txt; then
    [ -x "$f" ] && pass "$f" || fail "$f can't be double-clicked (not executable). Fix: chmod +x \"$f\""
  else fail "$f has a syntax error: $(head -1 /tmp/curwork-syntax.txt)"; fi
done
for f in tools/*.py; do "$PY" -m py_compile "$f" 2>/dev/null && pass "$f" || fail "$f has a Python error"; done
if [ -d .git ]; then
  bash tools/check_no_aws_details.sh --worktree | sed 's/^/  /' ; [ "${PIPESTATUS[0]}" = "0" ] || fail "AWS details found in files Git would add (see BLOCKED lines)"
  [ "$(git config --get core.hooksPath)" = ".githooks" ] && pass "Git commit and push checks are turned on" || fail "Git checks are off. Fix: git config core.hooksPath .githooks"
fi
[ $FAILS -eq $before ] && part "1 (script checks)" PASS || part "1 (script checks)" FAIL

echo; echo "${B}== 2 of 5. Code tests (unit and window tests, mocked S3)${N}"
echo "   Full output: code_tests_output.txt. Each window test runs in its own process, so one crash can't hide the rest."
before=$FAILS; OUT="$HERE/code_tests_output.txt"; ONE="$(mktemp "${TMPDIR:-/tmp}/curwork-test.XXXXXX")"
: > "$OUT"
(cd "$TOOL" && limit 600 "$PY" -m pytest -q -p no:cacheprovider tests/test_core.py > "$ONE" 2>&1); rc=$?
cat "$ONE" >> "$OUT"
[ $rc -eq 0 ] && pass "Unit tests: $(tail -1 "$ONE")" || { fail "Unit tests (exit $rc)"; tail -20 "$ONE" | sed 's/^/          /'; }
TESTS=$(cd "$TOOL" && "$PY" -m pytest --collect-only -q -p no:cacheprovider tests/test_gui.py 2>/dev/null | grep '::')
[ -n "$TESTS" ] || fail "Couldn't list the window tests (see code_tests_output.txt)"
for t in $TESTS; do
  (cd "$TOOL" && limit 240 "$PY" -m pytest -q -p no:cacheprovider "$t" > "$ONE" 2>&1); rc=$?
  { echo; echo "===== $t (exit $rc)"; cat "$ONE"; } >> "$OUT"
  name="window test: ${t##*::}"
  if [ $rc -eq 0 ]; then pass "$name"
  elif [ $rc -ge 128 ]; then fail "$name CRASHED Python (signal $((rc - 128)))"; grep -A12 -m1 "Fatal Python error" "$ONE" | sed 's/^/          /'
  else fail "$name"; grep -E "^E |Error|assert" "$ONE" | head -12 | sed 's/^/          /'; fi
done
rm -f "$ONE"
[ $FAILS -eq $before ] && part "2 (code tests)" PASS || part "2 (code tests)" FAIL

echo; echo "${B}== 3 of 5. Real AWS tests${N}"
if limit 1200 "$PY" tools/real_aws_tests.py; then part "3 (real AWS)" PASS; else FAILS=$((FAILS + 1)); part "3 (real AWS)" FAIL; fi

echo; echo "${B}== 4 of 5. CurWork.app${N}"
before=$FAILS
if [ ! -d "$APP" ]; then
  fail "CurWork.app isn't built yet. Run menu option 7."
else
  newer=$(find "$TOOL/curwork.py" "$TOOL/curwork_core.py" "$TOOL/curwork_help.py" "$TOOL/assets" "$TOOL/curwork_admin_settings.json" -newer "$APP/Contents/MacOS/CurWork" -not -name curwork_admin_settings.json 2>/dev/null | sed "s|$TOOL/||" | tr '\n' ' ')
  [ -z "$newer" ] && pass "Built from the current code" || fail "Out of date: changed since the build: $newer. Rebuild with menu option 7."
  codesign --verify --deep --strict "$APP" 2>/dev/null && pass "Signature is valid" || fail "Signature check failed. Rebuild with menu option 7."
  limit 90 "$APP/Contents/MacOS/CurWork" --self-test 2>/dev/null | selftest_report || FAILS=$((FAILS + 1))
fi
[ $FAILS -eq $before ] && part "4 (CurWork.app)" PASS || part "4 (CurWork.app)" FAIL

echo; echo "${B}== 5 of 5. CurWork from source${N}"
before=$FAILS
(cd "$TOOL" && limit 90 "$PY" curwork.py --self-test 2>/dev/null) | selftest_report || FAILS=$((FAILS + 1))
[ $FAILS -eq $before ] && part "5 (from source)" PASS || part "5 (from source)" FAIL

echo; echo "${B}== Summary${N}"
for p in "${PARTS[@]}"; do case "$p" in *PASS) echo "  ${G}PASS${N}  Part $p" | sed 's/: PASS$//';; *) echo "  ${R}FAIL${N}  Part $p" | sed 's/: FAIL$//';; esac; done
if [ $FAILS -eq 0 ]; then echo; echo "${G}== Done. All automated tests passed. CurWork is ready for you to test by hand.${N}"
else echo; echo "${R}STOPPED: $FAILS problem(s) found (FAIL lines above). Send automated_tests_results.txt for review before testing by hand.${N}"; fi
read -n1 -r -p "Press any key to close."
[ $FAILS -eq 0 ]
