#!/usr/bin/env bash

set -euo pipefail

mlflow_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$mlflow_dir"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 1
  fi
}

require_command docker
docker compose version >/dev/null

mlflow_url() {
  local binding
  binding="$(docker compose port mlflow 5000 2>/dev/null || true)"
  if [[ -z "$binding" ]]; then
    return 1
  fi
  printf 'http://%s\n' "$binding"
}
