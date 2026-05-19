#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

if ! "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("127.0.0.1", 0))
finally:
    sock.close()
PY
then
  echo "Localhost socket binding is unavailable." >&2
  echo "Live API/proxy tests that need 127.0.0.1 will be skipped." >&2
  echo "In Codex/sandboxed runs, rerun this script with elevated permissions to exercise them." >&2
fi

"${PYTHON_BIN}" -c 'import pathlib, mtg_source_stack; expected = pathlib.Path("src").resolve(); actual = pathlib.Path(mtg_source_stack.__file__).resolve(); raise SystemExit(0 if expected in actual.parents else f"mtg_source_stack resolved from unexpected checkout: {actual}")'
"${PYTHON_BIN}" -m unittest discover -s tests -q
