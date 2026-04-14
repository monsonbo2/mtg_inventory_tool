#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${FRONTEND_DIR}/.." && pwd)"
BACKEND_PYTHON="$(bash "${SCRIPT_DIR}/resolve_repo_python.sh")"

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

has_db_arg=0
for arg in "$@"; do
  if [ "$arg" = "--db" ]; then
    has_db_arg=1
    break
  fi
done

if [ "$has_db_arg" -eq 0 ]; then
  set -- --db "${REPO_ROOT}/var/db/frontend_demo.db" "$@"
fi

exec "${BACKEND_PYTHON}" "${REPO_ROOT}/scripts/bootstrap_frontend_demo.py" "$@"
