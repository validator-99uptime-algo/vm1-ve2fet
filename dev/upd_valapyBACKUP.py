#!/usr/bin/env python3
import os, sys, sqlite3, logging, traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
from time import perf_counter
import requests

# ─── CONFIG ──────────────────────────────────────────────────────────────
REWARD_SENDER_ADDR = "Y76M3MSY6DKBRHBL7C3NNDXGS5IIMQVQVUAB6MP4XEMMGVF2QWNPL226CA"
DB_PATH = "/home/ve2pcq/ve2fet/valar_database/valar.db"
INDEXER_URL = "https://mainnet-idx.4160.nodely.dev"
ALGOD_ADDRESS = "http://localhost:8080"
ALGOD_TOKEN = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
μALGO = 1_000_000
DAYS_7 = 7

LOG_DIR = Path.home() / "ve2fet/dev"
LOG_PATH = LOG_DIR / "upd_valapy.log"

# LOG_DIR = Path(os.getenv("VALAR_LOG", str(Path.home() / "ve2fet/dev"))).expanduser()
# LOG_PATH = LOG_DIR / "upd_valapy.log"

# ─── LOGGING SETUP ───────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("upd_valapy")

# ─── EMAIL ALERTS ────────────────────────────────────────────────────────
def send_alert_email(subject: str, body: str, to_email: str = "algo99uptime@yahoo.com") -> None:
    host = os.uname().nodename.upper()
    subj = f"[{host}] Valar: {subject}"
    body_esc = body.replace('%', '%%').replace('"', r'\"')
    os.system(f'~/bin/sendmail.sh "{to_email}" "{subj}" "$(printf \'{body_esc}\')"')
    log.info("e-mail sent: %s", subj)

# ─── BLOCKCHAIN HELPERS ─────────────────────────────────────────────────
def get_local_account_balance(address):
    headers = {"X-Algo-API-Token": ALGOD_TOKEN}
    try:
        resp = requests.get(f"{ALGOD_ADDRESS}/v2/accounts/{address}", headers=headers, timeout=6)
        data = resp.json()
        amount = data.get("amount", 0)
        min_balance = data.get("min-balance", 0)
        return (amount - min_balance) / μALGO  # ALGO
    except Exception as e:
        raise RuntimeError(f"Local node unreachable for {address}: {e}")

def get_reward_payments(address, after_time, session):
    txs = []
    next_token = ""
    done = False
    while not done:
        params = {
            "address": address,
            "tx-type": "pay",
            "limit": 1000
        }
        if next_token:
            params["next"] = next_token
        try:
            resp = session.get(f"{INDEXER_URL}/v2/accounts/{address}/transactions", params=params, timeout=12)
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Indexer unreachable for {address}: {e}")
        results = data.get("transactions", [])
        if not results:
            break
        for tx in results:
            if tx.get("sender") == REWARD_SENDER_ADDR and "round-time" in tx:
                tx_time = tx["round-time"]
                if tx_time >= int(after_time.timestamp()):
                    txs.append(tx)
                else:
                    done = True
                    break
        next_token = data.get("next-token", "")
        if not next_token or done:
            break
    return txs

def get_reward_payments_since_round(address, from_round, session):
    txs = []
    next_token = ""
    done = False
    while not done:
        params = {
            "address": address,
            "tx-type": "pay",
            "min-round": from_round,
            "limit": 1000
        }
        if next_token:
            params["next"] = next_token
        try:
            resp = session.get(f"{INDEXER_URL}/v2/accounts/{address}/transactions", params=params, timeout=12)
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Indexer unreachable for {address}: {e}")
        results = data.get("transactions", [])
        if not results:
            break
        for tx in results:
            if tx.get("sender") == REWARD_SENDER_ADDR and "round-time" in tx:
                txs.append(tx)
        next_token = data.get("next-token", "")
        if not next_token or done:
            break
    return txs

