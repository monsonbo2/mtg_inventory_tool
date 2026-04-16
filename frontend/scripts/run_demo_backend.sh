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

if ! "${BACKEND_PYTHON}" -c 'import fastapi, uvicorn, pydantic' >/dev/null 2>&1; then
  echo "Selected Python interpreter '${BACKEND_PYTHON}' is missing the FastAPI web dependencies." >&2
  echo "The frontend demo launcher prefers '${REPO_ROOT}/.venv/bin/python' when it exists." >&2
  echo "Install the repo web stack, for example:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  . .venv/bin/activate" >&2
  echo "  pip install -e '.[web]'" >&2
  echo "Or set MTG_FRONTEND_PYTHON=/path/to/python if you use another environment." >&2
  exit 1
fi

exec "${BACKEND_PYTHON}" -c 'from mtg_source_stack.api.app import main; import sys; main(sys.argv[1:])' "$@"
