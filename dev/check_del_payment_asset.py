#!/usr/bin/env python3
"""
check_del_payment_asset.py  –  one-shot inspector for a *delegator contract*

usage:
    (venv)$ python check_del_payment_asset.py  <delegator_app_id>

what you get:
    • contract state byte (0x05 = LIVE, 0x14 = ENDED_EXPIRED, …)
    • payment-asset ID and its unit-name / decimals
    • fee_round_milli, fee_setup  (raw, in base-units)
"""

import sys, base64, json
from algosdk.v2client import algod
from algosdk.encoding import encode_address

# ── RPC endpoint ───────────────────────────────────────────
ALGOD_ADDRESS = "http://localhost:8080"
ALGOD_TOKEN   = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

# ── helpers ────────────────────────────────────────────────
def u64(buf, off=0):      # 8-byte big-endian → int
    return int.from_bytes(buf[off:off+8], "big")

def decode_gs(gs):
    out = {}
    for e in gs:
        k = base64.b64decode(e["key"]).decode()
        v = e["value"]
        if v["type"] == 1:            # bytes
            out[k] = base64.b64decode(v["bytes"])
        else:                         # uint
            out[k] = v["uint"]
    return out

# ── main ───────────────────────────────────────────────────
def main(app_id: int):
    cli = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    gs  = cli.application_info(app_id)["params"].get("global-state", [])
    st  = decode_gs(gs)

    # sanity check – delegator contracts always have “G” & “B”
    if "G" not in st:
        sys.exit("❌  App-ID {} has no G-array → not a delegator contract?".format(app_id))

    G = st["G"]                       # raw bytes, 96 bytes long
    state = st.get("state", b"\x00")[0]

    fee_asset_id = u64(G, 24)
    fee_round_milli = u64(G, 8)
    fee_setup       = u64(G,16)

    # asset meta
    if fee_asset_id == 0:
        unit, dec = "ALGO", 6
    else:
        prm = cli.asset_info(fee_asset_id)["params"]
        unit, dec = prm.get("unit-name", "ASA{}".format(fee_asset_id)), prm["decimals"]

    print(f"\nDelegator {app_id}  – basic payment info")
    print("state byte             : 0x{:02x}".format(state))
    print("payment asset          : {}  (id {})".format(unit, fee_asset_id))
    print("asset decimals         : {}".format(dec))
    print("fee_round_milli (raw)  : {}".format(fee_round_milli))
    print("fee_setup (raw)        : {}".format(fee_setup))

if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("usage: python check_del_payment_asset.py <delegator_app_id>")
    main(int(sys.argv[1]))
