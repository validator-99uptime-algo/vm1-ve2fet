#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valar_winners.py - show both cheapest and runner-up at each stake
================================================================
For every 20 k ALGO checkpoint between 30 k and 2.59 M ALGO the script
prints two lines:

1. Winner line     - the cheapest READY ALGO ad that still has room.
2. Runner-up line  - who would win if that ad did not exist (second
   cheapest after applying the same filters).

Columns are identical so you can immediately compare the fees and see
how much you could raise before losing the spot.

Revision 2025-06-10 a  - runner‑up added, gratis aware, slots filter,
ASCII-only output.

Usage examples
~~~~~~~~~~~~~~
    python valar_winners.py              # default 30‑day horizon
    python valar_winners.py --days 60    # other horizons

The script is read-only – it never writes to the SQLite DB.
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from typing import List

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------
DB_PATH = os.path.expanduser("~/ve2fet/valar_database/valar.db")
OWNER_ADDR      = "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA"
# BLACKLIST_ADDRS = {"CSKHMIBF7E4SWV7FLIKO732EIK7U4VP2S3TXYJGMVK2IVM7MH2H5Z7L7H4"}

BLACKLIST_ADDRS = {
    "CSKHMIBF7E4SWV7FLIKO732EIK7U4VP2S3TXYJGMVK2IVM7MH2H5Z7L7H4",
    "NR4SKWFO7GUZNTQULOIYGZ4GMXXIPL3NAYKYO5IYE2EAYSNE6DUVWV2CTI",
}

MICRO = 1_000_000
ONE_IN_PPM = 1_000_000
SECONDS_PER_ROUND = 2.8
ROUNDS_PM = int(30 * 24 * 3600 / SECONDS_PER_ROUND)  # about 926 k rounds per 30 d
RED    = "\033[1;31m"   # bright-red
YELLOW = "\033[1;33m"   # bright-yellow
RESET  = "\033[0m"


# stake checkpoints ----------------------------------------------------
CHECKPOINTS: List[int] = list(range(30_000, 22_600_001, 10_000))

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Cheapest and runner-up ads")
parser.add_argument("--days", type=int, default=30, choices=[30, 60, 90, 119],
                    help="Contract duration in days (default 30)")
args = parser.parse_args()
MONTH_FACTOR = args.days / 30.0

# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------

def load_ads() -> pd.DataFrame:
    """Fetch READY ALGO ads and decode fee fields."""
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT ad_id, val_owner, val_manager,
               fee_setup, fee_round_min, fee_round_var,
               stake_max, gratis_stake_ppm,
               cnt_del, cnt_del_max
        FROM   validator_ads
        WHERE  state        = '05'   -- READY
          AND  fee_asset_id = 0      -- ALGO fees only
    """
    df = pd.read_sql(query, conn)

    # units ------------------------------------------------------------
    df["stake_max"] = df["stake_max"].astype(float) / MICRO  # micro ALGO -> ALGO
    df.loc[df["stake_max"] == 0, "stake_max"] = 60_000_000  # 0 means unlimited cap
    df["gratis_frac"] = df["gratis_stake_ppm"].astype(float) / ONE_IN_PPM

    # decoded monthly fees (ALGO) -------------------------------------
    df["setup"] = df["fee_setup"] / MICRO
    df["beta"] = np.ceil(df["fee_round_min"] * ROUNDS_PM / 1000) / MICRO
    df["gamma"] = np.ceil(df["fee_round_var"] * ROUNDS_PM / 10000) / MICRO

    # flags ------------------------------------------------------------
    df["mine"] = df["val_owner"] == OWNER_ADDR
    df["slots"] = df["cnt_del_max"] - df["cnt_del"]  # 0 means full

    # ——— drop ads whose *owner* is on the blacklist ———
    df = df[~df["val_owner"].isin(BLACKLIST_ADDRS)]

    return df[[
        "ad_id", "mine", "setup", "beta", "gamma",
        "stake_max", "gratis_frac", "slots", "val_manager"
    ]]


def effective_stake(stake: float, gratis_frac: float) -> float:
    """Billable stake after gratis adjustment."""
    return stake / (1.0 + gratis_frac)


def total_price(row: pd.Series, stake: int) -> float:
    """Total contract price (ALGO) for this ad at *stake*."""
    adj = effective_stake(stake, row.gratis_frac)
    monthly = max(row.beta, row.gamma * adj / 100_000.0)
    return row.setup + monthly * MONTH_FACTOR

# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def main() -> None:
    df = load_ads()

    print(f"\nCheapest ads for {args.days}-day contracts (winner + runner-up)")
    print("-" * 102)
    header = (
        "Stake    Rank Ad-ID    Mine?   Price   setup  min    /100k   gratis%  Slots Manager"
    )
    print(header)
    print("-" * len(header))

    for stake in CHECKPOINTS:
        # exclude full ads and those whose max stake is too low after gratis
        elig = df[(df.slots > 0) &
                   df.apply(lambda r: effective_stake(stake, r.gratis_frac) <= r.stake_max, axis=1)]
        if elig.empty:
            print(f"{stake // 1000:5d} k   --   --")
            continue

        costs = elig.apply(lambda r: total_price(r, stake), axis=1)
        best_two = costs.nsmallest(2)

        for rank, idx in enumerate(best_two.index, start=1):
            row = elig.loc[idx]
            mark = "Y" if row.mine else "N"
            label = "1st" if rank == 1 else "2nd"
            stake_col = f"{stake // 1000:5d} k" if rank == 1 else " " * 7  # indent second line

            color = (
                ""                          # leave winner line white if it’s yours
                if row.mine
                else (RED if rank == 1 else YELLOW)
            )
            print(
                f"{color}"
                f"{stake_col}  {label}  {int(row.ad_id):7d}   {mark}  {best_two[idx]:6.2f}  "
                f"{row.setup:5.2f}  {row.beta:5.2f}  {row.gamma:6.2f}   "
                f"{row.gratis_frac * 100:6.1f}  {row.slots:5d}  {row.val_manager[:8]}..."
                f"{RESET}"
            )
            if rank == 2:          # add a blank line **only** after the runner-up
                print()

if __name__ == "__main__":
    main()
