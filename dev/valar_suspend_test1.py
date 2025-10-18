#!/usr/bin/env python3
# valar_nb_probe_offsets.py — brute-force find app IDs inside Noticeboard user boxes

import base64, struct
from algosdk.v2client import algod
from algosdk.encoding import decode_address, encode_address

ALGOD_ADDRESS       = "http://localhost:8080"
ALGOD_TOKEN         = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
NOTICEBOARD_APP_ID  = 2713948864
DELEGATOR_APP_ID    = 3139255916
VALIDATOR_AD_APP_ID = 2921204282

DEL_MANAGER = "S7ESWLDBLVPTLBNSA5H2Y576RPRWRHJTKGTVTDJN52HL2NJKS2TTXF67BY"
VAL_OWNER   = "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA"

def fetch_box(client, addr_str):
    r = client.application_box_by_name(NOTICEBOARD_APP_ID, decode_address(addr_str))
    return base64.b64decode(r.get("value",""))

def scan_all(payload: bytes, target: int, label: str):
    hits = []
    t_be = target.to_bytes(8, "big")
    t_le = target.to_bytes(8, "little")
    for i in range(0, max(0, len(payload)-7)):
        chunk = payload[i:i+8]
        if chunk == t_be:
            hits.append((i, "BE"))
        if chunk == t_le:
            hits.append((i, "LE"))
    print(f"{label}: size={len(payload)}  target={target}")
    if hits:
        for off, kind in hits:
            print(f"  match at offset {off} ({kind})")
    else:
        print("  no matches found")

def main():
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    dm_box = fetch_box(client, DEL_MANAGER)
    vo_box = fetch_box(client, VAL_OWNER)

    print("Scanning users[del_manager] box …")
    scan_all(dm_box, DELEGATOR_APP_ID, "del_app_id in del_manager box")

    print("\nScanning users[val_owner] box …")
    scan_all(vo_box, VALIDATOR_AD_APP_ID, "val_app_id in val_owner box")

if __name__ == "__main__":
    main()
