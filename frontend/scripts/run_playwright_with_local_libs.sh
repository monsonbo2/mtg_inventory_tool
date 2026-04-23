#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LIB_ROOT="${FRONTEND_DIR}/.playwright-linux-libs/root"
LIB_DIRS=()

for candidate in \
  "${LIB_ROOT}/usr/lib/aarch64-linux-gnu" \
  "${LIB_ROOT}/lib/aarch64-linux-gnu" \
  "${LIB_ROOT}/usr/lib/x86_64-linux-gnu" \
  "${LIB_ROOT}/lib/x86_64-linux-gnu" \
  "${LIB_ROOT}/usr/lib" \
  "${LIB_ROOT}/lib"; do
  if [ -d "${candidate}" ]; then
    LIB_DIRS+=("${candidate}")
  fi
done

if [ "${#LIB_DIRS[@]}" -gt 0 ]; then
  PLAYWRIGHT_LIBRARY_PATH="$(IFS=:; printf '%s' "${LIB_DIRS[*]}")"
  export LD_LIBRARY_PATH="${PLAYWRIGHT_LIBRARY_PATH}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

exec npx playwright "$@"
