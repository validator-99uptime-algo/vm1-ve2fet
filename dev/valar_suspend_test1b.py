#!/usr/bin/env python3
"""
Test script: derive the two true indices Noticeboard expects for breach_suspended.
- Finds the Validator Ad (val_app) that lists your DelegatorContract (DELCO_APP_ID)
- Reads del_manager from the delco
- Reads the Noticeboard user boxes for del_manager and the val_app owner
- Computes byte-offset–based indices in users[addr].app_ids (fixed array)
- Prints: del_manager, del_app_idx, val_owner, val_app, val_app_idx

Reads only from your local algod. No transactions.
"""

import base64, sys
from typing import Optional, List

from algosdk.v2client import algod
from algosdk import encoding
from algosdk.logic import get_application_address

# ── CONFIG ───────────────────────────────────────────────────────────────
NOTICEBOARD_APP_ID = 2713948864
DELCO_APP_ID       = 3139255916

ALGOD_ADDRESS      = "http://localhost:8080"
ALGOD_TOKEN        = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

# In your deployment, users[addr].app_ids starts at byte offset 84 in the Noticeboard user box.
INDEX_OFFSET = 84  # header size before the fixed u64 app_ids array

# ── helpers ──────────────────────────────────────────────────────────────
def u64(b: bytes, ofs: int = 0) -> int:
    return int.from_bytes(b[ofs:ofs+8], "big")

def decode_u64s(buf: bytes, start: int = 0) -> List[int]:
    return [u64(buf, i) for i in range(start, len(buf)-7, 8)]

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
                ids = [u64(blob, i) for i in range(0, len(blob), 8) if i+8 <= len(blob)]
                if delco_id in ids:
                    return ad_id
    return None

def nb_user_box(client: algod.AlgodClient, user_addr: str) -> bytes:
    """Fetch raw Noticeboard user box value (box name = 32-byte raw address)."""
    raw_name = encoding.decode_address(user_addr)
    resp = client.application_box_by_name(NOTICEBOARD_APP_ID, raw_name)
    return base64.b64decode(resp["value"])

def true_index_from_box(buf: bytes, target_app_id: int, index_offset: int = INDEX_OFFSET) -> int:
    """Return the TRUE index in the fixed app_ids array by scanning from index_offset."""
    if len(buf) < index_offset + 8:
        raise RuntimeError(f"box too short ({len(buf)} bytes) for index_offset {index_offset}")
    if (len(buf) - index_offset) % 8 != 0:
        # not fatal; continue with floor division
        pass
    slots = (len(buf) - index_offset) // 8
    for i in range(slots):
        if u64(buf, index_offset + 8*i) == target_app_id:
            return i
    raise RuntimeError("target app id not present in app_ids array")

# ── main ─────────────────────────────────────────────────────────────────
def main():
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # 1) Find the Validator Ad (val_app) that lists this delco
    val_app = find_valad_for_delco(client, DELCO_APP_ID)
    if not val_app:
        print(f"ERROR: could not find validator ad for delco {DELCO_APP_ID}", file=sys.stderr)
        sys.exit(2)

    # 2) Read actors: del_manager from delco; val_owner from validator ad
    del_manager = gs_addr(client, DELCO_APP_ID, "del_manager")
    if not del_manager:
        print("ERROR: del_manager not found in delco global state", file=sys.stderr); sys.exit(2)

    val_owner = gs_addr(client, val_app, "val_owner")
    if not val_owner:
        print("ERROR: val_owner not found in validator ad global state", file=sys.stderr); sys.exit(2)

    # 3) Fetch both user boxes from Noticeboard
    dm_box = nb_user_box(client, del_manager)
    vo_box = nb_user_box(client, val_owner)

    # 4) Compute indices using absolute byte offset into the fixed app_ids array
    del_app_idx = true_index_from_box(dm_box, DELCO_APP_ID, INDEX_OFFSET)
    val_app_idx = true_index_from_box(vo_box, val_app,       INDEX_OFFSET)

    # 5) Print the values needed by Noticeboard.breach_suspended(...)
    print("del_manager:", del_manager)
    print("del_app    :", DELCO_APP_ID)
    print("del_app_idx:", del_app_idx)
    print("val_owner  :", val_owner)
    print("val_app    :", val_app)
    print("val_app_idx:", val_app_idx)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
