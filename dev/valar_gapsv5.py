#!/usr/bin/env python3
"""
valar_gaps.py  –  spot ads that are too cheap (or missing)
=========================================================
Prints, for one contract horizon (30 / 60 / 90 / 119 days):

1. Coverage gaps   – stake ranges where *none* of **your** READY ALGO ads
   is the cheapest offer.
2. Excess margins  – ranges where you *do* win and the gap to the next
   rival is at least EXCESS_MARGIN ALGO.
3. Safe‑raise tips – per winning ad: how far you can raise **Min monthly**
   (flat) *or* **Var / 100k** (slope) while keeping a BUFFER ALGO lead at
   every stake that ad already wins.

**One price sheet covers all contract lengths.**  The --per-month flag
normalises the raise tips to a 30‑day month, so the suggestions are the
*same* whichever horizon you request – just copy them into Valar.

Revision 2025‑06‑08  (ASCII‑only, no fancy dashes)
"""
from __future__ import annotations
import math, os, sqlite3, argparse, itertools
from typing import List, Tuple, Dict

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------
DB_PATH    = os.path.expanduser("~/ve2fet/valar_database/valar.db")
OWNER_ADDR = "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA"
MICRO      = 1_000_000
SECONDS_PER_ROUND = 2.8
ROUNDS_PM         = int(30 * 24 * 3600 / SECONDS_PER_ROUND)   # ~926k
ROUNDS_PER_DAY    = 24 * 3600 / SECONDS_PER_ROUND

# stake grid starts at 30k ALGO ---------------------------------------
STAKE_GRID: List[int] = (
    list(range(30_000, 250_001,   5_000)) +
    list(range(250_000, 1_000_001, 10_000)) +
    list(range(1_000_000, 60_000_001, 1_000_000))
)

EXCESS_MARGIN = 5.0   # ALGO margin considered "too much"
BUFFER        = 0.5   # keep at least this after raising

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
pa = argparse.ArgumentParser(description="Find gaps and safe price raises")
pa.add_argument("--days", type=int, default=30, choices=[30, 60, 90, 119],
                help="Contract duration in days (default 30)")
pa.add_argument("--per-month", action="store_true",
                help="Normalise raise tips to a 30‑day month")
args = pa.parse_args()
HORIZON_DAYS = args.days
MONTH_FACTOR = HORIZON_DAYS / 30.0
NORMALISE    = args.per_month

# ---------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------

def load_ads() -> pd.DataFrame:
    """Return DataFrame with all READY ALGO ads that accept this horizon."""
    conn = sqlite3.connect(DB_PATH)
    q = """
    SELECT ad_id, val_owner,
           fee_setup, fee_round_min, fee_round_var,
           stake_max,
           min_duration_rounds, max_duration_rounds,
           gratis_stake_ppm,
           cnt_del, cnt_del_max
    FROM   validator_ads
    WHERE  state        = '05'           -- READY
      AND  fee_asset_id = 0              -- ALGO denominated
      AND  cnt_del      < cnt_del_max    -- has capacity
    """
    df = pd.read_sql(q, conn)
    if df.empty:
        return df

    # Convert and filter ------------------------------------------------
    df["stake_max"] = df["stake_max"].astype(float) / MICRO
    df.loc[df["stake_max"] == 0, "stake_max"] = 60_000_000  # treat 0 as unlimited

    df["min_days"] = df["min_duration_rounds"] / ROUNDS_PER_DAY
    df["max_days"] = df["max_duration_rounds"].replace({0: math.inf}) / ROUNDS_PER_DAY
    df = df[(df["min_days"] <= HORIZON_DAYS) & (df["max_days"] >= HORIZON_DAYS)]
    if df.empty:
        return df

    # Human‑readable fees (ALGO per 30‑day month) -----------------------
    df["setup"]   = df["fee_setup"] / MICRO
    df["beta"]    = np.ceil(df["fee_round_min"]  * ROUNDS_PM / 1000)  / MICRO
    df["gamma"]   = np.ceil(df["fee_round_var"] * ROUNDS_PM / 10000) / MICRO
    df["gratis"]  = df["gratis_stake_ppm"].astype(float) / 1_000_000
    df["is_mine"] = df["val_owner"] == OWNER_ADDR

    return df[["ad_id","is_mine","setup","beta","gamma","stake_max","gratis"]]

