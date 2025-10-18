#!/usr/bin/env python3
import sqlite3
import requests
from datetime import datetime, timedelta, timezone

# ---- CONFIG ----
REWARD_SENDER_ADDR = "Y76M3MSY6DKBRHBL7C3NNDXGS5IIMQVQVUAB6MP4XEMMGVF2QWNPL226CA"
BENEFICIARY_ADDR = "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA"
DEL_ID = 3157018256
DB_PATH = "/home/ve2pcq/ve2fet/valar_database/valar.db"
INDEXER_URL = "https://mainnet-idx.4160.nodely.dev"

def get_created_at_round(del_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT created_at_round FROM delegator_contracts WHERE del_id = ?", (del_id,)).fetchone()
        if row:
            return row["created_at_round"]
        else:
            raise Exception("del_id not found")


def get_reward_payments(address, after_time):
    txs, next_token, done = [], "", False
    while not done:
        params = {
            "address": address,
            "tx-type": "pay",
            "limit": 1000,
            "min-time": int(after_time.timestamp())
        }

        if next_token:
            params["next"] = next_token
        resp = requests.get(f"{INDEXER_URL}/v2/accounts/{address}/transactions", params=params, timeout=12)
        try:
            data = resp.json()
        except Exception as e:
            print(f"Invalid JSON response for get_reward_payments: {resp.text}")
            break
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

def get_reward_payments_since_round(address, from_round):
    txs, next_token, done = [], "", False
    while not done:
        params = {"address": address, "tx-type": "pay", "min-round": from_round, "limit": 1000}
        if next_token:
            params["next"] = next_token
        resp = requests.get(f"{INDEXER_URL}/v2/accounts/{address}/transactions", params=params, timeout=12)
        try:
            data = resp.json()
        except Exception as e:
            print(f"Invalid JSON response for get_reward_payments_since_round: {resp.text}")
            break
        results = data.get("transactions", [])
        if not results:
            break
        for tx in results:
            if tx.get("sender") == REWARD_SENDER_ADDR and "round-time" in tx:
                txs.append(tx)
        next_token = data.get("next-token", "")
        if not next_token or not results:
            break
    return txs

if __name__ == "__main__":
    created_at_round = get_created_at_round(DEL_ID)
    print(f"del_id: {DEL_ID} -> created_at_round: {created_at_round}")

    now = datetime.now(timezone.utc)
    after_time_7d = now - timedelta(days=7)

    print(f"Testing for beneficiary: {BENEFICIARY_ADDR}")

    txs_7d = get_reward_payments(BENEFICIARY_ADDR, after_time_7d)
    txs_total = get_reward_payments_since_round(BENEFICIARY_ADDR, created_at_round)

    print(f"\nTransactions in last 7 days (count): {len(txs_7d)}")
    for tx in txs_7d:
        print(f"  7d txid: {tx.get('id','?')}, round: {tx.get('confirmed-round','?')}, time: {tx.get('round-time','?')}")

    print(f"\nTransactions since contract creation (count): {len(txs_total)}")
    for tx in txs_total:
        print(f"  total txid: {tx.get('id','?')}, round: {tx.get('confirmed-round','?')}, time: {tx.get('round-time','?')}")
