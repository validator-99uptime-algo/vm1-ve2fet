#!/bin/bash
# Set active_cpus.conf=8 on vm3..vm16 and vm18..vm44, then restart offline-cpus.service.
# Prompts ONCE for the sudo password and reuses it for all hosts.

set -euo pipefail
set +x  # don't echo commands (protects the password)

USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

# prompt once
read -s -p "Enter sudo password for ${USER} on target VMs: " SUDO_PW
echo

update_host () {
  local HOST="$1"
  echo "——— [${HOST}] updating cpu_management/active_cpus.conf to 8 ———"

  # write file
  ssh $SSH_OPTS -i "$SSH_KEY" "$USER@$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
DIR="$HOME/cpu_management"
FILE="$DIR/active_cpus.conf"
mkdir -p "$DIR"
printf '8\n' > "$FILE"
REMOTE

  # restart service using sudo password via stdin (no interactive prompt)
  if ! printf '%s\n' "$SUDO_PW" | ssh $SSH_OPTS -i "$SSH_KEY" "$USER@$HOST" "sudo -S systemctl restart offline-cpus.service"; then
    echo "❌  ${HOST}: restart failed"
    return 1
  fi

  # quick health check
  if ssh $SSH_OPTS -i "$SSH_KEY" "$USER@$HOST" "systemctl is-active --quiet offline-cpus.service"; then
    echo "✅  ${HOST}: service restarted and active"
  else
    echo "⚠️   ${HOST}: service not active after restart"
  fi
  echo
}

# vm3..vm16 and vm18..vm44
for i in {3..16} {18..44}; do
  update_host "vm${i}.local" || true
done

# clear password
unset SUDO_PW
echo "----- Done -----"
