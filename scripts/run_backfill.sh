#!/usr/bin/env bash
set -euo pipefail

# Legacy compatibility entrypoint for MacroPulser.
# Preferred split entrypoint:
#   scripts/macro_pulser/run-backfill.ps1
python -m app.main backfill --from "${1}" --to "${2}"
