#!/usr/bin/env python3
# susp_scan.py — scan block headers for participation updates after the protocol switch
# Local node only. Append results to CSV and store resume state.

import os, json, csv, time, requests

# --- CONFIG (set these) ---
ALGOD_ADDRESS = "http://localhost:8080"
ALGOD_TOKEN   = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"   # put your local node token here
SWITCH_ROUND  = 54013201                  # <-- SET THIS ONCE to the first post-upgrade round

# --- Files ---
STATE_PATH = "susp_scan_state.json"
OUT_CSV    = "susp_updates.csv"

H = {"X-Algo-API-Token": ALGOD_TOKEN}

def get_last_round():
    r = requests.get(f"{ALGOD_ADDRESS}/v2/status", headers=H, timeout=8)
    r.raise_for_status()
    return r.json()["last-round"]

def get_block_header(rnd: int):
    # FETCH FULL BLOCK (NOT header-only) so participation-updates are present
    r = requests.get(f"{ALGOD_ADDRESS}/v2/blocks/{rnd}?format=json", headers=H, timeout=8)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    # Some nodes return {"block": {...}}; normalize to the inner dict
    b = r.json()
    return b.get("block", b)

def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, "r") as f:
        return json.load(f)

def save_state(next_round: int):
    tmp = {"next_round": next_round, "saved_at": int(time.time())}
    with open(STATE_PATH, "w") as f:
        json.dump(tmp, f)

def ensure_csv():
    if not os.path.exists(OUT_CSV):
        with open(OUT_CSV, "w", newline="") as f:
            w = csv.writer(f)
            # generic columns: round, kind (key under participation-updates), value (address/entry), raw_json
            w.writerow(["round", "kind", "value", "raw"])

def main():
    ensure_csv()
    st = load_state()
    start = st["next_round"] if st and "next_round" in st else SWITCH_ROUND
    last  = get_last_round()

    if start > last:
        # Nothing to do (already caught up)
        print(f"Up to date. next_round={start}, last={last}")
        return

    wrote = 0
    with open(OUT_CSV, "a", newline="") as f:
        w = csv.writer(f)
        for rnd in range(start, last + 1):
            try:
                hdr = get_block_header(rnd)
                if not hdr:
                    continue

                # Look for participation-update arrays at the root of the block JSON
                # e.g., keys like 'partupdabs', and possibly others starting with 'partupd'
                updates = []
                for k, v in hdr.items():
                    if k.startswith("partupd") and isinstance(v, list) and v:
                        updates.append((k, v))

                if not updates:
                    continue

                for k, v in updates:
                    for entry in v:
                        w.writerow([rnd, k, str(entry), ""])
                        wrote += 1

            except requests.RequestException:
                # transient; skip this round
                continue

    # Save resume state
    save_state(last + 1)
    print(f"Scanned rounds {start}..{last}. New rows: {wrote}. Next start: {last+1}")

if __name__ == "__main__":
    main()