# ─── MAIN ───────────────────────────────────────────────────────────────
def main():
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    t0 = perf_counter()
    log.info(f"--- upd_valapy.py START {start_time} ---")

    count = 0
    error_count = 0
    now = datetime.now(timezone.utc)
    after_time_7d = now - timedelta(days=DAYS_7)

    with sqlite3.connect(DB_PATH) as conn, requests.Session() as session:
        conn.row_factory = sqlite3.Row
        # --- get current round from sys_meta (for filtering) ---

        headers = {"X-Algo-API-Token": ALGOD_TOKEN}
        status = requests.get(f"{ALGOD_ADDRESS}/v2/status", headers=headers, timeout=10).json()
        current_round = status.get("last-round", 0)

        # cur_round_row = conn.execute("SELECT last_scanned_round FROM sys_meta WHERE task_id=1").fetchone()
        # current_round = cur_round_row[0] if cur_round_row else 0

        # --- get latest blockchain round from local node (for correct APY_total) ---
        headers = {"X-Algo-API-Token": ALGOD_TOKEN}
        status = requests.get(f"{ALGOD_ADDRESS}/v2/status", headers=headers, timeout=10).json()
        latest_round = status.get("last-round", 0)

        # --- filter live & unexpired delegators only ---
        cur = conn.execute(
            "SELECT del_id, del_beneficiary, created_at_round FROM delegator_contracts WHERE state = 5 AND round_end >= ?",
            (current_round,)
        )
        rows = cur.fetchall()
        for row in rows:
            del_id = row["del_id"]
            addr = row["del_beneficiary"]
            created_at_round = row["created_at_round"]
            try:
                staked = get_local_account_balance(addr)
                if staked < 30000:
                    continue

                txs_7d = get_reward_payments(addr, after_time_7d, session)
                paid_7d = sum(tx.get("payment-transaction", {}).get("amount", 0) for tx in txs_7d) / μALGO
                txs_total = get_reward_payments_since_round(addr, created_at_round, session)
                paid_total = sum(tx.get("payment-transaction", {}).get("amount", 0) for tx in txs_total) / μALGO
                apy_7d = (paid_7d / staked) * (365 / DAYS_7) * 100 if staked else 0

                # --- FIX: use latest_round for APY_total ---
                rounds_since_creation = latest_round - created_at_round
                days_total = (rounds_since_creation * 2.8) / (60 * 60 * 24) if rounds_since_creation else 0
                apy_total = (paid_total / staked) * (365 / days_total) * 100 if staked and days_total else 0

                updated_at = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO delegator_contract_stats
                      (del_id, paid_last_7d, paid_total, apy_7d, apy_total, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(del_id) DO UPDATE SET
                      paid_last_7d = excluded.paid_last_7d,
                      paid_total   = excluded.paid_total,
                      apy_7d       = excluded.apy_7d,
                      apy_total    = excluded.apy_total,
                      updated_at   = excluded.updated_at
                    """,
                    (del_id, paid_7d, paid_total, apy_7d, apy_total, updated_at)
                )
                count += 1
            except Exception as e:
                msg = f"Error for del_id={del_id} {addr[:8]}...: {e}"
                log.error(msg)
                log.error(traceback.format_exc())
                error_count += 1
                try:
                    send_alert_email("upd_valapy.py ERROR", f"{msg}\n\n{traceback.format_exc()}")
                except Exception as email_err:
                    log.error(f"Failed to send error email: {email_err}")

        conn.commit()

    elapsed = perf_counter() - t0
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    log.info(f"--- upd_valapy.py END {end_time} ---")
    log.info(f"Total delegators processed: {count}")
    log.info(f"Errors: {error_count}")
    log.info(f"Total execution time: {elapsed:.3f} seconds")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception(f"FATAL ERROR: {e}")
        try:
            send_alert_email("upd_valapy.py FATAL ERROR", f"{e}\n\n{traceback.format_exc()}")
        except Exception as email_err:
            log.error(f"Failed to send fatal error email: {email_err}")
        sys.exit(1)
