#!/bin/bash
# CurWork Beta 0.013 - DRAFT - For Internal Use (FPT) - reset everything - updated 2026-11-22 23:56 UTC - modified by: mbitar
# Puts the Mac test back to a clean, ready-to-test state in one go:
#   Part 1: deletes EVERY CurWork test item (same search as the cleanup script, all items picked).
#   Part 2: creates a fresh test bucket with all sample files, including the large one, and biller test access.
# You type confirm once for each part. If Part 1 is cancelled or anything fails, Part 2 doesn't run.
# Kept: the CurWork-app folder (program, .venv, CurWork.app), the scripts, and sample-data.
# Results are saved to reset_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE" || exit 1
exec > >(tee "$HERE/reset_results.txt") 2>&1
HL() { printf '\033[1;30;43m %s \033[0m' "$1"; }
B=$'\033[1m'; G=$'\033[1;32m'; R=$'\033[1;31m'; N=$'\033[0m'
finish() { echo; echo "$1"; read -n1 -r -p "Press any key to close."; exit "$2"; }
echo "== CurWork reset everything - $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "Part 1 deletes every CurWork test item in AWS and on this Mac."
echo "Part 2 creates a fresh test bucket, uploads all sample files (about 116 MB) and sets up biller test access."
echo "Kept: CurWork-app (program, .venv, CurWork.app), the scripts, and sample-data."
echo "You'll type $(HL confirm) once for each part."
export CURWORK_RESET=1

echo; echo "${B}== Part 1 of 2: delete every test item${N}"
bash "$HERE/delete_curwork_test_items.command"; RC=$?
[ $RC -eq 3 ] && finish "STOPPED: Part 1 was cancelled. Nothing was deleted, and no new bucket was created." 3
[ $RC -ne 0 ] && finish "${R}STOPPED: some items were NOT confirmed deleted (FAIL lines above). No new bucket was created.${N}" 1

echo; echo "${B}== Part 2 of 2: create a fresh test bucket${N}"
bash "$HERE/setup_test_bucket.command"; RC=$?
[ $RC -ne 0 ] && finish "${R}STOPPED: Part 2 didn't finish (see above). Everything from Part 1 is deleted; run 'Create the test bucket' to try again.${N}" 1

finish "${G}== Done. Everything was reset and a fresh test bucket is ready ($(cut -d' ' -f1 test_bucket.txt)).${N}" 0
