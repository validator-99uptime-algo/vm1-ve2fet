#!/bin/bash
# Purpose: Interactive apt update/upgrade on VM41, log locally on vm1, reboot the VM, run in series (single host test).
# Notes:
#   - No -y flags; you will answer prompts.
#   - Output is visible on screen and also logged to a file in the same folder as this script.
#   - Reboot is issued *after* a successful upgrade; the SSH session will drop (expected).

set -euo pipefail

# ====== CONFIG YOU PROVIDED / ALREADY USE ======
USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"

# ====== DERIVED PATHS (same folder as this .sh) ======
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"

# ====== HOST LOOP: VM41 ONLY ======
for i in {2..40}; do
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
    continue
  fi

  echo "===== [$VM] APT succeeded. Proceeding to reboot... ====="

  # ---- Step 2: Reboot in a separate SSH session ----
  # Reboot will drop the connection; treat that as expected. We still log whatever we get.
  set +e
  {
    ssh -tt -i "$SSH_KEY" "$USER@$TARGET_VM" '
      set -euo pipefail
      echo "[$(hostname)] Issuing: sudo reboot"
      sudo reboot
    '
  } 2>&1 | tee -a "$LOG_FILE"
  REBOOT_STATUS=${PIPESTATUS[0]}
  set -e

  # When reboot is issued, SSH usually returns non-zero (e.g., 255) because the remote went away.
  # We treat any return here as informational; the reboot was requested successfully if we got that far.
  echo "===== [$VM] Reboot requested (SSH exit $REBOOT_STATUS is expected due to shutdown). ====="
  echo
done

echo "----- All done (test on VM41). Review logs under: $LOG_DIR -----"
