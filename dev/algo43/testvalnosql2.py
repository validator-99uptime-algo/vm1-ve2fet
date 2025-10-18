#!/usr/bin/env python3
# testvalnosql2.py
# NO SQLite. Local algod for apps; Indexer for voting-window headers.
# Changes:
#  • Exclude validators with delegators=0 from main section
#  • List those zero-delegator validators in a separate section at the end
#  • “Last block wins” across all LIVE (state=5) delegators per validator
#  • Labels: UPGRADED / NOT-UPGRADED / UNKNOWN

import os, sys, base64, csv, requests
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from algosdk.v2client import algod
from algosdk.encoding import encode_address
from algosdk.logic import get_application_address

# ---- Config (hard-coded token/addr as you use in your scripts) ----
ALGOD_ADDRESS      = "http://localhost:8080"
ALGOD_TOKEN        = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
INDEXER_URL        = "https://mainnet-idx.4160.nodely.dev"
NOTICEBOARD_APP_ID = 2713948864
LIVE_STATE_VALUE   = 5
TIMEOUT_S          = 8.0
MAX_WORKERS        = 12

client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
S = requests.Session()

# ---- Helpers ---------------------------------------------------------------
def u64(b: bytes, ofs: int = 0) -> int:
    return int.from_bytes(b[ofs:ofs+8], "big")

def decode_u64_list(b: bytes) -> List[int]:
    return [u64(b, i) for i in range(0, len(b), 8) if i+8 <= len(b)]

def decode_gs(gs) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for entry in gs or []:
        key = base64.b64decode(entry["key"]).decode()
        val = entry["value"]
        if val["type"] == 2:
            out[key] = val["uint"]
        else:
            raw = base64.b64decode(val["bytes"])
            if len(raw) == 32 and key in ("val_owner","val_manager","del_beneficiary","del_manager"):
                try: out[key] = encode_address(raw)
                except: out[key] = raw.hex()
            elif key in ("P","T","W","S","del_app_list"):
                out[key] = decode_u64_list(raw)
            elif key == "state" and len(raw) >= 1:
                out[key] = raw[0]
            else:
                out[key] = raw.hex()
    return out

def noticeboard_validator_ids(nb_app_id: int) -> List[int]:
    nb_escrow = get_application_address(nb_app_id)
    created = client.account_info(nb_escrow).get("created-apps", [])
    return [app["id"] for app in created]

def get_validator_info(vid: int) -> Tuple[str, List[int]]:
    gs = client.application_info(vid)["params"].get("global-state", [])
    d  = decode_gs(gs)
    owner = d.get("val_owner", "")
    del_list = d.get("del_app_list", []) if isinstance(d.get("del_app_list", []), list) else []
    return owner, del_list

def get_live_beneficiary(did: int):
    gs = client.application_info(did)["params"].get("global-state", [])
    d  = decode_gs(gs)
    return d.get("del_beneficiary") if d.get("state") == LIVE_STATE_VALUE else None

def current_round_indexer() -> int:
    r = S.get(f"{INDEXER_URL}/v2/transactions", params={"limit":1}, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()["current-round"]

def voting_window(cur_round: int) -> Tuple[int,int]:
    r = S.get(f"{INDEXER_URL}/v2/blocks/{cur_round}", params={"header-only":"true"}, timeout=TIMEOUT_S)
    r.raise_for_status()
    blk = (r.json().get("block") or r.json())
    V = int((blk.get("upgrade-state", {}) or {}).get("next-protocol-vote-before") or 0)
    if not V: raise RuntimeError("vote-before not available from indexer header")
    return V - 10_000, V

def last_in_window_for_addrs(addrs: List[str], start_r: int, end_r: int):
    """Returns (last_round:int|'' , last_approve:bool|None). Last block across all addrs."""
    if not addrs: return "", None
    next_tok = ""; last_round = None; last_approve = None
    params = {"proposers": ",".join(addrs), "min-round": start_r, "max-round": end_r, "limit": 1000}
    while True:
        if next_tok: params["next"] = next_tok
        r = S.get(f"{INDEXER_URL}/v2/block-headers", params=params, timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        for h in data.get("blocks", []):
            rnd = h["round"]
            appr = (h.get("upgrade-vote", {}) or {}).get("upgrade-approve") is True
            # ascending; overwrite to keep the last one overall
            last_round = rnd
            last_approve = appr
        next_tok = data.get("next-token", "")
        if not next_tok: break
    if last_round is None: return "", None
    return last_round, last_approve

def classify(last_approve, had_any) -> str:
    if last_approve is True: return "UPGRADED"
    if had_any and last_approve is not True: return "NOT-UPGRADED"
    return "UNKNOWN"

# ---- Main ------------------------------------------------------------------
def main():
    cur = current_round_indexer()
    start_r, end_r = voting_window(cur)

    validator_ids = noticeboard_validator_ids(NOTICEBOARD_APP_ID)

    main_rows = []   # validators with >=1 LIVE delegator
    zero_rows = []   # validators with 0 LIVE delegators

    def work(vid: int):
        try:
            owner, del_ids = get_validator_info(vid)
            # Gather LIVE beneficiaries (<=4 by Valar policy)
            bens: List[str] = []
            for did in del_ids:
                try:
                    b = get_live_beneficiary(did)
                    if b: bens.append(b)
                except Exception:
                    continue
            if not bens:
                # zero-delegator section
                return ("ZERO", [owner, str(vid), "UNKNOWN", "0", "0", "0", "0", ""])
            # Voting-window “last block wins” across all LIVE delegators
            last_round, last_approve = last_in_window_for_addrs(bens, start_r, end_r)
            had_any = (last_round != "")
            status = classify(last_approve, had_any)
            # Counts: keep simple (delegators count; last outcome indicators)
            total_yes = "1" if last_approve is True else "0"
            total_no  = "1" if (had_any and last_approve is not True) else "0"
            total_none = "0" if had_any else str(len(bens))
            row = [owner, str(vid), status, str(len(bens)), total_yes, total_no, total_none,
                   (str(last_round) if had_any else "")]
            return ("MAIN", row)
        except Exception:
            return ("MAIN", ["", str(vid), "UNKNOWN", "0", "0", "0", "0", ""])

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(work, vid) for vid in validator_ids]
        for f in as_completed(futures):
            kind, row = f.result()
            if kind == "ZERO": zero_rows.append(row)
            else:               main_rows.append(row)

    main_rows.sort(key=lambda r: (r[0], int(r[1]) if r[1].isdigit() else 0))
    zero_rows.sort(key=lambda r: (r[0], int(r[1]) if r[1].isdigit() else 0))

    w = csv.writer(sys.stdout, lineterminator="\n")
    # Main section (validators with LIVE delegators)
    w.writerow(["validator_owner","validator_ad_app_id","status","delegators","total_yes","total_no","total_none","last_in_window_round"])
    for r in main_rows:
        w.writerow(r)
    # Separate section
    print("")  # blank line separator (Excel ok)
    print("# validators_with_no_live_delegators")
    w.writerow(["validator_owner","validator_ad_app_id","status","delegators","total_yes","total_no","total_none","last_in_window_round"])
    for r in zero_rows:
        w.writerow(r)

if __name__ == "__main__":
    main()
