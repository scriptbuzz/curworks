#!/bin/bash
# CurWork Beta 0.011 - DRAFT - For Internal Use (FPT) - Mac launcher - updated 2026-11-22 14:58 UTC - modified by: mbitar
cd "$(dirname "$0")/CurWork-Beta-0.011" || exit 1
source .venv/bin/activate && python curwork.py 2>&1 | tee ../curwork_run_output.txt