# ---------------------------------------------------------------------
# Price maths
# ---------------------------------------------------------------------

def total_price(setup, beta, gamma, stake: int, gratis: pd.Series) -> pd.Series:
    """Vectorised total contract price (ALGO) for one stake size."""
    billable = np.maximum(0.0, stake * (1.0 - gratis))
    monthly  = np.maximum(beta, gamma * billable / 100_000.0)
    return setup + monthly * MONTH_FACTOR

# ---------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------

def analyse(df: pd.DataFrame):
    gap_rows:    List[Tuple[int,str]] = []
    excess_rows: List[Tuple[int,str]] = []
    ad_stats: Dict[int, Dict[str, float]] = {}

    for stake in STAKE_GRID:
        elig = df[df["stake_max"] >= stake]
        if elig.empty:
            continue

        costs = total_price(elig["setup"], elig["beta"], elig["gamma"],
                            stake, elig["gratis"])
        best_idx   = costs.idxmin()
        best_cost  = float(costs[best_idx])
        best_ad    = int(elig.at[best_idx, "ad_id"])
        best_mine  = bool(elig.at[best_idx, "is_mine"])

        rival_mask = ~elig["is_mine"].values
        rival_cost = float(costs[rival_mask].min()) if rival_mask.any() else math.inf

        if not best_mine:
            gap_rows.append((stake, f"rival {best_ad} wins ({best_cost:.2f} ALGO)"))
        else:
            margin = rival_cost - best_cost
            if margin >= EXCESS_MARGIN - 1e-9:
                excess_rows.append((stake, f"my ad {best_ad} by {margin:.1f} ALGO"))

            s = ad_stats.setdefault(best_ad, {"lo": stake, "hi": stake, "m": margin})
            s["hi"] = stake
            s["m"]  = min(s["m"], margin)

    def compress(rows):
        out = []
        for key, grp in itertools.groupby(rows, key=lambda r: r[1]):
            stakes = [r[0] for r in grp]
            lo, hi = stakes[0]//1000, stakes[-1]//1000
            out.append(f" {lo:>4}{'-'+str(hi) if lo!=hi else ''} k :  {key}")
        return out

    suggestions = []
    for ad, s in ad_stats.items():
        if s["m"] < EXCESS_MARGIN - 1e-9:
            continue
        head = s["m"] - BUFFER
        if head <= 0:
            continue
        lo_k, hi_k = s["lo"]//1000, s["hi"]//1000
        min_raise  = head / MONTH_FACTOR if NORMALISE else head
        var_raise  = head / (s["hi"] / 100_000.0)
        if NORMALISE:
            var_raise /= MONTH_FACTOR
        suggestions.append(
            f"ad {ad} : wins {lo_k}-{hi_k} k  -> raise Min <= {min_raise:6.1f}  or Var <= {var_raise:5.2f}")

    return compress(gap_rows), compress(excess_rows), suggestions

# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def main():
    df = load_ads()
    if df.empty:
        print("No READY ALGO ad of yours accepts this horizon.")
        return

    gaps, excess, sugg = analyse(df)
    hdr = f"{HORIZON_DAYS}‑day horizon (raise tips {'per‑month' if NORMALISE else 'full contract'})"
    print("\n" + "="*len(hdr))
    print(hdr)
    print("="*len(hdr))

    print("\nCoverage gaps (no winning ad)")
    print("-"*35)
    print("None" if not gaps else "\n".join(gaps))

    print(f"\nExcess margin >= {EXCESS_MARGIN:.1f} ALGO")
    print("-"*35)
    print("None" if not excess else "\n".join(excess))

    print(f"\nSafe raise suggestions (BUFFER {BUFFER} ALGO)")
    print("-"*35)
    print("None" if not sugg else "\n".join(sugg))

if __name__ == "__main__":
    main()
