#!/usr/bin/env bash
# Push ~/ve2fet to GitHub (vm1). Ignores venv/, *.log, valar_database/ by default.
# Usage:
#   ~/vm1-push.sh "message"                     # DB ignored
#   ~/vm1-push.sh --include-db-once "message"   # include a snapshot folder of valar_database this run

set -euo pipefail
DIR="$HOME/ve2fet"
REMOTE="git@github.com:validator-99uptime-algo/vm1-ve2fet.git"
BR="main"

INCLUDE_DB_ONCE=0
if [[ "${1:-}" == "--include-db-once" ]]; then INCLUDE_DB_ONCE=1; shift || true; fi
MSG=${1:-"Update $(date -u +'%Y-%m-%d %H:%M:%S UTC')"}
cd "$DIR"

# init once; set remote
if [[ ! -d .git ]]; then
  git init
  git remote add origin "$REMOTE" 2>/dev/null || git remote set-url origin "$REMOTE"
  git config --local user.name  "vm1"
  git config --local user.email "vm1@localhost"
fi

# ensures ignores exist
touch .gitignore
grep -qx 'venv/' .gitignore || echo 'venv/' >> .gitignore
grep -qx '*.log' .gitignore || echo '*.log' >> .gitignore
grep -qx 'valar_database/' .gitignore || echo 'valar_database/' >> .gitignore

# stage everything (respects .gitignore)
git add -A

# include DB once by making a stable snapshot folder (not the live dir)
if [[ $INCLUDE_DB_ONCE -eq 1 && -d valar_database ]]; then
  TS="$(date -u +'%Y%m%d-%H%M%S')"
  SNAP_DIR="valar_database_snapshot_${TS}"
  mkdir -p "$SNAP_DIR"

  # If sqlite3 is available, make a consistent DB copy; else do a plain copy.
  if command -v sqlite3 >/dev/null 2>&1 && [[ -f valar_database/valar.db ]]; then
    # copy all files except the main DB first
    rsync -a --exclude 'valar.db' valar_database/ "$SNAP_DIR"/
    # make a consistent DB backup into the snapshot
    sqlite3 valar_database/valar.db ".backup '$SNAP_DIR/valar.db'"
  else
    rsync -a valar_database/ "$SNAP_DIR"/
  fi

  # Add the snapshot folder (live valar_database/ remains ignored)
  git add -f "$SNAP_DIR"
fi

# commit only if changes
if git diff --cached --quiet; then
  echo "No changes."
  exit 0
fi

git commit -m "$MSG"
git push -u origin HEAD:"$BR"
