#!/usr/bin/env bash
set -euo pipefail

# Legacy compatibility entrypoint for MacroPulser.
# Preferred split entrypoint:
#   scripts/macro_pulser/run-replay.ps1
python -m app.main replay --release-id "${1}"
