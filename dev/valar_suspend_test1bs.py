#!/usr/bin/env python3
# Call Noticeboard.breach_suspended(...) for a DelegatorContract (NO ARCHIVE).
# Auto-discovers all 6 ABI args and submits the transaction via your local algod.

import base64, sys
from typing import Optional, List
from algosdk.v2client import algod
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, AccountTransactionSigner
from algosdk.abi import Method
from algosdk import mnemonic, account, transaction, encoding
from algosdk.logic import get_application_address

from algosdk.v2client.models import SimulateRequest, SimulateRequestTransactionGroup
import json

# --- REQUIRED: fill your funded signer (25 words) ---
SENDER_MN    = "collect sense parent process another size alter unaware act first element hub park again drop acid around crowd grocery glow reason egg remember absent sibling"

# --- Target DelegatorContract App ID ---
DELCO_APP_ID = 3139255916

# --- Local node + Noticeboard ---
ALGOD_ADDRESS      = "http://localhost:8080"
ALGOD_TOKEN        = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
NOTICEBOARD_APP_ID = 2713948864

# In this deployment, users[addr].app_ids starts at byte offset 84 in the Noticeboard user box.
INDEX_OFFSET = 84

# ----------------- helpers -----------------
def u64(b: bytes, ofs: int = 0) -> int:
    return int.from_bytes(b[ofs:ofs+8], "big")

def decode_u64s(buf: bytes) -> List[int]:
    return [u64(buf, i) for i in range(0, len(buf), 8) if i+8 <= len(buf)]

def app_global(client: algod.AlgodClient, app_id: int) -> dict:
    return client.application_info(app_id)["params"]

def gs_addr(client: algod.AlgodClient, app_id: int, key_name: str) -> Optional[str]:
    gs = app_global(client, app_id).get("global-state", []) or []
    for entry in gs:
        key = base64.b64decode(entry["key"]).decode(errors="ignore")
        if key == key_name:
            raw = base64.b64decode(entry["value"]["bytes"])
            if len(raw) == 32:
                try:
                    return encoding.encode_address(raw)
                except Exception:
                    return None
    return None

def find_valad_for_delco(client: algod.AlgodClient, delco_id: int) -> Optional[int]:
    nb_addr = get_application_address(NOTICEBOARD_APP_ID)
    created = client.account_info(nb_addr).get("created-apps", []) or []
    for app in created:
        ad_id = app["id"]
        gs = app_global(client, ad_id).get("global-state", []) or []
        for e in gs:
            if base64.b64decode(e["key"]).decode(errors="ignore") == "del_app_list":
                blob = base64.b64decode(e["value"]["bytes"])
                if delco_id in decode_u64s(blob):
                    return ad_id
    return None

def nb_user_box(client: algod.AlgodClient, user_addr: str) -> bytes:
    raw_name = encoding.decode_address(user_addr)
    resp = client.application_box_by_name(NOTICEBOARD_APP_ID, raw_name)
    return base64.b64decode(resp["value"])

def true_index_from_box(buf: bytes, target_app_id: int, index_offset: int = INDEX_OFFSET) -> int:
    if len(buf) < index_offset + 8:
        raise RuntimeError(f"box too short ({len(buf)} bytes) for index_offset {index_offset}")
    slots = (len(buf) - index_offset) // 8
    for i in range(slots):
        if u64(buf, index_offset + 8*i) == target_app_id:
            return i
    raise RuntimeError("target app id not present in app_ids array")

# ----------------- main -----------------
def main():
    # signer/client
    sk   = mnemonic.to_private_key(SENDER_MN)
    addr = account.address_from_private_key(sk)
    signer = AccountTransactionSigner(sk)
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # discover validator ad (val_app) that lists this delco
    val_app = find_valad_for_delco(client, DELCO_APP_ID)
    if not val_app:
        print(f"ERROR: could not find validator ad for delco {DELCO_APP_ID}", file=sys.stderr)
        sys.exit(2)

    # actors from GS
    del_manager     = gs_addr(client, DELCO_APP_ID, "del_manager")
    del_beneficiary = gs_addr(client, DELCO_APP_ID, "del_beneficiary")
    val_owner       = gs_addr(client, val_app,      "val_owner")
    if not del_manager or not del_beneficiary or not val_owner:
        print("ERROR: missing del_manager / del_beneficiary / val_owner from GS", file=sys.stderr)
        sys.exit(2)

    # indices from Noticeboard user boxes (fixed app_ids array starting at INDEX_OFFSET)
    dm_box = nb_user_box(client, del_manager)
    vo_box = nb_user_box(client, val_owner)
    del_app_idx = true_index_from_box(dm_box, DELCO_APP_ID, INDEX_OFFSET)
    val_app_idx = true_index_from_box(vo_box, val_app,       INDEX_OFFSET)

    # args + context
    print("ARGS:")
    print(" del_manager =", del_manager)
    print(" del_app     =", DELCO_APP_ID, " idx =", del_app_idx)
    print(" val_owner   =", val_owner)
    print(" val_app     =", val_app,       " idx =", val_app_idx)
    print(" del_beneficiary =", del_beneficiary)
    # sanity check slots
    print("CHECK dm slot =", u64(dm_box, INDEX_OFFSET + 8*del_app_idx))
    print("CHECK vo slot =", u64(vo_box, INDEX_OFFSET + 8*val_app_idx))

    # build Noticeboard.breach_suspended(del_manager, del_app, del_app_idx, val_owner, val_app, val_app_idx)
    sp = client.suggested_params()
    sp.flat_fee = True
    sp.fee = 8 * sp.min_fee  # 1 outer + up to 7 inner = 8_000 µALGO

    method = Method.from_signature(
        "breach_suspended(address,application,uint64,address,application,uint64)"
        "((uint64,uint64,uint64),address,byte[100])"
    )

    boxes = [
        (NOTICEBOARD_APP_ID, encoding.decode_address(del_manager)),
        (NOTICEBOARD_APP_ID, encoding.decode_address(val_owner)),
    ]

    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id=NOTICEBOARD_APP_ID,
        method=method,
        method_args=[del_manager, DELCO_APP_ID, del_app_idx, val_owner, val_app, val_app_idx],
        sender=addr,
        sp=sp,
        signer=signer,
        on_complete=transaction.OnComplete.NoOpOC,
#        accounts=[del_beneficiary, del_manager, val_owner],  # beneficiary MUST be Txn.Accounts[0]
        accounts=[del_manager, val_owner, del_beneficiary],  # NB expects manager, owner, then beneficiary
        foreign_apps=[val_app, DELCO_APP_ID],
        boxes=boxes,
    )

    # send
#    res = atc.execute(client, 8)
#    print("breach_suspended txid:", res.tx_ids[0])

    signed_group = atc.gather_signatures()
    req = SimulateRequest(txn_groups=[SimulateRequestTransactionGroup(txns=signed_group)])
    sim = client.simulate_transactions(req)
    print(json.dumps(sim, indent=2))
    # When simulation shows success, you can switch back to:
    # res = atc.execute(client, 8)
    # print("breach_suspended txid:", res.tx_ids[0])

if __name__ == "__main__":
    main()
