#!/usr/bin/env bash
# Levanta los 3 subagentes A2A (recon 9101, vuln 9102, reporter 9103) en background.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
mkdir -p .cache
PIDS=()
for spec in "recon 9101" "vuln 9102" "reporter 9103"; do
  set -- $spec
  role=$1; port=$2
  nohup python -m pentest_agent.a2a_server --role "$role" --port "$port" \
    > ".cache/a2a-$role.log" 2>&1 &
  PIDS+=($!)
done
echo "pids: ${PIDS[@]}"
sleep 6
for port in 9101 9102 9103; do
  echo "--- card :$port ---"
  curl -s --max-time 5 "http://127.0.0.1:$port/.well-known/agent.json" | head -c 200; echo
done
