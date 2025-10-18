#!/bin/bash

USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"

for i in {34..34}; do
  TARGET_VM="vm$i.local"
  echo "Setting up Chrony on $TARGET_VM ..."

  # Copy chrony.conf to remote /tmp
  scp -i $SSH_KEY /etc/chrony/chrony.conf $USER@$TARGET_VM:/tmp/ || { echo "❌ Failed to copy chrony.conf to $TARGET_VM"; exit 1; }

  # All remote setup and cleanup in one SSH session (ONE sudo prompt per VM)
  ssh -i $SSH_KEY -t $USER@$TARGET_VM '
    set -e
    echo "Disabling and stopping systemd-timesyncd..."
    sudo systemctl stop systemd-timesyncd || true
    sudo systemctl disable systemd-timesyncd || true

    echo "Installing chrony..."
    sudo apt update && sudo apt install chrony -y

    echo "Placing chrony.conf into place..."
    sudo cp /tmp/chrony.conf /etc/chrony/chrony.conf

    echo "Cleaning up /tmp/chrony.conf ..."
    rm -f /tmp/chrony.conf

    echo "Enabling and restarting chrony service..."
    sudo systemctl enable chrony
    sudo systemctl restart chrony

    echo "Chrony setup complete."
  ' || { echo "❌ Failed to configure Chrony on $TARGET_VM"; exit 1; }

  echo "✅ Chrony installed and configured on $TARGET_VM"
  echo
done

echo "----- All done! -----"
