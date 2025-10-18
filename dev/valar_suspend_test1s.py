#!/usr/bin/env python3
# valar_suspend_nb_call.py — Call Noticeboard.breach_suspended(...) for a DelegatorContract (no archive).
# Uses ONLY the Noticeboard route (correct for creator-only checks in VA/DC).

import base64
from typing import Optional, List

from algosdk.v2client import algod
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, AccountTransactionSigner
from algosdk.abi import Method
from algosdk import mnemonic, account, transaction, encoding as algoenc
from algosdk.logic import get_application_address

# ---------- CONFIG ----------
SENDER_MN          = "collect sense parent process another size alter unaware act first element hub park again drop acid around crowd grocery glow reason egg remember absent sibling"
ALGOD_ADDRESS      = "http://localhost:8080"
ALGOD_TOKEN        = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

DELCO_APP_ID       = 3139255916
NOTICEBOARD_APP_ID = 2713948864
INDEX_OFFSET       = 84   # start of users[addr].app_ids in NB user box
# ----------------------------

def u64(b: bytes, ofs: int = 0) -> int:
    return int.from_bytes(b[ofs:ofs+8], "big")

def app_params(client: algod.AlgodClient, app_id: int) -> dict:
    return client.application_info(app_id)["params"]

def gs_addr(client: algod.AlgodClient, app_id: int, key: str) -> Optional[str]:
    gs = app_params(client, app_id).get("global-state", []) or []
    for e in gs:
        if base64.b64decode(e["key"]).decode(errors="ignore") == key:
            raw = base64.b64decode(e["value"]["bytes"])
            if len(raw) == 32:
                return algoenc.encode_address(raw)
    return None

def find_valad_for_delco(client: algod.AlgodClient, delco_id: int, nb_app_id: int) -> Optional[int]:
    nb_addr = get_application_address(nb_app_id)
    for app in client.account_info(nb_addr).get("created-apps", []) or []:
        ad_id = app["id"]
        gs = app_params(client, ad_id).get("global-state", []) or []
        for e in gs:
            if base64.b64decode(e["key"]).decode(errors="ignore") == "del_app_list":
                blob = base64.b64decode(e["value"]["bytes"])
                # decode full u64 list
                ids = [u64(blob, i) for i in range(0, len(blob), 8) if i+8 <= len(blob)]
                if delco_id in ids:
                    return ad_id
    return None

def nb_user_box(client: algod.AlgodClient, nb_app_id: int, addr: str) -> bytes:
    raw = algoenc.decode_address(addr)
    r = client.application_box_by_name(nb_app_id, raw)
    return base64.b64decode(r["value"])

def nb_index_from_box(buf: bytes, target_app_id: int, index_offset: int) -> int:
    if len(buf) < index_offset + 8:
        raise RuntimeError(f"NB user box too short: {len(buf)} bytes")
    slots = (len(buf) - index_offset) // 8
    for i in range(slots):
        if u64(buf, index_offset + 8*i) == target_app_id:
            return i
    raise RuntimeError("target app id not present in NB user box app_ids")

def main():
    # signer/client
    sk   = mnemonic.to_private_key(SENDER_MN)
    addr = account.address_from_private_key(sk)
    signer = AccountTransactionSigner(sk)
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # discover validator ad that lists this delegator (under THIS NB)
    val_app = find_valad_for_delco(client, DELCO_APP_ID, NOTICEBOARD_APP_ID)
    if not val_app:
        print(f"ERROR: no validator ad lists delegator {DELCO_APP_ID} under NB {NOTICEBOARD_APP_ID}")
        return

    # actors from GS
    del_manager     = gs_addr(client, DELCO_APP_ID, "del_manager")
    del_beneficiary = gs_addr(client, DELCO_APP_ID, "del_beneficiary")
    val_owner       = gs_addr(client, val_app,     "val_owner")
    if not (del_manager and del_beneficiary and val_owner):
        print("ERROR: missing del_manager / del_beneficiary / val_owner from GS")
        return

    # NB indices from user boxes (offset 84) + slot sanity
    dm_box = nb_user_box(client, NOTICEBOARD_APP_ID, del_manager)
    vo_box = nb_user_box(client, NOTICEBOARD_APP_ID, val_owner)
    del_app_idx = nb_index_from_box(dm_box, DELCO_APP_ID, INDEX_OFFSET)
    val_app_idx = nb_index_from_box(vo_box, val_app,       INDEX_OFFSET)

    print("ARGS:")
    print(" del_manager =", del_manager)
    print(" del_app     =", DELCO_APP_ID, " idx =", del_app_idx)
    print(" val_owner   =", val_owner)
    print(" val_app     =", val_app,       " idx =", val_app_idx)
    print("CHECK dm slot =", u64(dm_box, INDEX_OFFSET + 8*del_app_idx))
    print("CHECK vo slot =", u64(vo_box, INDEX_OFFSET + 8*val_app_idx))

    # Build NB.breach_suspended(del_manager, del_app, del_app_idx, val_owner, val_app, val_app_idx)
    atc = AtomicTransactionComposer()
    sp = client.suggested_params()
    sp.flat_fee = True
    sp.fee = 200_000  # headroom for inner calls

    method = Method.from_signature(
        "breach_suspended(address,application,uint64,address,application,uint64)"
        "((uint64,uint64,uint64),address,byte[100])"
    )

    boxes = [
        (NOTICEBOARD_APP_ID, algoenc.decode_address(del_manager)),
        (NOTICEBOARD_APP_ID, algoenc.decode_address(val_owner)),
    ]

    atc.add_method_call(
        app_id=NOTICEBOARD_APP_ID,
        method=method,
        method_args=[del_manager, DELCO_APP_ID, del_app_idx, val_owner, val_app, val_app_idx],
        sender=addr,
        sp=sp,
        signer=signer,
        on_complete=transaction.OnComplete.NoOpOC,
        accounts=[del_beneficiary],  # beneficiary first; NB/VA inner calls will have access if needed
        # omit foreign_apps -> let ATC derive correct order from ABI args
        boxes=boxes,
    )

    # SEND
    res = atc.execute(client, 8)
    print("breach_suspended txid:", res.tx_ids[0])

if __name__ == "__main__":
    main()
