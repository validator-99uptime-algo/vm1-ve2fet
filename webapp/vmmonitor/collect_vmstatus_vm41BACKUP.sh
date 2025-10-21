#!/bin/bash
# Collector: loop explicitly from VM41..VM44 (easy to expand later).
# No sudo on remotes. Serial SSH. Writes per-host JSON + aggregate JSON.
# Logs to vmmonitor/logs/.

set -euo pipefail

USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"

BASE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
OUT_DIR="$BASE_DIR/output"
STATUS_DIR="$OUT_DIR/status"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$STATUS_DIR" "$LOG_DIR"

TS="$(date +%Y%m%d-%H%M%S)"
RUN_LOG="$LOG_DIR/collect-$TS.log"

echo "=== Collector start: $TS ===" | tee -a "$RUN_LOG"

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

# ----- LOOP: exactly VM41..VM44 -----
for i in {1..44}; do
  HOST="vm${i}.local"
  VM_NAME="vm${i}"
  echo "--- [$HOST] collecting ---" | tee -a "$RUN_LOG"

  if ! JSON_OUT=$(ssh -i "$SSH_KEY" -o ConnectTimeout=10 "$USER@$HOST" 'bash -s' <<'REMOTESCRIPT'
set -euo pipefail

json_escape() {
  echo -n "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

HOSTNAME="$(hostname || echo unknown)"
KERNEL="$(uname -r || echo unknown)"
UPTIME_S="$(awk "{print int(\$1)}" /proc/uptime 2>/dev/null || echo 0)"
VCPUS="$(nproc 2>/dev/null || echo 0)"
DISK_ROOT_FREE="$(df -hP / 2>/dev/null | awk "NR==2{print \$4}" || echo "unknown")"
SWAP_USED_MB="$(free -m 2>/dev/null | awk "/^Swap:/ {print \$3}" || echo 0)"

SIM_OUT="$(apt-get -s -o Debug::NoLocking=true -o APT::Get::Show-User-Simulation-Note=false full-upgrade 2>/dev/null || true)"
PENDING_UPDATES="$(printf "%s" "$SIM_OUT" | awk "/^Inst /{c++} END{print c+0}")"
SECURITY_UPDATES="$(printf "%s" "$SIM_OUT" | awk "/^Inst / && /-security/{c++} END{print c+0}")"

if [ -f /var/run/reboot-required ]; then REBOOT_REQUIRED=true; else REBOOT_REQUIRED=false; fi
if [ -f /var/run/reboot-required.pkgs ]; then
  REBOOT_PKGS="$(tr "\n" "," < /var/run/reboot-required.pkgs | sed "s/,$//")"
else
  REBOOT_PKGS=""
fi

APT_REFRESH_EPOCH="$(stat -c %Y /var/lib/apt/periodic/update-success-stamp 2>/dev/null || echo 0)"

if command -v algod >/dev/null 2>&1; then
  ALGOD_VERSION="$(algod -v 2>/dev/null | sed -n "2p" | awk "{print \$1}" || true)"
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
    echo "[$HOST] ERROR: SSH/collect failed" | tee -a "$RUN_LOG"
    write_error_json "$HOST" "ssh or remote script failed"
    continue
  fi

  echo "$JSON_OUT" > "$STATUS_DIR/${VM_NAME}.json"
  echo "[$HOST] OK -> $STATUS_DIR/${VM_NAME}.json" | tee -a "$RUN_LOG"
done

# Aggregate
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

echo "Aggregate: $OUT_DIR/fleet-status.json" | tee -a "$RUN_LOG"
echo "=== Collector end: $(date +%Y%m%d-%H%M%S) ===" | tee -a "$RUN_LOG"
