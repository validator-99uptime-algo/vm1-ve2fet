#!/bin/bash
# Parallel collector:
# - Up to MAX_PARALLEL SSH jobs at a time across vm1..vmN (N = MAX_VM)
# - SSH ConnectTimeout=4s
# - Writes per-host JSON to output/status/vm<N>.json
# - Optionally runs update_catchup_24h.py afterward
# - Rebuilds output/fleet-status.json
# - NO per-run log file; all output goes to stdout (your cron-collector.log)

set -euo pipefail

# ====== EDIT THESE CONSTANTS AS NEEDED ======
MAX_VM=44               # highest VM number (vm1..vm44). Change here only.
MAX_PARALLEL=20         # number of VMs to collect concurrently
CONNECT_TIMEOUT=4       # SSH ConnectTimeout (seconds)
USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"
# ===========================================

BASE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
OUT_DIR="$BASE_DIR/output"
STATUS_DIR="$OUT_DIR/status"
mkdir -p "$STATUS_DIR"

TS="$(date +%Y%m%d-%H%M%S)"
START_EPOCH="$(date +%s)"
START_HUMAN="$(date '+%Y-%m-%d %H:%M:%S %Z')"

log() { echo "$*"; }

log "=== Collector start: $TS ($START_HUMAN) ==="
log "--- Settings: MAX_VM=$MAX_VM MAX_PARALLEL=$MAX_PARALLEL CONNECT_TIMEOUT=$CONNECT_TIMEOUT ---"

write_error_json() {
  local host="$1"
  local err="$2"
  local now_epoch
  now_epoch="$(date +%s)"
  cat > "$STATUS_DIR/${host%.local}.json" <<EOF
{
  "host": "$host",
  "reachable": false,
  "error": "$(echo "$err" | sed 's/"/\\"/g')",
  "collected_at": $now_epoch
}
EOF
}

