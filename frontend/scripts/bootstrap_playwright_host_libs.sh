#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LIB_ROOT="${FRONTEND_DIR}/.playwright-linux-libs"
DEB_DIR="${LIB_ROOT}/debs"
ROOT_DIR="${LIB_ROOT}/root"
TMP_DIR="$(mktemp -d)"
PACKAGES=(
  libnspr4
  libnss3
  libasound2t64
)

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

mkdir -p "${TMP_DIR}"

(
  cd "${TMP_DIR}"
  apt download "${PACKAGES[@]}"
)

rm -rf "${DEB_DIR}" "${ROOT_DIR}"
mkdir -p "${DEB_DIR}" "${ROOT_DIR}"
mv "${TMP_DIR}"/*.deb "${DEB_DIR}/"

for deb in "${DEB_DIR}"/*.deb; do
  dpkg-deb -x "${deb}" "${ROOT_DIR}"
done

echo "Playwright host libraries extracted under ${ROOT_DIR}"
