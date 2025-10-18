#!/usr/bin/env python3
# test_all_beneficiaries_preswitch_votes.py
# Indexer-only. For every DISTINCT del_beneficiary in delegator_contracts (active),
# prints whether it cast any YES vote during the current upgrade voting window.

import os, sys, sqlite3, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH      = os.getenv("VALAR_DB", "/home/ve2pcq/ve2fet/valar_database/valar.db")
INDEXER_URL  = os.getenv("INDEXER_URL", "https://mainnet-idx.4160.nodely.dev")
TIMEOUT_S    = float(os.getenv("TIMEOUT_S", "8.0"))
MAX_WORKERS  = int(os.getenv("MAX_WORKERS", "8"))

S = requests.Session()

def current_round() -> int:
    r = S.get(f"{INDEXER_URL}/v2/transactions", params={"limit":1}, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()["current-round"]

def upgrade_window(cur_round: int) -> tuple[int, int, str, int]:
    # Read a recent block's upgrade-state to get vote-before (V) and switch (S)
    r = S.get(f"{INDEXER_URL}/v2/blocks/{cur_round}", params={"header-only":"true"}, timeout=TIMEOUT_S)
    r.raise_for_status()
    blk = (r.json().get("block") or r.json())
    us  = blk.get("upgrade-state", {}) or {}
    next_proto = us.get("next-protocol") or ""
    V = int(us.get("next-protocol-vote-before") or 0)
    Sw = int(us.get("next-protocol-switch-on") or 0)
    if V == 0:
        raise RuntimeError("vote-before not published yet")
    start = max(0, V - 10_000)  # mainnet voting window
    end   = V
    return start, end, next_proto, Sw

def check_addr_in_window(addr: str, start_r: int, end_r: int, next_proto: str) -> tuple[str, str, int|None]:
    # Returns (address, STATUS, yes_round|None)
    # STATUS ∈ {"VOTED-YES", "VOTED-NO-OR-NOT-SUPPORTED", "NO-PROPOSAL-IN-WINDOW", "ERROR"}
    try:
        next_token = ""
        saw_any = False
        yes_round = None
        while True:
            params = {
                "proposers": addr,
                "min-round": start_r,
                "max-round": end_r,
                "limit": 1000
            }
            if next_token:
                params["next"] = next_token
            r = S.get(f"{INDEXER_URL}/v2/block-headers", params=params, timeout=TIMEOUT_S)
            r.raise_for_status()
            data = r.json()
            blocks = data.get("blocks", [])
            if blocks:
                saw_any = True
                for h in blocks:
                    uv = h.get("upgrade-vote", {}) or {}
                    us = h.get("upgrade-state", {}) or {}
                    if uv.get("upgrade-approve") is True:
                        # Optional: ensure it's for the same pending next protocol
                        if not next_proto or us.get("next-protocol") == next_proto:
                            yes_round = h["round"]
            next_token = data.get("next-token", "")
            if not next_token:
                break

        if yes_round is not None:
            return addr, "VOTED-YES", yes_round
        if saw_any:
            return addr, "VOTED-NO-OR-NOT-SUPPORTED", None
        return addr, "NO-PROPOSAL-IN-WINDOW", None

    except requests.HTTPError as e:
        msg = getattr(e, "response", None) and e.response.text
        sys.stderr.write(f"[HTTP_ERROR] {addr}: {e} {msg or ''}\n")
        return addr, "ERROR", None
    except Exception as e:
        sys.stderr.write(f"[ERROR] {addr}: {e}\n")
        return addr, "ERROR", None

def load_active_beneficiaries(cur_round: int) -> list[str]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # same “active” filter you used in your APY script
        rows = conn.execute(
            "SELECT DISTINCT del_beneficiary AS addr "
            "FROM delegator_contracts "
            "WHERE state=5 AND round_end>=?",
            (cur_round,)
        ).fetchall()
        return [r["addr"] for r in rows if r["addr"]]

def main():
    try:
        cur = current_round()
        start, end, next_proto, switch_on = upgrade_window(cur)

        addrs = load_active_beneficiaries(cur)
        if not addrs:
            print("no addresses found"); return

        print(f"# WINDOW [{start},{end}]  switch={switch_on}  addrs={len(addrs)}")
        print("address,status,yes_round")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(check_addr_in_window, a, start, end, next_proto) for a in addrs]
            for f in as_completed(futures):
                addr, status, yes_round = f.result()
                print(f"{addr},{status},{'' if yes_round is None else yes_round}")

    except Exception as e:
        sys.stderr.write(f"FATAL: {e}\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
