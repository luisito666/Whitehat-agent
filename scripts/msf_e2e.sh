#!/usr/bin/env bash
# E2E Metasploit real vs lab vsftpd (todo loopback, userspace).
# Uso: bash scripts/msf_e2e.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

MSF_HOME="$HOME/tools/metasploit-framework"
export RBENV_ROOT="$HOME/.rbenv"
export PATH="$RBENV_ROOT/bin:$RBENV_ROOT/shims:$PATH"
# headers/libs de desarrollo extraidos sin root (gemas nativas: sqlite3, pcap, yaml)
export CPATH="$HOME/tools/devpkgs/root/usr/include"
export LIBRARY_PATH="$HOME/tools/devpkgs/root/usr/lib/x86_64-linux-gnu"

# 1) lab vulnerable
python -m pentest_agent.lab_vsftpd &
LAB_PID=$!
trap 'kill $LAB_PID $RPC_PID 2>/dev/null || true' EXIT
sleep 1

# 2) msfrpcd (necesita bundle instalado; fallara con mensaje claro si falta).
#    Sin -S => SSL activo, consistente con el default MSFRPCD_SSL=1 de la tool.
#    Usuario default 'msf' (no -U), consistente con el default de la tool.
pkill -f msfrpcd 2>/dev/null || true   # daemon previo en 55553 (lab loopback)
export MSFRPCD_PASSWORD="${MSFRPCD_PASSWORD:-whlab-test-pass}"
export MSFRPCD_SSL=1
cd "$MSF_HOME"
bundle exec ruby msfrpcd -P "$MSFRPCD_PASSWORD" -p 55553 -a 127.0.0.1 &
RPC_PID=$!
cd - >/dev/null
sleep 8

# 3) engagement + aprobacion + disparo
cp -n engagement.example.yaml engagement.yaml
export PENTEST_ENGAGEMENT_FILE="$PWD/engagement.yaml"
export PENTEST_EXPLOIT_APPROVED=ENG-LAB-2026-001
export MSF_BACKEND=real
python scripts/msf_fire_test.py
