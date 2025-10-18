#!/usr/bin/env python3
"""
Discover all Delegator contracts via the Valar Noticeboard and print:
address,suspended,status,incentive_eligible

• No arguments, no indexer (local algod only).
• "Suspended" = (status == Offline) AND current_round ∈ [vote_first, vote_last].
"""

import base64
from algosdk.v2client import algod
from algosdk.encoding import encode_address
from algosdk.logic import get_application_address

# ── CONFIG (local node) ──────────────────────────────────────────────────
NOTICEBOARD_APP_ID = 2713948864
ALGOD_ADDRESS      = "http://localhost:8080"
ALGOD_TOKEN        = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

# ── helpers ──────────────────────────────────────────────────────────────
def _u64(b, ofs=0): return int.from_bytes(b[ofs:ofs+8], "big")
def decode_u64_list(b): return [_u64(b, i) for i in range(0, len(b), 8) if i+8 <= len(b)]

def get_validator_ad_ids(client: algod.AlgodClient):
    nb_addr = get_application_address(NOTICEBOARD_APP_ID)
    info = client.account_info(nb_addr)
    return [app["id"] for app in info.get("created-apps", [])]

def get_delco_ids_from_ad(client: algod.AlgodClient, ad_id: int):
    gs = client.application_info(ad_id)["params"].get("global-state", []) or []
    for e in gs:
        key = base64.b64decode(e["key"]).decode(errors="ignore")
        if key == "del_app_list":
            blob = base64.b64decode(e["value"]["bytes"])
            return [x for x in decode_u64_list(blob) if x]
    return []

def get_del_beneficiary(client: algod.AlgodClient, delco_id: int):
    gs = client.application_info(delco_id)["params"].get("global-state", []) or []
    for e in gs:
        key = base64.b64decode(e["key"]).decode(errors="ignore")
        if key == "del_beneficiary":
            raw = base64.b64decode(e["value"]["bytes"])
            if len(raw) == 32:
                try: return encode_address(raw)
                except Exception: return None
    return None

def classify_suspension(status, vf, vl, current_round):
    in_window = isinstance(vf, int) and isinstance(vl, int) and vf <= current_round <= vl
    if not isinstance(vf, int) or not isinstance(vl, int):
        return "Not registered", False
    if current_round > vl:
        return "Expired", False
    if status == "Offline" and in_window:
        return "Suspended", True
    if status == "Online" and in_window:
        return "Valid", False
    return (status or "Unknown"), False

# ── main ─────────────────────────────────────────────────────────────────
def main():
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    current_round = client.status()["last-round"]

    # 1) Discover validator ads from the Noticeboard
    ad_ids = get_validator_ad_ids(client)

    # 2) Collect delegator app IDs from each ad
    delco_ids = set()
    for ad in ad_ids:
        delco_ids.update(get_delco_ids_from_ad(client, ad))

    # 3) Map delegator → beneficiary address (unique)
    addrs = set()
    for did in sorted(delco_ids):
        addr = get_del_beneficiary(client, did)
        if addr:
            addrs.add(addr)

    # 4) Snapshot each beneficiary account and report
    print("address,suspended,status,incentive_eligible")
    for addr in sorted(addrs):
        acct = client.account_info(addr)
        status = acct.get("status")
        part = acct.get("participation") or {}
        vf, vl = part.get("vote-first-valid"), part.get("vote-last-valid")
        inc = acct.get("incentive-eligible")  # may be absent → printed empty

        verdict, suspended = classify_suspension(status, vf, vl, current_round)
        # Output strictly the requested fields
        print(",".join([
            addr,
            "true" if suspended else "false",
            status or "",
            "" if inc is None else str(bool(inc)),
        ]))

if __name__ == "__main__":
    main()
