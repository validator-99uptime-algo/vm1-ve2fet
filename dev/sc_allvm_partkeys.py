#!/usr/bin/env python3
"""
sc_allvm_partkeys.py - scan participation keys on a set of VMs

* Scope: VM 2 through VM 44 (adjust list after validation)
* SSH into each host, run `goal -d /var/lib/algorand account partkeyinfo`, parse the output
* Ignore any key block whose **Last vote round** is `N/A` or missing
* Replace rows for that vm_number in the part_keys table (DELETE + INSERT)
* Log **START / per-VM summary / END** with timestamps like 2025-07-11 15:53:01,789
  - VM line includes run time (secs with 3 decimals)
  - END line appends total script time
* Exit 0 if every VM succeeds, 1 otherwise
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, List

# -------- Config -------------------------------------------------------
VM_NUMBERS: Final[List[int]] = list(range(2, 44))  # VMs 2 .. 44 inclusive
SSH_USER:   Final[str]      = "ve2pcq"
SSH_KEY:    Final[str]      = str(Path("~/.ssh/id_ed25519").expanduser())
HOST_FMT:   Final[str]      = "vm{num}.local"     # vm2.local, vm3.local ...
ALGOD_DATA: Final[str]      = "/var/lib/algorand" # explicit data dir

DB_PATH:  Final[str] = str(Path("~/ve2fet/valar_database/valar.db").expanduser())
LOG_PATH: Final[str] = str(Path("~/ve2fet/dev/sc_allvm_partkeys.log").expanduser())

# -------- Regex patterns for `goal account partkeyinfo` output ---------
FIELD_RE = re.compile(r"^(.*?):\s+(.*)$")
PART_ID_LABEL   = "Participation ID:"
PARENT_LABEL    = "Parent address:"

# -------- Helper to handle 'N/A' --------------------------------------

def _to_int(val: str) -> int | None:
    """Convert numeric field or return None for placeholders like 'N/A' or '-'."""
    val_strip = val.strip().upper()
    if val_strip in {"N/A", "-", ""}:
        return None
    return int(val_strip)

# -------- Logging helpers ---------------------------------------------

def _log(line: str) -> None:
    """Append a line with UTC timestamp `YYYY-MM-DD HH:MM:SS,mmm`."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]  # trim to ms
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"{ts}  {line}\n")

# -------- SSH helper ---------------------------------------------------

def run_ssh_partkeyinfo(host: str) -> subprocess.CompletedProcess:
    """Run goal account partkeyinfo via SSH with explicit data dir."""
    remote_cmd = f"goal -d {ALGOD_DATA} account partkeyinfo"
    full_cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "IdentitiesOnly=yes",
        f"{SSH_USER}@{host}",
        remote_cmd,
    ]
    return subprocess.run(full_cmd, capture_output=True, text=True, timeout=60)

# -------- Parser -------------------------------------------------------

def parse_partkeyinfo(text: str):
    """Yield one dict per participation-key block."""
    current = {}
    for line in text.splitlines():
        m = FIELD_RE.match(line)
        if not m:
            continue
        label, value = m.groups()
        label = label.strip()
        if label == PART_ID_LABEL.rstrip(":"):
            if current:
                yield current
            current = {"part_id": value}
        elif label == PARENT_LABEL.rstrip(":"):
            current["parent_address"] = value
        elif label == "First round":
            current["first_round"] = _to_int(value)
        elif label == "Last round":
            current["last_round"] = _to_int(value)
        elif label == "Effective first round":
            current["eff_first_round"] = _to_int(value)
        elif label == "Effective last round":
            current["eff_last_round"] = _to_int(value)
        elif label == "Last vote round":
            current["last_vote_round"] = _to_int(value)
        elif label == "Last block proposal round":
            current["last_block_prop_round"] = _to_int(value)
    if current:
        yield current

# -------- DB helpers ---------------------------------------------------

def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout = 8000")
    return conn

# -------- Main routine -------------------------------------------------

def main() -> None:
    start_time = time.monotonic()
    _log("** START sc_allvm_partkeys **")
    overall_ok = True

    conn = connect_db()

    for num in VM_NUMBERS:
        vm_start = time.monotonic()
        host = HOST_FMT.format(num=num)
        rc = run_ssh_partkeyinfo(host)
        if rc.returncode != 0:
            _log(f"VM {num}: SSH failed ({rc.returncode}) {rc.stderr.strip()}")
            overall_ok = False
            continue

        try:
            all_rows = list(parse_partkeyinfo(rc.stdout))
            # Skip keys where last_vote_round is None (i.e., 'N/A')
            rows = [r for r in all_rows if r.get("last_vote_round") is not None]
        except Exception as e:
            _log(f"VM {num}: parse error {e}")
            overall_ok = False
            continue

        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with conn:
                conn.execute("DELETE FROM part_keys WHERE vm_number=?", (num,))
                conn.executemany(
                    """
                    INSERT INTO part_keys (
                        vm_number, parent_address, part_id,
                        first_round, last_round,
                        eff_first_round, eff_last_round,
                        last_vote_round, last_block_prop_round,
                        collected_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    [(
                        num,
                        r.get("parent_address"),
                        r.get("part_id"),
                        r.get("first_round"),
                        r.get("last_round"),
                        r.get("eff_first_round"),
                        r.get("eff_last_round"),
                        r.get("last_vote_round"),
                        r.get("last_block_prop_round"),
                        now_iso,
                    ) for r in rows]
                )
            vm_dur = time.monotonic() - vm_start
            _log(f"VM {num}: {len(rows)} keys inserted ({vm_dur:.3f} s)")
        except Exception as e:
            _log(f"VM {num}: DB error {e}")
            overall_ok = False

    conn.close()
    total_dur = time.monotonic() - start_time
    _log(f"** END   sc_allvm_partkeys ** ({total_dur:.3f} s)")
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _log(f"fatal: {exc}")
        raise
