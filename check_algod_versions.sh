#!/bin/bash

USER="ve2pcq"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"

for i in {40..44}; do
  TARGET_VM="vm$i.local"
  echo -n "Algorand algod version on $TARGET_VM: "

  ssh -i $SSH_KEY $USER@$TARGET_VM '
    algod -v 2>/dev/null | sed -n "2p" | awk "{print \$1}"
    if [ -f /var/lib/algorand/node.log ]; then
      echo "node.log present: Yes"
    else
      echo "node.log present: No"
    fi
  '
  if [ $? -ne 0 ]; then
    echo "❌ Could not connect or 'algod' not found on $TARGET_VM"
  fi
  echo "--------------------------------------------"
done
