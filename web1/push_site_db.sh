#!/bin/bash
LOG="/home/ve2pcq/ve2fet/web1/push_site_db.log"
exec >>"$LOG" 2>&1
exec 9>"/home/ve2pcq/ve2fet/web1/push_site_db.lock"; flock -n 9 || { date -Is; echo "already running"; exit 0; }

# Build filtered site DB on VM1, stage to web1 (no sudo on web1)

set -euo pipefail

# --- CONFIG ---
SRC_DB="/home/ve2pcq/ve2fet/valar_database/valar.db"

DEST_HOST="web1.local"
DEST_USER="ve2fet"
SSH_KEY="/home/ve2pcq/.ssh/id_ed25519"

DEST_DIR="/home/${DEST_USER}/ve2fet/go99uptime"
STAGED_NAME="valar_site.sqlite.staged"          # file staged for web1 cron to publish
TABLES="validator_ads noticeboard_users currencies sys_meta delegator_states delegator_contracts part_keys delegator_contract_stats"
# -------------

TMPDIR="$(mktemp -d /tmp/site_db.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
echo "$(date -Is) — start"

echo "• Dumping selected tables (read-only)…"
sqlite3 -batch "$SRC_DB" \
  ".timeout 5000" \
  ".output $TMPDIR/filtered.sql" \
  ".dump $TABLES"

echo "• Building compact site DB…"
sqlite3 -batch "$TMPDIR/valar_site.sqlite" < "$TMPDIR/filtered.sql"
sqlite3 -batch "$TMPDIR/valar_site.sqlite" 'PRAGMA optimize; VACUUM;'

echo "• Ensuring staging folder on ${DEST_HOST}…"
ssh -i "$SSH_KEY" "${DEST_USER}@${DEST_HOST}" "mkdir -p '$DEST_DIR'"

echo "• Uploading (to a temp name)…"
scp -i "$SSH_KEY" "$TMPDIR/valar_site.sqlite" "${DEST_USER}@${DEST_HOST}:${DEST_DIR}/${STAGED_NAME}.incoming"

echo "• Finalizing stage (atomic rename)…"
ssh -i "$SSH_KEY" "${DEST_USER}@${DEST_HOST}" "mv -f '${DEST_DIR}/${STAGED_NAME}.incoming' '${DEST_DIR}/${STAGED_NAME}'"

# Optional quick check of the staged file (no sudo, reads in your home)
echo "• Quick-check staged file…"
ssh -i "$SSH_KEY" "${DEST_USER}@${DEST_HOST}" \
  "sqlite3 -batch 'file:${DEST_DIR}/${STAGED_NAME}?mode=ro&immutable=1' 'PRAGMA quick_check;' | grep -qi '^ok$' && echo '✓ Staged OK at: ${DEST_DIR}/${STAGED_NAME}' || (echo '✗ quick_check failed' >&2; exit 1)"

echo "✓ Done."
echo "$(date -Is) — done"
