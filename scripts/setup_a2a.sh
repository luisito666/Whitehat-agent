#!/usr/bin/env bash
# Instala dependencias A2A en el venv del PoC (tarea acotada, no es un server)
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
uv pip install -q a2a-sdk uvicorn
python - <<'PYEOF'
import a2a
print("a2a import OK")
PYEOF
