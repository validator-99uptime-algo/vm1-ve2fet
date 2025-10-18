#!/usr/bin/env python3
"""
DB_beneficiary_overview.py  –  delegator-beneficiaries at a glance

Columns
-------
beneficiary | state | ALGO balance | op-fee/mo | expiry (UTC) | days | del_id

* ALGO balance: live on-chain µALGO → ALGO, 2-decimals.
* op-fee/mo   : monthly fee (ALGO or USDC) + suffix “A” / “US”.
* expiry/date : from round_end → UTC (assumes 2.8 s/round).

Totals
------
prints grand totals for ALGO balance, fees (ALGO & USDC) and row count.

Environment
-----------
VALAR_DB   – sqlite path (default ~/ve2fet/valar_database/valar.db)
ALGOD node – edit ALGOD_ADDRESS / ALGOD_TOKEN below if needed.
"""

import os, sqlite3, math, datetime
from pathlib import Path
from algosdk.v2client import algod

# ─── constants ───────────────────────────────────────────────────────────
DB               = os.getenv("VALAR_DB",
                              str(Path.home() / "ve2fet/valar_database/valar.db"))
ALGOD_ADDRESS    = "http://localhost:8080"
ALGOD_TOKEN      = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
SECONDS_PER_ROUND = 2.8
USDC_ID          = 31566704            # change if your USDC ASA differs
µ                = 1_000_000           # µ-units → base units (6 decimals)

# ─── open DB & fetch data ────────────────────────────────────────────────
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# 1) delegator states code → label
state_map = {r["code"]: r["label"]
             for r in conn.execute("SELECT code,label FROM delegator_states")}

# 2) delegator contracts joined to validator_ads (for manager look-up if needed)
dels = conn.execute("""
    SELECT del_id, del_beneficiary, state, round_end,
           fee_round_milli, fee_asset_id
    FROM   delegator_contracts
""").fetchall()
conn.close()

# ─── prepare Algod client ────────────────────────────────────────────────
algo = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

def algo_balance(addr: str) -> float:
    """Return ALGO balance (base-units) for address (excludes min-balance)."""
    try:
        info = algo.account_info(addr)
        return (info["amount"] - info["min-balance"]) / µ
    except Exception:
        return 0.0

def round_to_utc(round_no: int) -> datetime.datetime:
    now      = datetime.datetime.now(datetime.timezone.utc)
    status   = algo.status()
    delta_r  = round_no - status["last-round"]
    return now + datetime.timedelta(seconds=delta_r * SECONDS_PER_ROUND)

# ─── compute / enrich rows ───────────────────────────────────────────────
rows = []
rounds_pm = int((30*24*3600)/SECONDS_PER_ROUND)

for r in dels:
    addr     = r["del_beneficiary"]
    state_tx = state_map.get(r["state"], f"0x{r['state']:02x}")
    bal_A    = algo_balance(addr)

    # monthly fee
    fee_raw  = math.ceil(r["fee_round_milli"] * rounds_pm / 1000)   # µ-units
    if r["fee_asset_id"] == 0:                # ALGO
        fee_val = fee_raw / µ
        fee_str = f"{fee_val:,.2f}A"
    elif r["fee_asset_id"] == USDC_ID:        # USDC
        fee_val = fee_raw / µ
        fee_str = f"{fee_val:,.2f}US"
    else:                                     # other ASA – show raw
        fee_val = 0
        fee_str = "-"

    # expiry / days left
    exp_dt   = round_to_utc(r["round_end"])
    days_left= (exp_dt - datetime.datetime.now(datetime.timezone.utc)).days

    rows.append({
        "addr":      addr,
        "state":     state_tx,
        "bal_A":     bal_A,
        "fee_str":   fee_str,
        "fee_val":   fee_val if r["fee_asset_id"]==0 else 0.0,
        "fee_val_us":fee_val if r["fee_asset_id"]==USDC_ID else 0.0,
        "expiry":    exp_dt.strftime("%Y-%m-%d %H:%M"),
        "days":      days_left,
        "del_id":    r["del_id"],
    })

# sort by ALGO balance desc
rows.sort(key=lambda x: x["bal_A"], reverse=True)

# ─── print table ─────────────────────────────────────────────────────────
hdr = ("beneficiary".ljust(58) +
       " | state | ALGO balance | op-fee/mo | expiry (UTC)       | days | del_id")
print(hdr)
print("-" * len(hdr))

tot_bal    = tot_fee_A = tot_fee_US = 0.0

for row in rows:
    print(f"{row['addr']} | "
          f"{row['state']:<5} | "
          f"{row['bal_A']:12,.2f} | "
          f"{row['fee_str']:9} | "
          f"{row['expiry']} | "
          f"{row['days']:4d} | "
          f"{row['del_id']}")
    tot_bal    += row["bal_A"]
    tot_fee_A  += row["fee_val"]
    tot_fee_US += row["fee_val_us"]

print("-" * len(hdr))
print(f"{'TOTAL'.ljust(58)} |       | "
      f"{tot_bal:12,.2f} | "
      f"{tot_fee_A:,.2f}A / {tot_fee_US:,.2f}US | "
      f"                  |      | {len(rows)} rows")
print("Done.")
