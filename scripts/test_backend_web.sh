#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

python3 -c 'import pathlib, mtg_source_stack; expected = pathlib.Path("src").resolve(); actual = pathlib.Path(mtg_source_stack.__file__).resolve(); raise SystemExit(0 if expected in actual.parents else f"mtg_source_stack resolved from unexpected checkout: {actual}")'

if ! python3 -c 'import fastapi, httpx, multipart, pydantic, uvicorn' >/dev/null 2>&1; then
  echo "Backend web/API tests require the optional web dependencies." >&2
  echo "Install them first with: pip install -e '.[web]'" >&2
  exit 1
fi

python3 -m unittest tests.test_api_contract tests.test_api_app tests.test_web_api -q
