#!/usr/bin/env python3
"""Muestra el output_tail de los ultimos N registros del ledger."""
import json
import sys

n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
lines = open("reports/evidence.jsonl").read().strip().splitlines()
for line in lines[-n:]:
    rec = json.loads(line)
    msf = rec.get("msf") or {}
    print("=" * 30, rec["ts"], "proven:", rec.get("proven"))
    print((msf.get("output_tail") or "(sin output)")[-1400:])
