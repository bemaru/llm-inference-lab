#!/usr/bin/env bash

set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

docker compose up -d

url="$(mlflow_url)"
deadline=$((SECONDS + 180))
until curl --fail --silent "$url/health" >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "MLflow did not become healthy within 180 seconds." >&2
    docker compose ps >&2
    docker compose logs --tail=100 mlflow >&2
    exit 1
  fi
  sleep 2
done

echo "MLflow is ready: $url"
