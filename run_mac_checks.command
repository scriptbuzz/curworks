#!/bin/bash
# CurWork Beta 0.014 - DRAFT - For Internal Use (FPT) - Mac check script - updated 2026-11-23 00:16 UTC - modified by: mbitar
# Double-click to run. It checks Python, Tk and the AWS CLI, sets up CurWork's Python environment,
# runs the automated tests, and saves everything to mac_check_results.txt next to this file.
# It reads no passwords and changes nothing outside the CurWork-app folder.

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/CurWork-app" || { echo "CurWork-app folder not found next to this script."; read -n1 -r -p "Press any key to close."; exit 1; }
OUT="$HERE/mac_check_results.txt"
exec > >(tee "$OUT") 2>&1

echo "== CurWork Mac check - $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "macOS $(sw_vers -productVersion) on $(uname -m)"

echo; echo "== Python (3.10 or newer, not Apple's built-in 3.9)"
PY=""
for c in python3.12 python3.13 python3.11 python3; do
  p="$(command -v "$c" 2>/dev/null)" || continue
  if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then echo "RESULT: no suitable Python found. Install Python 3.12 from python.org."; else echo "Using $PY ($("$PY" --version 2>&1))"; fi

echo; echo "== Tk (the window toolkit)"
if [ -n "$PY" ]; then "$PY" -c "import tkinter as tk; r = tk.Tk(); r.withdraw(); print('Tk', r.tk.call('info', 'patchlevel'), 'works'); r.destroy()" || echo "RESULT: Tk is missing or broken for this Python."; fi

echo; echo "== AWS CLI"
if command -v aws >/dev/null 2>&1; then
  echo "Found $(command -v aws)"; aws --version
  echo "AWS profile names on this Mac (names only):"; aws configure list-profiles 2>/dev/null | sed 's/^/  /' || true
else
  echo "RESULT: aws not found on PATH. Install AWS CLI v2 for macOS."
fi

if [ -n "$PY" ]; then
  echo; echo "== Python environment (.venv in CurWork-app)"
  "$PY" -m venv .venv && source .venv/bin/activate || { echo "RESULT: couldn't create .venv"; }
  python -m pip install -q --upgrade pip
  python -m pip install -q --require-hashes -r requirements-lock.txt && echo "Runtime packages installed (hash-checked)." || echo "RESULT: runtime package install failed."
  python -m pip install -q -r requirements-dev.txt && echo "Test tools installed." || echo "RESULT: test tool install failed."

  echo; echo "== Automated tests"
  python -m pytest -q -p no:cacheprovider 2>&1 | tail -15

  echo; echo "== Can CurWork's window code load?"
  python -c "import curwork, curwork_core as c; print('Loaded CurWork', c.RELEASE_LABEL, '|', c.STATUS, '| tool folder:', c.tool_folder())"
fi

echo; echo "== Done. Results saved to $OUT"
read -n1 -r -p "Press any key to close this window."
