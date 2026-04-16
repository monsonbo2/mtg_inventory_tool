#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${FRONTEND_DIR}/.." && pwd)"

if [ -n "${MTG_FRONTEND_PYTHON:-}" ]; then
  printf '%s\n' "${MTG_FRONTEND_PYTHON}"
  exit 0
fi

if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  printf '%s\n' "${REPO_ROOT}/.venv/bin/python"
  exit 0
fi

if command -v python3 >/dev/null 2>&1; then
  printf '%s\n' "python3"
  exit 0
fi

echo "Could not find a Python interpreter for the frontend demo tools." >&2
echo "Set MTG_FRONTEND_PYTHON or create ${REPO_ROOT}/.venv/bin/python." >&2
exit 1
