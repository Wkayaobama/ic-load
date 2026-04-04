#!/usr/bin/env bash
set -euo pipefail

echo "Running ic-load remote smoke path..."

# The probe is the guaranteed remote-safe path: it exercises orchestration,
# rendered SQL generation, and run artifact handling without live writes.
python -m pipeline.probe --entity company
python -m pipeline.probe --entity communication

# Keep test scope intentionally narrow so a fresh Codespace can validate quickly.
pytest tests -q -p no:cacheprovider

echo "Smoke path complete."
