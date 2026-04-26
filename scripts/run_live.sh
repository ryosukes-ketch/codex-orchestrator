#!/usr/bin/env bash
set -euo pipefail

# Legacy compatibility entrypoint for MacroPulser.
# Preferred split entrypoint:
#   scripts/macro_pulser/run-live.ps1
python -m app.main live
