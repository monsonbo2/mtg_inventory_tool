#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export JUPYTER_CONFIG_DIR="$PROJECT_ROOT/.jupyter/config"
export JUPYTER_DATA_DIR="$PROJECT_ROOT/.jupyter/data"
export JUPYTER_RUNTIME_DIR="$PROJECT_ROOT/.jupyter/runtime"
export IPYTHONDIR="$PROJECT_ROOT/.jupyter/ipython"
export MPLCONFIGDIR="$PROJECT_ROOT/.jupyter/matplotlib"

mkdir -p \
  "$JUPYTER_CONFIG_DIR" \
  "$JUPYTER_DATA_DIR" \
  "$JUPYTER_RUNTIME_DIR" \
  "$IPYTHONDIR" \
  "$MPLCONFIGDIR"

exec "$PROJECT_ROOT/.venv/bin/jupyter" lab "$PROJECT_ROOT/notebooks/review_inventory.ipynb"