# ---- single-host worker (runs in background for each VM) ----
collect_one() {
  local i="$1"
  local HOST="vm${i}.local"
  local VM_NAME="vm${i}"

  log "--- [$HOST] collecting ---"

  # Remote script produces one JSON object on stdout
  if ! JSON_OUT=$(
    ssh -i "$SSH_KEY" -o ConnectTimeout="$CONNECT_TIMEOUT" -o BatchMode=yes \
        "$USER@$HOST" 'bash -s' <<'REMOTESCRIPT'
set -euo pipefail

json_escape() {
  printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

HOSTNAME="$(hostname || echo unknown)"
KERNEL="$(uname -r || echo unknown)"
UPTIME_S="$(awk '{print int($1)}' /proc/uptime 2>/dev/null || echo 0)"
VCPUS="$(nproc 2>/dev/null || echo 0)"
DISK_ROOT_FREE="$(df -hP / 2>/dev/null | awk 'NR==2{print $4}' || echo "unknown")"
SWAP_USED_MB="$(free -m 2>/dev/null | awk '/^Swap:/ {print $3}' || echo 0)"

SIM_OUT="$(apt-get -s -o Debug::NoLocking=true -o APT::Get::Show-User-Simulation-Note=false full-upgrade 2>/dev/null || true)"
PENDING_UPDATES="$(printf "%s" "$SIM_OUT" | awk '/^Inst /{c++} END{print c+0}')"
SECURITY_UPDATES="$(printf "%s" "$SIM_OUT" | awk '/^Inst / && /-security/{c++} END{print c+0}')"

if [ -f /var/run/reboot-required ]; then REBOOT_REQUIRED=true; else REBOOT_REQUIRED=false; fi
if [ -f /var/run/reboot-required.pkgs ]; then
  REBOOT_PKGS="$(tr '\n' ',' < /var/run/reboot-required.pkgs | sed 's/,$//')"
else
  REBOOT_PKGS=""
fi

APT_REFRESH_EPOCH="$(stat -c %Y /var/lib/apt/periodic/update-success-stamp 2>/dev/null || echo 0)"

if command -v algod >/dev/null 2>&1; then
  ALGOD_VERSION="$(algod -v 2>/dev/null | sed -n '2p' | awk '{print $1}' || true)"
else
  ALGOD_VERSION=""
fi

if [ -e /var/lib/algorand/node.log ]; then NODE_LOG_PRESENT=true; else NODE_LOG_PRESENT=false; fi
if ls /var/lib/algorand/*.log >/dev/null 2>&1; then ANY_LOGS_PRESENT=true; else ANY_LOGS_PRESENT=false; fi

COLLECTED_AT="$(date +%s)"

printf '{'
printf '"host":"%s",'   "$(json_escape "$HOSTNAME")"
printf '"reachable":true,'
printf '"hostname":"%s",' "$(json_escape "$HOSTNAME")"
printf '"kernel":"%s",'   "$(json_escape "$KERNEL")"
printf '"uptime_seconds":%s,' "$UPTIME_S"
printf '"vcpus":%s,' "$VCPUS"
printf '"disk_root_free":"%s",' "$(json_escape "$DISK_ROOT_FREE")"
printf '"swap_used_mb":%s,' "$SWAP_USED_MB"
printf '"pending_updates":%s,' "$PENDING_UPDATES"
printf '"security_updates":%s,' "$SECURITY_UPDATES"
printf '"reboot_required":%s,' "$REBOOT_REQUIRED"
printf '"reboot_pkgs":"%s",' "$(json_escape "$REBOOT_PKGS")"
printf '"apt_last_refresh_epoch":%s,' "$APT_REFRESH_EPOCH"
printf '"algod_version":"%s",' "$(json_escape "$ALGOD_VERSION")"
printf '"algorand_logs":{"node_log_present":%s,"any_logs_present":%s},' "$NODE_LOG_PRESENT" "$ANY_LOGS_PRESENT"
printf '"error":"",'
printf '"collected_at":%s' "$COLLECTED_AT"
printf '}\n'
REMOTESCRIPT
  ); then
    log "[$HOST] ERROR: ssh or remote script failed"
    write_error_json "$HOST" "ssh or remote script failed"
    return
  fi

  echo "$JSON_OUT" > "$STATUS_DIR/${VM_NAME}.json"
  log "[$HOST] OK -> $STATUS_DIR/${VM_NAME}.json"
}

# ---- launch up to MAX_PARALLEL background jobs ----
pids=()
for i in $(seq 1 "$MAX_VM"); do
  collect_one "$i" &
  pids+=("$!")
  if (( ${#pids[@]} >= MAX_PARALLEL )); then
    wait "${pids[0]}" || true
    pids=("${pids[@]:1}")
  fi
done
for pid in "${pids[@]}"; do
  wait "$pid" || true
done

# ---- CatchupStart counts (last 24h) — only if updater exists ----
if [ -f "$BASE_DIR/update_catchup_24h.py" ]; then
  log "--- Updating CatchupStart counts (last 24h) ---"
  python3 "$BASE_DIR/update_catchup_24h.py"
else
  log "--- Skipping CatchupStart update (update_catchup_24h.py not found) ---"
fi

# ---- Aggregate into fleet-status.json ----
{
  echo '['
  first=1
  for f in "$STATUS_DIR"/*.json; do
    [ -e "$f" ] || continue
    if [ $first -eq 1 ]; then first=0; else echo ','; fi
    cat "$f"
  done
  echo ']'
} > "$OUT_DIR/fleet-status.json"

log "Aggregate: $OUT_DIR/fleet-status.json"

END_EPOCH="$(date +%s)"
END_HUMAN="$(date '+%Y-%m-%d %H:%M:%S %Z')"
ELAPSED="$((END_EPOCH - START_EPOCH))"
printf -v ELAPSED_FMT '%02d:%02d:%02d' "$((ELAPSED/3600))" "$(((ELAPSED%3600)/60))" "$((ELAPSED%60))"

log "=== Collector end: $(date +%Y%m%d-%H%M%S) ($END_HUMAN) ==="
log "--- Total runtime: ${ELAPSED}s (${ELAPSED_FMT}) ---"
