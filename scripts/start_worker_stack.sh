#!/usr/bin/env bash
# Levanta el stack A2A completo para auditar el worker K8s (192.168.17.53):
# recon/vuln/reporter (defensivos) + exploit (ofensivo, con SU engagement).
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
mkdir -p .cache

# servidores previos fuera (patron [.] para no auto-matchear este script)
pkill -f "pentest_agent[.]a2a_server" 2>/dev/null || true
sleep 1

# defensivos: recon necesita el scope del worker en SU proceso
export PENTEST_SCOPE_FILE="$PWD/scope.worker.yaml"
for spec in "recon 9101" "vuln 9102" "reporter 9103"; do
  set -- $spec
  nohup python -m pentest_agent.a2a_server --role "$1" --port "$2" \
    > ".cache/a2a-$1.log" 2>&1 &
  echo "$1 -> $!"
done

# ofensivo: SU proceso lleva engagement + aprobacion humana + msf real
PENTEST_ENGAGEMENT_FILE="$PWD/engagement-k8s-worker.yaml" \
PENTEST_EXPLOIT_APPROVED=ENG-K8SWORKER-2026-001 \
MSF_BACKEND=real \
MSFRPCD_PASSWORD=whlab-test-pass \
MSFRPCD_USER=msfapi \
MSFRPCD_SSL=1 \
  nohup python -m pentest_agent.a2a_server --role exploit --port 9104 \
    > .cache/a2a-exploit.log 2>&1 &
echo "exploit -> $!"

sleep 6
for port in 9101 9102 9103 9104; do
  echo "--- card :$port ---"
  curl -s --max-time 5 "http://127.0.0.1:$port/.well-known/agent.json" | head -c 160; echo
done
