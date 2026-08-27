#!/usr/bin/env bash

set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

docker compose down
echo "MLflow stopped. PostgreSQL and artifact volumes were preserved."
