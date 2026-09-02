#!/usr/bin/env bash
# E2E rapido: tool msf real vs lab vsftpd (variables ya fijadas para el lab)
set -euo pipefail
cd "$(dirname "$0")/.."
export PENTEST_ENGAGEMENT_FILE="$PWD/engagement.yaml"
export PENTEST_EXPLOIT_APPROVED=ENG-LAB-2026-001
export MSF_BACKEND=real
export MSFRPCD_PASSWORD=whlab-test-pass
export MSFRPCD_USER=msfapi
export MSFRPCD_SSL=1
.venv/bin/python scripts/msf_fire_test.py
