#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${FRONTEND_DIR}/.." && pwd)"
BACKEND_PYTHON="$(bash "${SCRIPT_DIR}/resolve_repo_python.sh")"

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

exec "${BACKEND_PYTHON}" "${REPO_ROOT}/scripts/shared_service_proxy_harness.py" "$@"
