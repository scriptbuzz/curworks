#!/bin/bash
# CurWork Beta 0.014 - DRAFT - For Internal Use (FPT) - Mac launcher - updated 2026-11-23 00:16 UTC - modified by: mbitar
cd "$(dirname "$0")/CurWork-app" || exit 1
source .venv/bin/activate && python curwork.py 2>&1 | tee ../curwork_run_output.txt
