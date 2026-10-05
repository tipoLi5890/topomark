#!/usr/bin/env bash
# Deploy helper: builds and uploads.
set -euo pipefail

log() { echo "[deploy] $*"; }

function build {
  cat <<EOF2
{ not a brace block
EOF2
  echo "done }"
}

upload()
{
  local f="$1"   # comment with {
  echo "${f}"
}
