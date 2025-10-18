#!/bin/bash
# Purpose: Interactive apt update/upgrade on VMs, log locally on vm1, reboot ONLY if required.
# Notes:
#   - No -y flags; you will answer prompts.
#   - Output is visible on screen and also logged to a file in the same folder as this script.

set -euo pipefail

# ====== CONFIG YOU PROVIDED / ALREADY USE ======
USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"

# ====== DERIVED PATHS (same folder as this .sh) ======
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"

# ====== HOST LOOP (your current range) ======
for i in {2..44}; do
  VM="vm${i}"
  TARGET_VM="${VM}.local"
  LOG_FILE="$LOG_DIR/apt-${VM}-${TS}.log"

  echo "===== [$VM] Starting interactive apt update/upgrade (logging to $LOG_FILE) ====="

  # ---- Step 1: Run apt commands interactively and capture exit status ----
  # We keep apt in the *first* SSH session so we get a reliable exit code.
  # You will see prompts on screen due to -tt (forced TTY).
  set +e
  {
    ssh -tt -i "$SSH_KEY" "$USER@$TARGET_VM" '
      set -euo pipefail
      echo "[$(hostname)] Running: sudo apt-get update"
      sudo apt-get update

      echo "[$(hostname)] Running: sudo apt-get full-upgrade (interactive; answer prompts as needed)"
      sudo apt-get full-upgrade

      echo "[$(hostname)] Running: sudo apt-get autoremove --purge (interactive if needed)"
      sudo apt-get autoremove --purge

      echo "[$(hostname)] Running: sudo apt-get autoclean"
      sudo apt-get autoclean

      echo "[$(hostname)] APT operations completed successfully."
    '
  } 2>&1 | tee "$LOG_FILE"
  APT_STATUS=${PIPESTATUS[0]}
  set -e

  if [[ $APT_STATUS -ne 0 ]]; then
    echo "===== [$VM] APT FAILED (exit $APT_STATUS). See $LOG_FILE ====="
    echo
    continue
  fi

  echo "===== [$VM] Checking if reboot is required... ====="

  # ---- Step 2: Reboot ONLY if /var/run/reboot-required exists ----
  set +e
  {
    ssh -tt -i "$SSH_KEY" "$USER@$TARGET_VM" '
      set -euo pipefail
      if [ -f /var/run/reboot-required ]; then
        echo "[$(hostname)] Reboot required. Issuing: sudo reboot"
        sudo reboot
      else
        echo "[$(hostname)] No reboot required. Skipping reboot."
      fi
    '
  } 2>&1 | tee -a "$LOG_FILE"
  REBOOT_STATUS=${PIPESTATUS[0]}
  set -e

  # Note: if a reboot was issued, SSH typically returns non-zero due to disconnect; that’s expected.
  echo "===== [$VM] Reboot check complete (SSH exit $REBOOT_STATUS may be non-zero if reboot happened). ====="
  echo
done

echo "----- All done. Review logs under: $LOG_DIR -----"
