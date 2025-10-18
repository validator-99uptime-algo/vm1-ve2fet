#!/usr/bin/env python3
# find_last_proposed_block_with_upgrade_fields.py
import os, requests
from datetime import datetime, timezone

# ---- CONFIG ----
ADDR          = "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA"
ALGOD_ADDRESS = os.getenv("ALGOD_ADDRESS", "http://localhost:8080")
ALGOD_TOKEN   = os.getenv("ALGOD_TOKEN",   "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690")
INDEXER_URL   = os.getenv("INDEXER_URL",   "https://mainnet-idx.4160.nodely.dev")
SECS_PER_ROUND = 2.8
RELEASE_UTC  = datetime(2025, 9, 16, 0, 0, tzinfo=timezone.utc)  # scan floor

H = {"X-Algo-API-Token": ALGOD_TOKEN}

def get_last_round(s):
    r = s.get(f"{ALGOD_ADDRESS}/v2/status", headers=H, timeout=8)
    r.raise_for_status()
    return r.json()["last-round"]

def get_block_json_local(s, rnd):
    # Try header-only JSON; fall back to full JSON if unsupported
    for qs in ("?format=json&header-only=true", "?format=json"):
        r = s.get(f"{ALGOD_ADDRESS}/v2/blocks/{rnd}{qs}", headers=H, timeout=8)
        if r.status_code == 404:
            return None
        if r.ok:
            return r.json().get("block") or r.json()
    return None

def extract_field(d, *names):
    # Try both hyphenated and camelCase keys; search 1 level deep as well
    for n in names:
        if n in d: return d[n]
    for v in d.values():
        if isinstance(v, dict):
            for n in names:
                if n in v: return v[n]
    return None

def extract_proposer(block_json):
    # Proposer should be a base32 string under "proposer"
    p = extract_field(block_json, "proposer", "prp")
    return p if isinstance(p, str) else None

def extract_upgrade_vote(block_json):
    uv = extract_field(block_json, "upgrade-vote", "upgradeVote") or {}
    return {
        "upgrade-approve": uv.get("upgrade-approve", uv.get("upgradeApprove")),
        "upgrade-propose": uv.get("upgrade-propose", uv.get("upgradePropose")),
        "upgrade-delay":   uv.get("upgrade-delay",   uv.get("upgradeDelay")),
    }

def extract_upgrade_state(block_json):
    us = extract_field(block_json, "upgrade-state", "upgradeState") or {}
    return {
        "current-protocol":          us.get("current-protocol",          us.get("currentProtocol")),
        "next-protocol":             us.get("next-protocol",             us.get("nextProtocol")),
        "next-protocol-approvals":   us.get("next-protocol-approvals",   us.get("nextProtocolApprovals")),
        "next-protocol-switch-on":   us.get("next-protocol-switch-on",   us.get("nextProtocolSwitchOn")),
        "next-protocol-vote-before": us.get("next-protocol-vote-before", us.get("nextProtocolVoteBefore")),
    }

def local_scan_latest_proposal(s, start_rnd, end_rnd):
    for rnd in range(end_rnd, start_rnd - 1, -1):
        blk = get_block_json_local(s, rnd)
        if not blk: 
            continue
        if extract_proposer(blk) == ADDR:
            return rnd, blk
    return None, None

def indexer_latest_proposal_and_fields(s, min_rnd, max_rnd):
    next_tok = ""
    last = None
    last_block_obj = None
    params = {"proposers": ADDR, "min-round": min_rnd, "max-round": max_rnd, "limit": 1000}
    while True:
        if next_tok:
            params["next"] = next_tok
        r = s.get(f"{INDEXER_URL}/v2/block-headers", params=params, timeout=15)
        if not r.ok:
            break
        data = r.json()
        blocks = data.get("blocks", [])
        if blocks:
            last = blocks[-1]["round"]
            last_block_obj = blocks[-1]
        next_tok = data.get("next-token", "")
        if not next_tok:
            break
    return last, last_block_obj

def main():
    with requests.Session() as s:
        last = get_last_round(s)
        delta = max(0, (datetime.now(timezone.utc) - RELEASE_UTC).total_seconds())
        window = int(delta / SECS_PER_ROUND) + 5000
        start = max(0, last - max(window, 10000))

        # 1) Local-first
        rnd, blk = local_scan_latest_proposal(s, start, last)
        if rnd is not None:
            uv = extract_upgrade_vote(blk)
            us = extract_upgrade_state(blk)
            print(f"LAST_PROPOSAL: round={rnd} source=local")
            print(f"UPGRADE_VOTE: approve={uv['upgrade-approve']} propose={uv['upgrade-propose']} delay={uv['upgrade-delay']}")
            print("UPGRADE_STATE:", us)
            return

        # 2) Indexer fallback
        rnd, blk = indexer_latest_proposal_and_fields(s, start, last)
        if rnd is not None and blk is not None:
            # Indexer already returns upgrade fields in the header object
            uv = blk.get("upgrade-vote", {})
            us = blk.get("upgrade-state", {})
            print(f"LAST_PROPOSAL: round={rnd} source=indexer")
            print(f"UPGRADE_VOTE: approve={uv.get('upgrade-approve')} propose={uv.get('upgrade-propose')} delay={uv.get('upgrade-delay')}")
            print("UPGRADE_STATE:", {
                "current-protocol":          us.get("current-protocol"),
                "next-protocol":             us.get("next-protocol"),
                "next-protocol-approvals":   us.get("next-protocol-approvals"),
                "next-protocol-switch-on":   us.get("next-protocol-switch-on"),
                "next-protocol-vote-before": us.get("next-protocol-vote-before"),
            })
            return

        print("LAST_PROPOSAL: not found in window")

if __name__ == "__main__":
    main()
