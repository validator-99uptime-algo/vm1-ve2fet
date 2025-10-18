#!/usr/bin/env python3
# classify_validators_from_chain_csv.py
# Purpose: NO SQLite. Discover Valar validators & LIVE delegators from local algod,
#          then use Indexer to classify validators as UPGRADED / NOT-UPGRADED / UNKNOWN
#          based on each validator’s LIVE delegators’ last proposal in the voting window.
# Output CSV columns:
#   validator_owner,validator_ad_app_id,status,delegators,total_yes,total_no,total_none,last_in_window_round
#
# Requirements:
#   - Local algod node reachable (reads Noticeboard, validator apps, delegator apps)
#   - Indexer base URL (reads block headers in voting window)
#   - LIVE delegator state value: 5
#
# Env vars you can override:
#   ALGOD_ADDRESS (default http://localhost:8080)
#   ALGOD_TOKEN
#   INDEXER_URL
#   NOTICEBOARD_APP_ID (default 2713948864)
#   TIMEOUT_S (default 8.0)
#   MAX_WORKERS (default 12)

import os, sys, base64, csv, requests
from typing import Dict, List, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from algosdk.v2client import algod
from algosdk.encoding import encode_address

# ----- Config -----
ALGOD_ADDRESS       = os.getenv("ALGOD_ADDRESS", "http://localhost:8080")
# ALGOD_TOKEN         = os.getenv("ALGOD_TOKEN",   "")
ALGOD_TOKEN = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
INDEXER_URL         = os.getenv("INDEXER_URL",   "https://mainnet-idx.4160.nodely.dev")
NOTICEBOARD_APP_ID  = int(os.getenv("NOTICEBOARD_APP_ID", "2713948864"))
TIMEOUT_S           = float(os.getenv("TIMEOUT_S", "8.0"))
MAX_WORKERS         = int(os.getenv("MAX_WORKERS", "12"))
LIVE_STATE_VALUE    = 5  # per user confirmation

client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
S = requests.Session()

# ----- Helpers -----
def u64_from(b: bytes, ofs: int = 0) -> int:
    return int.from_bytes(b[ofs:ofs+8], "big")

def decode_u64_list(b: bytes) -> List[int]:
    return [u64_from(b, i) for i in range(0, len(b), 8) if i+8 <= len(b)]

def decode_global_state(gs) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for entry in gs or []:
        key = base64.b64decode(entry["key"]).decode()
        val = entry["value"]
        if val["type"] == 2:  # uint
            out[key] = val["uint"]
        else:
            raw = base64.b64decode(val["bytes"])
            if len(raw) == 32 and key in ("val_owner","val_manager","del_beneficiary","del_manager"):
                try:
                    out[key] = encode_address(raw)
                except Exception:
                    out[key] = raw.hex()
            elif key in ("P","T","W","S","del_app_list"):
                out[key] = decode_u64_list(raw)
            elif key == "state" and len(raw) >= 1:
                out[key] = raw[0]
            else:
                out[key] = raw.hex()
    return out

def noticeboard_created_validator_ids(nb_app_id: int) -> List[int]:
    nb_addr = client.application_info(nb_app_id)["params"]["creator"]
    # Account info for creator won’t list created-apps; use the Noticeboard’s *escrow* address:
    # In sc_val1.py you derive it via get_application_address(NOTICEBOARD_APP_ID)
    from algosdk.logic import get_application_address
    nb_escrow = get_application_address(nb_app_id)
    created = client.account_info(nb_escrow).get("created-apps", [])
    return [app["id"] for app in created]

def get_validator_info(validator_app_id: int) -> Tuple[str, List[int]]:
    gs = client.application_info(validator_app_id)["params"].get("global-state", [])
    d  = decode_global_state(gs)
    owner = d.get("val_owner", "")
    del_list = d.get("del_app_list", []) if isinstance(d.get("del_app_list", []), list) else []
    return owner, del_list

def get_delegator_beneficiary_if_live(delegator_app_id: int):
    gs = client.application_info(delegator_app_id)["params"].get("global-state", [])
    d  = decode_global_state(gs)
    if d.get("state") == LIVE_STATE_VALUE:
        return d.get("del_beneficiary")
    return None

