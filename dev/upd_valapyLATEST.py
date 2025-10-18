#!/usr/bin/env python3
import os, sys, sqlite3, logging, traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
from time import perf_counter
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

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
def get_local_account_balance(address, session):
    headers = {"X-Algo-API-Token": ALGOD_TOKEN}
    resp = session.get(f"{ALGOD_ADDRESS}/v2/accounts/{address}", headers=headers, timeout=6)
    data = resp.json()
    amount = data.get("amount", 0)
    min_balance = data.get("min-balance", 0)
    return (amount - min_balance) / μALGO

def get_reward_payments(address, after_time, session, created_at_round):
    txs, next_token, done = [], "", False
    while not done:
        params = {"address": address, "tx-type": "pay", "limit": 1000}
        if next_token:
            params["next"] = next_token
        resp = session.get(f"{INDEXER_URL}/v2/accounts/{address}/transactions", params=params, timeout=12)
        try:
            data = resp.json()
        except requests.exceptions.JSONDecodeError:
            log.error(f"Invalid JSON response for get_reward_payments: {resp.text}")
            return txs
        results = data.get("transactions", [])
        if not results:
            break

        for tx in results:
            if (
                tx.get("sender") == REWARD_SENDER_ADDR
                and "round-time" in tx
                and tx.get("confirmed-round", 0) >= created_at_round
            ):
                tx_time = tx.get("round-time", 0)
                if tx_time >= int(after_time.timestamp()):
                    txs.append(tx)
                else:
                    done = True
                    break

        next_token = data.get("next-token", "")
        if not next_token:
            break
    return txs

def get_reward_payments_since_round(address, from_round, session):
    txs, next_token = [], ""
    while True:
        params = {"address": address, "tx-type": "pay", "min-round": from_round, "limit": 1000, "next": next_token}
        resp = session.get(f"{INDEXER_URL}/v2/accounts/{address}/transactions", params=params, timeout=12)
        try:
            data = resp.json()
        except requests.exceptions.JSONDecodeError:
            log.error(f"Invalid JSON response for get_reward_payments_since_round: {resp.text}")
            return txs
        results = data.get("transactions", [])
        txs.extend([tx for tx in results if tx.get("sender") == REWARD_SENDER_ADDR])
        next_token = data.get("next-token", "")
        if not next_token or not results:
            break
    return txs

def process_delegator(row, after_time_7d, latest_round, session):
    del_id, addr, created_at_round = row["del_id"], row["del_beneficiary"], row["created_at_round"]
    staked = get_local_account_balance(addr, session)
    if staked < 30000:
        return None

    created_at_datetime = datetime.now(timezone.utc) - timedelta(seconds=(latest_round - created_at_round) * 2.8)
    paid_7d = sum(tx.get("payment-transaction", {}).get("amount", 0) for tx in get_reward_payments(addr, after_time_7d, session, created_at_round)) / μALGO
    paid_total = sum(tx.get("payment-transaction", {}).get("amount", 0) for tx in get_reward_payments_since_round(addr, created_at_round, session)) / μALGO

    first_tx_time = max(after_time_7d, created_at_datetime)

    days_active = (datetime.now(timezone.utc) - max(after_time_7d, created_at_datetime)).total_seconds() / 86400

    apy_7d = (paid_7d / staked) * (365 / days_active) * 100 if staked and days_active > 0 else 0

    days_total = ((latest_round - created_at_round) * 2.8) / (86400)
    apy_total = (paid_total / staked) * (365 / days_total) * 100 if staked and days_total else 0

    return del_id, paid_7d, paid_total, apy_7d, apy_total

# ─── MAIN ───────────────────────────────────────────────────────────────
def main():
    t0 = perf_counter()
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    log.info(f"--- upd_valapy.py START {start_time} ---")

    with sqlite3.connect(DB_PATH) as conn, requests.Session() as session:
        conn.row_factory = sqlite3.Row
        current_round = session.get(f"{ALGOD_ADDRESS}/v2/status", headers={"X-Algo-API-Token": ALGOD_TOKEN}, timeout=10).json().get("last-round", 0)
        latest_round = current_round
        after_time_7d = datetime.now(timezone.utc) - timedelta(days=DAYS_7)

        rows = conn.execute("SELECT del_id, del_beneficiary, created_at_round FROM delegator_contracts WHERE state=5 AND round_end>=?", (current_round,)).fetchall()

        count, error_count = 0, 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(process_delegator, row, after_time_7d, latest_round, session) for row in rows]

            for future in as_completed(futures):
                result = future.result()
                if result:
                    conn.execute("""INSERT INTO delegator_contract_stats (del_id, paid_last_7d, paid_total, apy_7d, apy_total, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(del_id) DO UPDATE SET paid_last_7d=excluded.paid_last_7d, paid_total=excluded.paid_total,
                    apy_7d=excluded.apy_7d, apy_total=excluded.apy_total, updated_at=excluded.updated_at""", (*result, datetime.now(timezone.utc).isoformat()))
                    count += 1
        conn.commit()

    elapsed = perf_counter() - t0
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    log.info(f"--- upd_valapy.py END {end_time} ---")
    log.info(f"Total delegators processed: {count}")
    log.info(f"Errors: {error_count}")
    log.info(f"Total execution time: {elapsed:.3f} seconds")

if __name__ == "__main__":
    main()
