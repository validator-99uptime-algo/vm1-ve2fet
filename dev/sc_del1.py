#!/usr/bin/env python3
"""
sc_del1.py  –  Valar Delegator-contract watcher (manual run, task-id 2)

 • For every Validator-Ad already stored in validator_ads
       – reads its current del_app_list on-chain
       – discovers new / ended Delegator contracts
 • Mirrors each Delegator contract’s *immutable* and *live* data into
   the delegator_contracts table
 • Keeps the currencies table in sync with any new payment-asset
 • Sends **one e-mail + log entry** per brand-new Delegator contract
   (after the initial load)
 • Writes a one-line INFO summary each scan
 • Updates sys_meta (task_id = 2) with round scanned & UTC timestamp
"""

import os, sys, base64, logging, math, sqlite3
from datetime import timezone, datetime
from pathlib   import Path
from typing    import Dict, List, Any, Tuple, Set

from algosdk.v2client import algod
from algosdk.encoding import encode_address
from algosdk.logic    import get_application_address


# ─── Constants ───────────────────────────────────────────────────────────
TASK_ID           = 2
SECONDS_PER_ROUND = 2.8

ALGOD_ADDRESS     = "http://localhost:8080"
ALGOD_TOKEN       = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

DB_PATH  = os.getenv("VALAR_DB",  str(Path.home() / "ve2fet/valar_database/valar.db"))

LOG_DIR  = os.getenv("VALAR_LOG", str(Path.home() / "ve2fet/dev"))
LOG_PATH = str(Path(LOG_DIR).expanduser() / "scan_delegators.log")

# ─── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("sc_del1")

# ─── E-mail helper ───────────────────────────────────────────────────────
def send_alert_email(subject: str, body: str, to_email: str = None) -> None:
    if to_email is None:
        to_email = "algo99uptime@yahoo.com"
    host = os.uname().nodename.upper()
    subj = f"[{host}] Valar: {subject}"
    body_esc = body.replace('"', r"\"")
    cmd = f"""~/bin/sendmail.sh "{to_email}" "{subj}" "$(printf '{body_esc}')" """
    os.system(cmd)
    log.info("e-mail sent: %s", subj)


# ─── Helpers to decode on-chain blobs ────────────────────────────────────
def _u64(b: bytes, ofs: int = 0) -> int:
    return int.from_bytes(b[ofs : ofs + 8], "big")

def decode_uint64_list(b: bytes) -> List[int]:
    return [_u64(b, i) for i in range(0, len(b), 8) if i + 8 <= len(b)]

def decode_G(buf: bytes) -> Dict[str, int]:
    return {
        "commission_ppm"  : _u64(buf,  0),
        "fee_round_milli" : _u64(buf,  8),
        "fee_setup"       : _u64(buf, 16),
        "fee_asset_id"    : _u64(buf, 24),
    }

def decode_B(buf: bytes) -> Dict[str, int]:
    return { "stake_max": _u64(buf, 0) }

