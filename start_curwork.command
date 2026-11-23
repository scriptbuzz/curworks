#!/bin/bash
# CurWork Beta 0.013 - DRAFT - For Internal Use (FPT) - Mac launcher - updated 2026-11-22 23:56 UTC - modified by: mbitar
cd "$(dirname "$0")/CurWork-app" || exit 1
source .venv/bin/activate && python curwork.py 2>&1 | tee ../curwork_run_output.txt