def current_round_indexer() -> int:
    r = S.get(f"{INDEXER_URL}/v2/transactions", params={"limit":1}, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()["current-round"]

def vote_window_from_indexer(cur_round: int) -> Tuple[int,int]:
    r = S.get(f"{INDEXER_URL}/v2/blocks/{cur_round}", params={"header-only":"true"}, timeout=TIMEOUT_S)
    r.raise_for_status()
    blk = (r.json().get("block") or r.json())
    us  = blk.get("upgrade-state", {}) or {}
    V   = int(us.get("next-protocol-vote-before") or 0)
    if not V:
        raise RuntimeError("vote-before not available")
    return V - 10_000, V

def last_in_window_for_addrs(addrs: List[str], start_r: int, end_r: int):
    """
    Returns:
      last_round (int or ""), last_approve (bool or None if no proposal)
    Scans all headers for given proposers, tracking the *last* round and its approve bit.
    """
    if not addrs:
        return "", None
    # Batch proposers comma-separated; paginate
    next_tok = ""
    last_round = None
    last_approve = None
    params = {"proposers": ",".join(addrs), "min-round": start_r, "max-round": end_r, "limit": 1000}
    while True:
        if next_tok:
            params["next"] = next_tok
        r = S.get(f"{INDEXER_URL}/v2/block-headers", params=params, timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        blocks = data.get("blocks", [])
        for h in blocks:
            rnd = h["round"]
            # ascending by round; overwrite to keep the last
            uv = h.get("upgrade-vote", {}) or {}
            approve = uv.get("upgrade-approve", False) is True
            last_round = rnd
            last_approve = approve
        next_tok = data.get("next-token", "")
        if not next_tok:
            break
    if last_round is None:
        return "", None
    return last_round, last_approve

def classify(approve_last, had_any):
    if approve_last is True:
        return "UPGRADED"
    if had_any is True and approve_last is not True:
        return "NOT-UPGRADED"
    return "UNKNOWN"

def main():
    # 1) Voting window
    cur = current_round_indexer()
    start_r, end_r = vote_window_from_indexer(cur)

    # 2) Discover validators from Noticeboard (local)
    validator_ids = noticeboard_created_validator_ids(NOTICEBOARD_APP_ID)

    # 3) Build per-validator: owner + LIVE delegators’ beneficiary addresses
    rows = []  # for CSV
    # To avoid repetitive Indexer calls, we’ll resolve per validator concurrently
    def work(vid):
        try:
            owner, del_list = get_validator_info(vid)
            # live delegators (≤ 4)
            beneficiaries: List[str] = []
            for did in del_list:
                try:
                    b = get_delegator_beneficiary_if_live(did)
                    if b:
                        beneficiaries.append(b)
                except Exception:
                    continue
            # 4) Indexer classification based on last in-window proposal across those addresses
            if beneficiaries:
                last_round, last_approve = last_in_window_for_addrs(beneficiaries, start_r, end_r)
                had_any = (last_round != "")
                status  = classify(last_approve, had_any)
                last_round_str = str(last_round) if last_round != "" else ""
                total_yes = 1 if last_approve is True else 0
                total_no  = 1 if (had_any and last_approve is not True) else 0
                total_none = 0 if had_any else len(beneficiaries)
            else:
                # No LIVE delegators → UNKNOWN
                status = "UNKNOWN"
                last_round_str = ""
                total_yes = 0
                total_no = 0
                total_none = 0
            return [
                owner,
                str(vid),
                status,
                str(len(beneficiaries)),
                str(total_yes),
                str(total_no),
                str(total_none),
                last_round_str,
            ]
        except Exception as e:
            return ["", str(vid), "UNKNOWN", "0", "0", "0", "0", ""]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(work, vid) for vid in validator_ids]
        for f in as_completed(futures):
            rows.append(f.result())

    # Sort by owner then validator id
    rows.sort(key=lambda r: (r[0], int(r[1]) if r[1].isdigit() else 0))

    # 5) CSV
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["validator_owner","validator_ad_app_id","status","delegators","total_yes","total_no","total_none","last_in_window_round"])
    for r in rows:
        w.writerow(r)

if __name__ == "__main__":
    main()
