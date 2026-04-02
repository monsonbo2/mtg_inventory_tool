#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${FRONTEND_DIR}/.." && pwd)"

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

exec python3 -c 'from mtg_source_stack.api.app import main; import sys; main(sys.argv[1:])' "$@"
