#!/usr/bin/env bash

set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

docker compose ps

if url="$(mlflow_url)" && curl --fail --silent "$url/health" >/dev/null; then
  echo "MLflow health: ok ($url)"
else
  echo "MLflow health: unavailable" >&2
  exit 1
fi
