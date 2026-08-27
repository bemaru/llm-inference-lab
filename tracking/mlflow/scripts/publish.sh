#!/usr/bin/env bash

set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
invocation_dir="$PWD"
# shellcheck disable=SC1091
source "$script_dir/common.sh"

if (( $# != 1 )); then
  echo "Usage: publish.sh <repo-relative-manifest.json>" >&2
  exit 2
fi

repo_root="$(cd -- "$mlflow_dir/../.." && pwd)"
case "$1" in
  /*) manifest_path="$(realpath -- "$1")" ;;
  *) manifest_path="$(realpath -- "$invocation_dir/$1")" ;;
esac
case "$manifest_path" in
  "$repo_root"/*) ;;
  *)
    echo "Manifest must be inside the repository: $manifest_path" >&2
    exit 2
    ;;
esac

manifest_relative="${manifest_path#"$repo_root"/}"
public_uri="$(mlflow_url)"

require_command uv
MLFLOW_TRACKING_URI="$public_uri" uv run --locked --script "$script_dir/publish_record.py" \
  --workspace "$repo_root" \
  --manifest "$manifest_relative" \
  --public-uri "$public_uri"
