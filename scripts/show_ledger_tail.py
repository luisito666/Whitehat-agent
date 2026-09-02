#!/usr/bin/env python3
"""Muestra el output_tail del ultimo registro del ledger (sin pipes raros)."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "reports/evidence.jsonl"
lines = open(path).read().strip().splitlines()
rec = json.loads(lines[-1])
print(rec["msf"]["output_tail"][-2200:])
