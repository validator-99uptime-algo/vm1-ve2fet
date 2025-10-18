#!/usr/bin/env python3
# classify_validators_by_delegator_votes.py
# Indexer-only. One row per validator_ad_app_id.

import os, sys, sqlite3, requests
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH      = os.getenv("VALAR_DB", "/home/ve2pcq/valar_database/valar.db")
INDEXER_URL  = os.getenv("INDEXER_URL", "https://mainnet-idx.4160.nodely.dev")
TIMEOUT_S    = float(os.getenv("TIMEOUT_S", "8.0"))
MAX_WORKERS  = int(os.getenv("MAX_WORKERS", "12"))

S = requests.Session()

def current_round():
    r = S.get(f"{INDEXER_URL}/v2/transactions", params={"limit":1}, timeout=TIMEOUT_S); r.raise_for_status()
    return r.json()["current-round"]

def vote_window(cur_round: int):
    r = S.get(f"{INDEXER_URL}/v2/blocks/{cur_round}", params={"header-only":"true"}, timeout=TIMEOUT_S); r.raise_for_status()
    blk = (r.json().get("block") or r.json())
    us  = blk.get("upgrade-state", {}) or {}
    V   = int(us.get("next-protocol-vote-before") or 0)
    if not V: raise RuntimeError("vote-before not published yet")
    return V - 10_000, V

def load_delegators_for_validators(cur_round: int):
    # returns list of (validator_ad_app_id, del_beneficiary)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT validator_ad_app_id AS vid, del_beneficiary AS addr "
            "FROM delegator_contracts WHERE state=5 AND round_end>=? "
            "AND addr IS NOT NULL",
            (cur_round,)
        ).fetchall()
        return [(r["vid"], r["addr"]) for r in rows if r["vid"] and r["addr"]]

def check_addr_in_window(addr: str, start_r: int, end_r: int):
    """
    Return ('YES', yes_round) if any header has upgrade-approve=true;
           ('NO', '')        if proposed but no YES;
           ('NONE','')       if no proposals in window.
    """
    next_tok = ""; saw_any = False; yes_round = None
    while True:
        params = {"proposers": addr, "min-round": start_r, "max-round": end_r, "limit": 1000}
        if next_tok: params["next"] = next_tok
        r = S.get(f"{INDEXER_URL}/v2/block-headers", params=params, timeout=TIMEOUT_S); r.raise_for_status()
        data = r.json(); blocks = data.get("blocks", [])
        if blocks:
            saw_any = True
            for h in blocks:
                uv = h.get("upgrade-vote", {}) or {}
                if uv.get("upgrade-approve") is True:
                    yes_round = h["round"]
        next_tok = data.get("next-token", "")
        if not next_tok or yes_round is not None:
            break
    if yes_round is not None: return ("YES", yes_round)
    if saw_any:               return ("NO",  "")
    return ("NONE","")

def main():
    try:
        cur = current_round()
        start_r, end_r = vote_window(cur)

        pairs = load_delegators_for_validators(cur)
        if not pairs:
            print("validator_ad_app_id,status,delegators,total_yes,total_no,total_none,any_yes_round")
            return

        # group delegators by validator
        dels_by_val = defaultdict(list)
        for vid, addr in pairs:
            dels_by_val[vid].append(addr)

        # dedupe addresses per validator to avoid duplicate checks
        unique_addrs = sorted({addr for _, addr in pairs})

        # run checks per delegator address
        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(check_addr_in_window, a, start_r, end_r): a for a in unique_addrs}
            for f in as_completed(futs):
                a = futs[f]
                try:
                    results[a] = f.result()
                except Exception as e:
                    results[a] = ("NONE","")  # conservative

        # aggregate per validator
        print(f"# WINDOW [{start_r},{end_r}] addrs={len(unique_addrs)} validators={len(dels_by_val)}")
        print("validator_ad_app_id,status,delegators,total_yes,total_no,total_none,any_yes_round")
        for vid in sorted(dels_by_val.keys()):
            yes = no = none = 0
            any_yes_round = ""
            for addr in set(dels_by_val[vid]):
                st, rnd = results.get(addr, ("NONE",""))
                if st == "YES":
                    yes += 1
                    if not any_yes_round: any_yes_round = str(rnd)
                elif st == "NO":
                    no  += 1
                else:
                    none += 1
            # classify validator
            if yes > 0:       status = "UPGRADED"
            elif no > 0:      status = "NOT-SUPPORTED"
            else:             status = "UNKNOWN"
            print(f"{vid},{status},{len(set(dels_by_val[vid]))},{yes},{no},{none},{any_yes_round}")

    except Exception as e:
        print("ERROR:", e); sys.exit(2)

if __name__ == "__main__":
    main()
