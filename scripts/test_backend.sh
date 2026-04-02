#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

python3 -c 'import pathlib, mtg_source_stack; expected = pathlib.Path("src").resolve(); actual = pathlib.Path(mtg_source_stack.__file__).resolve(); raise SystemExit(0 if expected in actual.parents else f"mtg_source_stack resolved from unexpected checkout: {actual}")'
python3 -m unittest discover -s tests -q
