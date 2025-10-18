import sqlite3
import requests
from datetime import datetime, timedelta, timezone

DB_PATH = "/home/ve2pcq/ve2fet/valar_database/valar.db"
INDEXER_URL = "https://mainnet-idx.4160.nodely.dev"
DAYS_7 = 7

def get_reward_payments(address, after_time):
    txs = []
    next_token = ""
    done = False
    with requests.Session() as session:
        while not done:
            params = {
                "address": address,
                "tx-type": "pay",
                "limit": 1000
            }
            if next_token:
                params["next"] = next_token
            resp = session.get(f"{INDEXER_URL}/v2/accounts/{address}/transactions", params=params)
            data = resp.json()
            results = data.get("transactions", [])
            if not results:
                break
            for tx in results:
                if tx.get("sender") != address and "round-time" in tx:
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

if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    after_time_7d = now - timedelta(days=DAYS_7)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT del_id, del_beneficiary FROM delegator_contracts")
        for row in cur.fetchall():
            del_id = row["del_id"]
            addr = row["del_beneficiary"]
            txs_7d = get_reward_payments(addr, after_time_7d)
            if not any("payment-transaction" in tx for tx in txs_7d):
                print(f"del_id={del_id} beneficiary={addr}")
