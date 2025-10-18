#!/usr/bin/env python3
"""
list_gating.py – dump the Eligibility / Gating requirement(s)
for every Valar Validator-Ad on this node.

Output columns
--------------
ad_id | cnt_asa | ASA1_ID | ASA1_min | ASA2_ID | ASA2_min
If cnt_asa is 0 the remaining columns show 0.
For cnt_asa == 1 only ASA1_* are meaningful.
"""

import base64, os, sys
from algosdk.v2client import algod
from algosdk.logic    import get_application_address

# ─── CONFIG ──────────────────────────────────────────────────────────────
NOTICEBOARD_APP_ID = 2713948864          # Valar noticeboard
ALGOD_ADDRESS      = "http://localhost:8080"
ALGOD_TOKEN        = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
# ------------------------------------------------------------------------

client   = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
nb_addr  = get_application_address(NOTICEBOARD_APP_ID)
ad_ids   = [
    app["id"]
    for app in client.account_info(nb_addr).get("created-apps", [])
]

def u64(buf: bytes, ofs: int = 0) -> int:
    return int.from_bytes(buf[ofs : ofs + 8], "big")

def decode_gating(buf: bytes, cnt: int):
    """Return up to two (asa_id, min_amount) pairs."""
    pairs = []
    for i in range(cnt):
        ofs = i * 16
        if ofs + 16 > len(buf):
            break
        asa_id  = u64(buf, ofs)
        min_amt = u64(buf, ofs + 8)
        pairs.append((asa_id, min_amt))
    while len(pairs) < 2:          # pad to always have two slots
        pairs.append((0, 0))
    return pairs[:2]

print("ad_id | cnt_asa | ASA1_ID | ASA1_min | ASA2_ID | ASA2_min")

for aid in ad_ids:
    try:
        gs = client.application_info(aid)["params"].get("global-state", [])
    except Exception as e:
        print(f"# skip {aid}: {e}", file=sys.stderr)
        continue

    cnt_asa = 0
    rawG    = b""
    for entry in gs:
        key = base64.b64decode(entry["key"]).decode()
        val = entry["value"]
        if key == "cnt_asa":
            cnt_asa = val["uint"]
        elif key == "G":
            rawG = base64.b64decode(val["bytes"])

    pairs = decode_gating(rawG, cnt_asa)
    (asa1_id, asa1_min), (asa2_id, asa2_min) = pairs

    print(f"{aid} | {cnt_asa} | {asa1_id} | {asa1_min} | {asa2_id} | {asa2_min}")
