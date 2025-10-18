#!/usr/bin/env python3
"""
total_stake_by_validator.py  –  validator managers at a glance

Adds two new columns:
  • ALGO balance  – current on-chain balance of the manager address
  • % stake/bal   – stake-ALGO ÷ balance × 100 (n/a if balance = 0)

Keeps all previous columns and the final TOTAL line.
Sorted (as before) by GRAND TOTAL (stake ALGO + stake USDC, desc).
"""

import os, sqlite3
from pathlib import Path
from collections import defaultdict
from algosdk.v2client import algod

# ─── config ──────────────────────────────────────────────────────────────
DB          = os.getenv("VALAR_DB",
                        str(Path.home() / "ve2fet/valar_database/valar.db"))

ALGOD_ADDR  = "http://localhost:8080"
ALGOD_TOKEN = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

USDC_ID   = 31566704      # adjust if your USDC ASA differs
µALGO     = 1_000_000

# ─── load DB ─────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

ads  = conn.execute("SELECT ad_id, val_manager FROM validator_ads").fetchall()
dels = conn.execute("""
        SELECT d.fee_asset_id, d.stake_max, a.val_manager
        FROM   delegator_contracts AS d
        JOIN   validator_ads       AS a
               ON a.ad_id = d.validator_ad_app_id
""").fetchall()
conn.close()

# ─── aggregate stake figures ─────────────────────────────────────────────
stats = defaultdict(lambda: {
    "ads": 0, "dels": 0,
    "stake_algo": 0, "stake_usdc": 0
})

for ad in ads:
    stats[ad["val_manager"]]["ads"] += 1

for d in dels:
    s = stats[d["val_manager"]]
    s["dels"] += 1
    if   d["fee_asset_id"] == 0:
        s["stake_algo"] += d["stake_max"]
    elif d["fee_asset_id"] == USDC_ID:
        s["stake_usdc"] += d["stake_max"]

# ─── fetch on-chain ALGO balances ────────────────────────────────────────
client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDR)

for mgr in stats:
    try:
        acct = client.account_info(mgr)
        bal  = (acct["amount"] - acct["min-balance"]) / µALGO
    except Exception:
        bal  = 0.0                              # fallback on RPC failure
    stats[mgr]["algo_balance"] = bal

# ─── build rows & sort ───────────────────────────────────────────────────
rows = []
for mgr, s in stats.items():
    stake_A = s["stake_algo"] / µALGO
    stake_U = s["stake_usdc"] / µALGO
    total   = stake_A + stake_U
    bal     = s["algo_balance"]
    ratio   = (stake_A / bal * 100) if bal else None
    rows.append((total, mgr, s["ads"], s["dels"],
                 stake_A, stake_U, bal, ratio))

rows.sort(reverse=True)      # largest GRAND TOTAL first
tot_all_valar = sum(r[0] for r in rows)          # GRAND TOTAL of every manager

# ─── print table ────────────────────────────────────────────────────────
hdr = ("manager".ljust(58) +
       " | ads | dels | stake ALGO | stake USDC | GRAND TOTAL | ALGO balance | % of total")
print(hdr)
print("-" * len(hdr))

tot_ads = tot_dels = tot_A = tot_U = tot_all = tot_bal = 0.0

for total, mgr, n_ads, n_dels, stake_A, stake_U, bal, ratio in rows:
    print(f"{mgr} | "
          f"{n_ads:3d} | "
          f"{n_dels:4d} | "
          f"{stake_A:10,.0f} | "
          f"{stake_U:10,.0f} | "
          f"{total:11,.0f} | "
          f"{bal:12,.0f} | "
          f"{(total / tot_all_valar * 100):9.1f}%")
    tot_ads   += n_ads
    tot_dels  += n_dels
    tot_A     += stake_A
    tot_U     += stake_U
    tot_all   += total
    tot_bal   += bal

print("-" * len(hdr))
print(f"{'TOTAL'.ljust(58)} | "
      f"{int(tot_ads):3d} | "
      f"{int(tot_dels):4d} | "
      f"{tot_A:10,.0f} | "
      f"{tot_U:10,.0f} | "
      f"{tot_all:11,.0f} | "
      f"{tot_bal:12,.0f} | "
      f"{100.0:9.1f}%")
#      f"{(tot_A / tot_bal * 100 if tot_bal else 0):9.1f}%")
print("Done.")
