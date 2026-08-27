#!/usr/bin/env bash

set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

public_uri="$(mlflow_url)"
docker compose exec -T mlflow \
  python - \
  --tracking-uri http://127.0.0.1:5000 \
  --public-uri "$public_uri" < "$mlflow_dir/scripts/smoke.py"
