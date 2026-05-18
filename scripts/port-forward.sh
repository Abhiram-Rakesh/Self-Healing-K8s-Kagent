#!/bin/bash
# port-forward.sh — opens five service tunnels at once.
# Binds to 0.0.0.0 so the URLs are reachable from your LAN.
set -euo pipefail

GREEN=$'\033[0;32m'
CYAN=$'\033[0;36m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

log()  { printf "%s[pf]%s %s\n" "$CYAN" "$NC" "$*"; }
ok()   { printf "%s[ok]%s %s\n" "$GREEN" "$NC" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$YELLOW" "$NC" "$*"; }

BIND_ADDR="${BIND_ADDR:-0.0.0.0}"
LOG_DIR="${LOG_DIR:-/tmp/kagent-portforward}"
mkdir -p "$LOG_DIR"

PIDS=()
cleanup() {
  log "Stopping port-forwards"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

start_pf() {
  local label="$1" ns="$2" svc="$3" local_port="$4" remote_port="$5"
  if ! kubectl -n "$ns" get svc "$svc" >/dev/null 2>&1; then
    warn "$label: service $ns/$svc not found, skipping"
    return 0
  fi
  log "$label -> http://${BIND_ADDR}:${local_port}  (svc/${svc} ${remote_port})"
  kubectl -n "$ns" port-forward --address "$BIND_ADDR" \
    "svc/$svc" "${local_port}:${remote_port}" \
    >"$LOG_DIR/${label}.log" 2>&1 &
  PIDS+=($!)
}

start_pf grafana       monitoring monitoring-grafana                          3000  80
start_pf prometheus    monitoring monitoring-kube-prometheus-prometheus       9090  9090
start_pf alertmanager  monitoring monitoring-kube-prometheus-alertmanager     9093  9093
start_pf kagent-ui     kagent     kagent-ui                                   8080  80
start_pf healer        kagent     kagent-healer                               8000  8000

ok "All available port-forwards started. Logs: $LOG_DIR"
ok "Press Ctrl-C to stop."

wait
