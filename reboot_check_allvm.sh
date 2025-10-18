#!/bin/bash
# Reboot vm2..vm40, prompt for sudo password once per VM, wait 20s, poll SSH until back,
# then print Algorand version and node.log presence.

set -euo pipefail

USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"

INITIAL_WAIT=19      # seconds before first reachability check
RETRY_EVERY=5        # seconds between SSH retries
TIMEOUT=600          # give up after this many seconds per VM

for i in {5..40}; do
  TARGET_VM="vm$i.local"
  echo "🔄 Rebooting $TARGET_VM ..."

  # Force a TTY so sudo can prompt for the password (interactive like your example).
  # We don't fail the script if SSH drops mid-reboot.
  ssh -tt -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
      -i "$SSH_KEY" "$USER@$TARGET_VM" 'sudo reboot' || true

  # Give the VM time to go down and start coming back up
  sleep "$INITIAL_WAIT"

  echo "⏳ Waiting for $TARGET_VM to come back online (timeout ${TIMEOUT}s)..."
  start_ts=$(date +%s)
  while true; do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
          -i "$SSH_KEY" "$USER@$TARGET_VM" 'exit' 2>/dev/null; then
      echo "✅ $TARGET_VM is back online"
      break
    fi
    now=$(date +%s)
    if (( now - start_ts >= TIMEOUT )); then
      echo "❌ $TARGET_VM did not come back within ${TIMEOUT}s"
      echo "--------------------------------------------"
      continue 2
    fi
    sleep "$RETRY_EVERY"
  done

  # Once reachable, run your original checks
  ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "$USER@$TARGET_VM" '
    echo -n "Algorand algod version: "
    algod -v 2>/dev/null | sed -n "2p" | awk "{print \$1}"
    if [ -f /var/lib/algorand/node.log ]; then
      echo "node.log present: Yes"
    else
      echo "node.log present: No"
    fi
  ' || echo "⚠️  SSH command on $TARGET_VM succeeded but inner commands failed."

  echo "--------------------------------------------"
done

echo "🎉 Reboot cycle finished"
