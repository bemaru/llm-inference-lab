#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
publish_script="$repo_root/tracking/mlflow/scripts/publish.sh"
manifest="tracking/mlflow/imports/example.json"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT
fake_bin="$tmp_dir/bin"
capture_file="$tmp_dir/uv-capture"
docker_capture="$tmp_dir/docker-capture"
smoke_capture="$tmp_dir/smoke-stdin"
mkdir -p -- "$fake_bin"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'printf "%s\n" "$*" >> "$MOCK_DOCKER_CAPTURE"' \
  'case "$*" in' \
  '  "compose version") exit 0 ;;' \
  '  "compose port mlflow 5000") printf "%s\n" "127.0.0.1:15000" ;;' \
  '  "compose exec -T mlflow python - "*) cat > "$MOCK_SMOKE_CAPTURE" ;;' \
  '  *) echo "unexpected docker call: $*" >&2; exit 97 ;;' \
  'esac' \
  > "$fake_bin/docker"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  '{' \
  '  printf "args=%s\\n" "$*"' \
  '  printf "uri=%s\\n" "${MLFLOW_TRACKING_URI-}"' \
  '} > "$MOCK_UV_CAPTURE"' \
  > "$fake_bin/uv"
chmod 755 "$fake_bin/docker" "$fake_bin/uv"

(
  cd "$repo_root"
  PATH="$fake_bin:$PATH" \
  MOCK_DOCKER_CAPTURE="$docker_capture" \
  MOCK_UV_CAPTURE="$capture_file" \
    "$publish_script" "$manifest"
)

capture="$(<"$capture_file")"
[[ "$capture" == *"run --locked --script "*"publish_record.py"* ]] || fail "publisher did not use the locked uv script"
[[ "$capture" == *"--workspace $repo_root"* ]] || fail "publisher workspace mapping is incorrect"
[[ "$capture" == *"--manifest $manifest"* ]] || fail "publisher manifest mapping is incorrect"
[[ "$capture" == *"--public-uri http://127.0.0.1:15000"* ]] || fail "public URI is incorrect"
[[ "$capture" == *"uri=http://127.0.0.1:15000"* ]] || fail "tracking URI was not passed"
if grep -q '^compose .*run' "$docker_capture"; then
  fail "publisher container was invoked"
fi

PATH="$fake_bin:$PATH" \
MOCK_DOCKER_CAPTURE="$docker_capture" \
MOCK_SMOKE_CAPTURE="$smoke_capture" \
  "$repo_root/tracking/mlflow/scripts/smoke.sh"
cmp "$repo_root/tracking/mlflow/scripts/smoke.py" "$smoke_capture" || fail "smoke script was not passed through stdin"
grep -Fq 'compose exec -T mlflow python - --tracking-uri http://127.0.0.1:5000 --public-uri http://127.0.0.1:15000' "$docker_capture" || fail "smoke invocation is incorrect"

echo "local MLflow client tests: PASS"