def decode_del_state(gs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    rawG = rawB = b""
    for entry in gs:
        key = base64.b64decode(entry["key"]).decode()
        val = entry["value"]
        if val["type"] == 2:
            out[key] = val["uint"]
        else:
            b = base64.b64decode(val["bytes"])
            if len(b) == 32 and key in ("del_beneficiary","del_manager"):
                try:    out[key] = encode_address(b)
                except: out[key] = b.hex()
            elif key in ("G","B"):
                if   key == "G": rawG = b
                elif key == "B": rawB = b
            elif key == "state":
                out["state"] = b[0]
            else:
                out[key] = b.hex()
    # pull wanted pieces from G / B
    if rawG: out.update(decode_G(rawG))
    if rawB: out.update(decode_B(rawB))
    return out


# ─── DB helpers ──────────────────────────────────────────────────────────
def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def ensure_currency(conn: sqlite3.Connection, client: algod.AlgodClient, asset_id: int):
    cur = conn.execute("SELECT 1 FROM currencies WHERE asset_id=?", (asset_id,))
    if cur.fetchone():
        return

    if asset_id == 0:
        conn.execute("INSERT OR IGNORE INTO currencies(asset_id,symbol,decimals) "
                     "VALUES (0,'ALGO',6)")
        conn.commit()
        return
    try:
        params = client.asset_info(asset_id)["params"]
        symbol = params.get("unit-name", f"ASA{asset_id}")
        dec    = params["decimals"]
    except Exception:
        symbol, dec = f"ASA{asset_id}", 0
    conn.execute("INSERT OR IGNORE INTO currencies(asset_id,symbol,decimals) "
                 "VALUES (?,?,?)", (asset_id, symbol, dec))
    conn.commit()

# ─── Main scan routine ───────────────────────────────────────────────────
def main() -> None:
    log.info("=== scan start ===")
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    this_round = client.status()["last-round"]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA busy_timeout = 10000")

    # ------------------------------------------------------------------ meta
    meta = conn.execute(
        "SELECT last_scanned_round FROM sys_meta WHERE task_id=?", (TASK_ID,)
    ).fetchone()
    first_run = meta is None or meta["last_scanned_round"] == 0

    # ------------------------------------------------------------------ validator-ad list in DB
    val_rows = conn.execute("SELECT ad_id,val_owner FROM validator_ads").fetchall()
    val_owner_by_id = {row["ad_id"]: row["val_owner"] for row in val_rows}

    # ------------------------------------------------------------------ discover ALL live delegator IDs
    current_del_ids: Set[int] = set()
    del_id_to_validator: Dict[int, int] = {}

    for row in val_rows:
        try:
            gs = client.application_info(row["ad_id"])["params"].get("global-state", [])
        except Exception as e:
            log.warning("skip validator %s: %s", row["ad_id"], e)
            continue

        ad_state = {}
        for entry in gs:
            k = base64.b64decode(entry["key"]).decode()
            if k == "del_app_list":
                ad_state["del_app_list"] = decode_uint64_list(
                    base64.b64decode(entry["value"]["bytes"])
                )
        for did in ad_state.get("del_app_list", []):
            if did:
                current_del_ids.add(did)
                del_id_to_validator[did] = row["ad_id"]

    # ------------------------------------------------------------------ iterate delegators
    alerts: List[str] = []

    for did in current_del_ids:
        try:
            gs = client.application_info(did)["params"].get("global-state", [])

        except Exception as e:
            log.warning("skip delegator %s: %s", did, e)
            continue

        d  = decode_del_state(gs)

        # currency row
        asset_id = d.get("fee_asset_id", 0)
        ensure_currency(conn, client, asset_id)

        # monthly operational fee (base-unit/month) for alert
        rounds_pm = int((30*24*3600)/SECONDS_PER_ROUND)
        fee_month_raw = math.ceil(d["fee_round_milli"] * rounds_pm / 1000)

        row = {
            "del_id"             : did,
            "validator_ad_app_id": del_id_to_validator.get(did),
            "del_beneficiary"    : d.get("del_beneficiary"),
            "del_manager"        : d.get("del_manager"),
            "state"              : d.get("state"),
            "cnt_breach_del"     : d.get("cnt_breach_del"),
            "round_start"        : d.get("round_start"),
            "round_end"          : d.get("round_end"),
            "commission_ppm"     : d.get("commission_ppm"),
            "fee_round_milli"    : d.get("fee_round_milli"),
            "fee_setup"          : d.get("fee_setup"),
            "fee_asset_id"       : asset_id,
            "stake_max"          : d.get("stake_max"),
            "created_at_round"   : d.get("round_start"),
            "updated_at_round"   : this_round,
        }

        old = conn.execute(
            "SELECT * FROM delegator_contracts WHERE del_id=?", (did,)
        ).fetchone()

        if old is None:
            # -------- NEW delegator contract
            conn.execute(
                f"INSERT INTO delegator_contracts ({','.join(row.keys())}) "
                f"VALUES ({','.join('?'*len(row))})",
                tuple(row.values()),
            )
            conn.commit()
            if not first_run:
                owner_addr = val_owner_by_id.get(row["validator_ad_app_id"])
                stake_algo = row["stake_max"] / 1_000_000 if row["stake_max"] else 0
                op_fee     = fee_month_raw / 1_000_000  # asset has 6 dec when ALGO/USDC
                alerts.append(
                    f"NEW Delegator {did}\n"
                    f" • Beneficiary : {row['del_beneficiary']}\n"
                    f" • Validator   : {row['validator_ad_app_id']}  (owner {owner_addr})\n"
                    f" • Stake max   : {stake_algo:,.0f} ALGO\n"
                    f" • Oper. fee   : {op_fee:,.2f} /month "
                    f"(asset id {asset_id})"
                )
        else:
            # -------- existing row → just refresh “state” & updated_at_round
            if old["state"] != row["state"]:
                conn.execute(
                    "UPDATE delegator_contracts SET state=?,updated_at_round=? "
                    "WHERE del_id=?",
                    (row["state"], this_round, did),
                )
           # else:
           #     conn.execute(
           #         "UPDATE delegator_contracts SET updated_at_round=? WHERE del_id=?",
           #         (this_round, did),
           #     )
        conn.commit()

    # ------------------------------------------------------------------ mark contracts that disappeared
    db_ids   = {r["del_id"] for r in conn.execute("SELECT del_id FROM delegator_contracts")}
    vanished = db_ids - current_del_ids

    vanish_alerts: list[str] = []

    for x in vanished:
        # fetch the row before deleting so its data can be e-mailed
        row = conn.execute(
            "SELECT * FROM delegator_contracts WHERE del_id=?", (x,)
        ).fetchone()

        if row and not first_run:
            rounds_pm     = int((30 * 24 * 3600) / SECONDS_PER_ROUND)
            fee_month_raw = math.ceil(row["fee_round_milli"] * rounds_pm / 1000)
            op_fee        = fee_month_raw / 1_000_000          # 6-dec assets
            stake_algo    = row["stake_max"] / 1_000_000 if row["stake_max"] else 0
            owner_addr    = val_owner_by_id.get(row["validator_ad_app_id"])

            vanish_alerts.append(
                f"REMOVED Delegator {x}\n"
                f" • Beneficiary : {row['del_beneficiary']}\n"
                f" • Validator   : {row['validator_ad_app_id']}  (owner {owner_addr})\n"
                f" • Stake max   : {stake_algo:,.0f} ALGO\n"
                f" • Oper. fee   : {op_fee:,.2f} /month "
                f"(asset id {row['fee_asset_id']})"
            )

        # now delete the row locally
        conn.execute("DELETE FROM delegator_contracts WHERE del_id=?", (x,))
        # delete, if any, related APY stats row
        conn.execute("DELETE FROM delegator_contract_stats WHERE del_id=?", (x,)) 
        conn.commit()
        log.info("delegator %s vanished – row deleted", x)


    # include the removal notices in the normal alert batch
    alerts.extend(vanish_alerts)

    # ------------------------------------------------------------------ sys_meta
    conn.execute(
        """
        INSERT INTO sys_meta(task_id,last_scanned_round,last_checked_at)
        VALUES (?,?,datetime('now'))
        ON CONFLICT(task_id)
        DO UPDATE SET last_scanned_round=excluded.last_scanned_round,
                      last_checked_at   =excluded.last_checked_at
        """,
        (TASK_ID, this_round),
    )
    conn.commit()
    conn.close()

    # ------------------------------------------------------------------ alerts
    if alerts and not first_run:
        send_alert_email("DELEGATOR-WATCHER", "\n\n".join(alerts))

    log.info("scan complete – %d active, %d vanished, %d alerts",
             len(current_del_ids), len(vanished), len(alerts))


# ─── entry-point ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("fatal error: %s", e)
        sys.exit(1)
