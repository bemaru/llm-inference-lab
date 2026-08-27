#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  dashboard-tunnel.sh start <ssh-target>
  dashboard-tunnel.sh status <ssh-target>
  dashboard-tunnel.sh stop <ssh-target>

The SSH target may also be supplied through DGX_SPARK_SSH_TARGET.
EOF
}

action="${1:-}"
ssh_target="${2:-${DGX_SPARK_SSH_TARGET:-}}"
local_port="${DGX_SPARK_DASHBOARD_LOCAL_PORT:-11000}"
remote_port="${DGX_SPARK_DASHBOARD_REMOTE_PORT:-11000}"

if [[ "$action" != "start" && "$action" != "status" && "$action" != "stop" ]]; then
  usage >&2
  exit 2
fi

if [[ -z "$ssh_target" ]]; then
  echo "ERROR: provide an SSH target as the second argument or DGX_SPARK_SSH_TARGET." >&2
  usage >&2
  exit 2
fi

for port in "$local_port" "$remote_port"; do
  if [[ ! "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
    echo "ERROR: invalid TCP port: $port" >&2
    exit 2
  fi
done

control_path="${XDG_RUNTIME_DIR:-/tmp}/llm-inference-lab-spark-dashboard-${UID}-${local_port}.sock"
forward="127.0.0.1:${local_port}:127.0.0.1:${remote_port}"

tunnel_is_running() {
  ssh -S "$control_path" -O check "$ssh_target" >/dev/null 2>&1
}

case "$action" in
  start)
    if tunnel_is_running; then
      echo "Dashboard tunnel is already running: http://127.0.0.1:${local_port}"
      exit 0
    fi

    rm -f -- "$control_path"
    if command -v ss >/dev/null 2>&1 \
      && ss -H -ltn "sport = :${local_port}" 2>/dev/null | grep -q .; then
      echo "ERROR: local port ${local_port} is already in use by another process." >&2
      exit 1
    fi

    ssh \
      -fN \
      -M \
      -S "$control_path" \
      -o BatchMode=yes \
      -o ControlPersist=no \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 \
      -L "$forward" \
      "$ssh_target"

    echo "Dashboard tunnel started: http://127.0.0.1:${local_port}"
    ;;
  status)
    if tunnel_is_running; then
      echo "Dashboard tunnel is running: http://127.0.0.1:${local_port}"
    else
      echo "Dashboard tunnel is not running."
      exit 1
    fi
    ;;
  stop)
    if ! tunnel_is_running; then
      rm -f -- "$control_path"
      echo "Dashboard tunnel is not running."
      exit 0
    fi

    ssh -S "$control_path" -O exit "$ssh_target" >/dev/null
    rm -f -- "$control_path"
    echo "Dashboard tunnel stopped."
    ;;
esac
