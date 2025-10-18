#!/bin/bash

USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"
# VMS=(vm4 vm6 vm7 vm8 vm9 vm10 vm12 vm14 vm20 vm21 vm23 vm27 vm29 vm31 vm34 vm35 vm37)
# VMS=(vm41)

for i in {2..41}; do
  VM="vm${i}"
  TARGET_VM="${VM}.local"
  echo "Configuring Algorand nolog on $TARGET_VM ..."

  ssh -i "$SSH_KEY" -t "$USER@$TARGET_VM" '
    set -e

    # 1. Add -o to ExecStart if not present
    ALGOD_SERVICE="/usr/lib/systemd/system/algorand.service"
    if ! grep -q -- "-o" "$ALGOD_SERVICE"; then
      echo "Patching ExecStart with -o ..."
      sudo sed -i "s|^\(ExecStart=/usr/bin/algod -d /var/lib/algorand\)\(.*\)|\1 -o\2|" "$ALGOD_SERVICE"
    fi

    # 2. Add drop-in override for journald if not present
    DROPIN_DIR="/etc/systemd/system/algorand.service.d"
    DROPIN_FILE="$DROPIN_DIR/nolog.conf"
    sudo mkdir -p "$DROPIN_DIR"
    if [ ! -f "$DROPIN_FILE" ] || ! grep -q "StandardOutput=null" "$DROPIN_FILE"; then
      echo -e "[Service]\nStandardOutput=null\nStandardError=null" | sudo tee "$DROPIN_FILE"
    fi

    # 3. Stop Valar first, then Algorand
    echo "Stopping Valar ..."
    sudo systemctl stop valar.service

    echo "Stopping Algorand ..."
    sudo systemctl stop algorand.service


    # 4. Delete old logs
    echo "Deleting old .log files ..."
    sudo rm -f /var/lib/algorand/*.log

    # 5. Reload systemd and start Algorand
    echo "Reloading systemd and starting Algorand ..."
    sudo systemctl daemon-reload
    sudo systemctl start algorand.service

    # 6. Restart Valar
    echo "Starting Valar ..."
    sudo systemctl start valar.service

    echo "Refreshing swap for this VM ..."
    sudo swapoff -a
    sudo swapon -a

    echo "Algorand nolog configuration complete on $(hostname)."
  ' || { echo "❌ Failed on $TARGET_VM"; exit 1; }

  echo "✅ Algorand nolog setup done on $TARGET_VM"
  echo
done

echo "----- All done! -----"
