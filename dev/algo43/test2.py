#!/usr/bin/env python3
# test_preswitch_support.py
# Goal: PRE-SWITCH check — did ADDR vote YES for the pending protocol during the voting window?
# Indexer-only. Prints one of: VOTED-YES, VOTED-NO-OR-NOT-SUPPORTED, NO-PROPOSAL-IN-WINDOW.

import os, sys, requests

ADDR        = os.getenv("ADDR", "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA")
INDEXER_URL = os.getenv("INDEXER_URL", "https://mainnet-idx.4160.nodely.dev")
TIMEOUT_S   = float(os.getenv("TIMEOUT_S", "8.0"))
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "10000"))  # scan [vote_before - WINDOW_SIZE, vote_before]

s = requests.Session()

def current_round() -> int:
    r = s.get(f"{INDEXER_URL}/v2/transactions", params={"limit":1}, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()["current-round"]

def network_upgrade_state(cur_round: int):
    r = s.get(f"{INDEXER_URL}/v2/blocks/{cur_round}", params={"header-only":"true"}, timeout=TIMEOUT_S)
    r.raise_for_status()
    b = (r.json().get("block") or r.json())
    us = b.get("upgrade-state", {}) or {}
    return {
        "current":      us.get("current-protocol"),
        "next":         us.get("next-protocol"),
        "vote_before":  int(us.get("next-protocol-vote-before") or 0),
        "switch_on":    int(us.get("next-protocol-switch-on") or 0),
    }

def find_votes_in_window(addr: str, start_r: int, end_r: int):
    next_tok = ""
    yes_round = None
    saw_any = False
    while True:
        params = {"proposers": addr, "min-round": start_r, "max-round": end_r, "limit": 1000}
        if next_tok:
            params["next"] = next_tok
        r = s.get(f"{INDEXER_URL}/v2/block-headers", params=params, timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        blocks = data.get("blocks", [])
        if blocks:
            saw_any = True
            for h in blocks:
                uv = h.get("upgrade-vote", {}) or {}
                us = h.get("upgrade-state", {}) or {}
                if uv.get("upgrade-approve") is True and us.get("next-protocol"):
                    yes_round = h["round"]  # keep last YES seen
        next_tok = data.get("next-token", "")
        if not next_tok:
            break
    return saw_any, yes_round

def main():
    try:
        cur = current_round()
        st = network_upgrade_state(cur)
        V = st["vote_before"]
        S = st["switch_on"]

        if V == 0:
            print(f"ERROR: vote window not published yet (current_round={cur})"); sys.exit(1)

        start = max(0, V - WINDOW_SIZE)
        saw, yes_rnd = find_votes_in_window(ADDR, start, V)

        print(f"SWITCH_ROUND={S} VOTE_BEFORE={V} WINDOW=[{start},{V}] ADDR={ADDR}")

        if yes_rnd is not None:
            print(f"STATUS=VOTED-YES ROUND={yes_rnd}")
        elif saw:
            print("STATUS=VOTED-NO-OR-NOT-SUPPORTED")
        else:
            print("STATUS=NO-PROPOSAL-IN-WINDOW")

    except requests.HTTPError as e:
        print("HTTP_ERROR", e, (e.response.text if getattr(e, "response", None) else ""))
        sys.exit(2)
    except Exception as e:
        print("ERROR", e); sys.exit(2)

if __name__ == "__main__":
    main()
