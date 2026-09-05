#!/usr/bin/env bash
# Arranque de laboratorio ofensivo COMPLETO en un solo comando (fail-closed intacto).
#
# Qué hace, en orden:
#   1. Valida engagement.yaml (fail-closed: si falta/expira, aborta)
#   2. Te muestra el resumen y pide tu 'y' (aprobación humana, NO elidable)
#   3. Levanta labs: web vulnerable (path-traversal) + vsftpd 2.3.4 (backdoor)
#   4. Levanta stack A2A: recon 9101, vuln 9102, reporter 9103
#   5. Levanta exploit 9104 CON la aprobación en SU proceso (triple llave)
#   6. Corre la auditoría E2E con handoff ofensivo habilitado (A2A_EXPLOIT_URL)
#   7. Muestra el ledger de evidencia y limpia todo al salir
#
# Uso:  bash scripts/run_lab_full.sh          (o .venv/bin/python ... no: es bash)
# Detener todo: Ctrl-C (trap) o `pkill -f pentest_agent`
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
mkdir -p .cache

PY=.venv/bin/python

# ---------------------------------------------------------------- 1) engagement
ENG_SUMMARY=$($PY - <<'EOF'
from pentest_agent.engagement import EngagementError, load_engagement
try:
    eng = load_engagement()
    eng.assert_valid()
    print(f"OK|{eng.id}|{eng.client.get('name')}|{eng.auth_reference}|{eng.valid_from}..{eng.valid_until}")
    print("|".join(sorted(eng.prohibited)))
except EngagementError as e:
    print(f"FAIL|{e}")
    raise SystemExit(1)
EOF
) || { echo "ABORTADO: engagement inválido (fail-closed)."; exit 1; }

ENG_ID=$(echo "$ENG_SUMMARY" | head -1 | cut -d'|' -f2)
echo "=== Engagement vigente: $ENG_ID ==="
echo "$ENG_SUMMARY" | head -1 | cut -d'|' -f3- | tr '|' '\n' | sed 's/^/  /'
echo "  Prohibidas: $(echo "$ENG_SUMMARY" | sed -n 2p | tr '\n' ' ')"
echo
echo "Al aprobar certificas autorización escrita para las técnicas del"
echo "engagement, dentro de la ventana de vigencia (igual que approve.py)."
read -r -p "¿Aprobar explotación en lab? [y/N] " ans
[[ "${ans,,}" == "y" ]] || { echo "No aprobado. Abortando (fail-closed)."; exit 1; }

# ---------------------------------------------------------------- 2) labs
PIDS=()
cleanup() {
  echo
  echo "=== limpiando (${PIDS[*]:-none}) ==="
  kill "${PIDS[@]}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# labs con -u: log sin buffering (el script extrae el puerto efímero del log)
$PY -u -m pentest_agent.lab > .cache/lab-web.log 2>&1 & PIDS+=($!)
$PY -u -m pentest_agent.lab_vsftpd > .cache/lab-vsftpd.log 2>&1 & PIDS+=($!)

# lab web usa puerto efímero: extraerlo del log (reintento hasta 10s)
LAB_WEB_PORT=""
for _ in $(seq 1 20); do
  LAB_WEB_PORT=$(grep -oE '127\.0\.0\.1:[0-9]+' .cache/lab-web.log 2>/dev/null | head -1 | cut -d: -f2 || true)
  [[ -n "$LAB_WEB_PORT" ]] && break
  sleep 0.5
done
[[ -n "$LAB_WEB_PORT" ]] || { echo "ERROR: lab web no arrancó"; cat .cache/lab-web.log; exit 1; }
echo "labs: web 127.0.0.1:$LAB_WEB_PORT  |  vsftpd 127.0.0.1:2121 (shell :6200)"

# ---------------------------------------------------------------- 3) stack A2A
for spec in "recon 9101" "vuln 9102" "reporter 9103"; do
  set -- $spec
  nohup $PY -m pentest_agent.a2a_server --role "$1" --port "$2" \
    > ".cache/a2a-$1.log" 2>&1 & PIDS+=($!)
done

# exploit server: la aprobación vive SOLO en este proceso (llave 2)
PENTEST_EXPLOIT_APPROVED="$ENG_ID" \
  nohup $PY -m pentest_agent.a2a_server --role exploit --port 9104 \
    > .cache/a2a-exploit.log 2>&1 & PIDS+=($!)

for port in 9101 9102 9103 9104; do
  ok=""
  for _ in $(seq 1 20); do
    curl -sf --max-time 2 "http://127.0.0.1:$port/.well-known/agent.json" > /dev/null && ok=1 && break
    sleep 0.5
  done
  [[ -n "$ok" ]] || { echo "ERROR: worker :$port no levantó (ver .cache/a2a-*.log)"; exit 1; }
  echo "worker :$port OK"
done

# ---------------------------------------------------------------- 4) auditoría E2E
echo
echo "=== Auditoría E2E (supervisor + 4 agentes, handoff ofensivo) ==="
export A2A_EXPLOIT_URL="http://127.0.0.1:9104"
$PY - <<EOF
from pentest_agent.a2a_team import run_audit
result = run_audit("127.0.0.1", ports="22,${LAB_WEB_PORT},2121,6200,9101,9102,9103,9104", recursion_limit=60)
msgs = result["messages"]
print(f"=== mensajes del grafo: {len(msgs)} ===")
for m in msgs:
    name = getattr(m, "name", "") or m.__class__.__name__
    content = m.content if isinstance(m.content, str) else str(m.content)
    print(f"--- [{name}] {content[:220]}")
EOF

# ---------------------------------------------------------------- 5) evidencia
echo
echo "=== Ledger de evidencia (últimas 3 acciones) ==="
tail -3 reports/evidence.jsonl 2>/dev/null || echo "(sin ledger)"
echo
echo "Logs en .cache/  |  Todo el stack se apaga al salir."
