#!/usr/bin/env python3
"""
sc_val1.py  –  Valar Validator-Ad watcher

 • Discovers every Validator-Ad created by the Valar Noticeboard (app-id 2713948864)
 • Mirrors their on-chain global state into the validator_ads table
 • Keeps the currencies table in sync
 • E-mails + logs when
       – a brand-new Ad appears   (after the initial load)
       – any of six live pricing / stake-limit fields change
 • Updates sys_meta (task_id = 1)

Env vars
────────
VALAR_DB  – SQLite file path   (default ~/ve2fet/valar_database/valar.db)
VALAR_LOG – **directory** in which the script will create scan_validators.log
"""

import os, sys, base64, sqlite3, logging, math
from pathlib import Path
from typing  import Dict, List, Any

from algosdk.v2client import algod
from algosdk.encoding import encode_address
from algosdk.logic    import get_application_address


# ─── Constants ───────────────────────────────────────────────────────────
TASK_ID            = 1
NOTICEBOARD_APP_ID = 2713948864
ALGOD_ADDRESS      = "http://localhost:8080"
ALGOD_TOKEN        = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"
SECONDS_PER_ROUND = 2.8              # main-net average

WATCHED_FIELDS = [
    "state",
    "fee_asset_id",
    "fee_setup",
    "fee_round_min",
    "fee_round_var",
    "stake_max",
    "gratis_stake_ppm",
    "cnt_del",
    "cnt_del_max",
]

DB_PATH  = os.getenv("VALAR_DB",
                     str(Path.home() / "ve2fet/valar_database/valar.db"))
LOG_DIR  = Path(os.getenv("VALAR_LOG",
                          str(Path.home() / "ve2fet/dev"))).expanduser()
LOG_PATH = LOG_DIR / "scan_validators.log"

LOG_DIR.mkdir(parents=True, exist_ok=True)          # be safe


# ─── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("sc_val1")


# ─── simple e-mail helper ─────────────────────────────────────────────
def send_alert_email(subject: str,
                     body: str,
                     to_email: str = "algo99uptime@yahoo.com") -> None:
    """
    Tiny wrapper around ~/bin/sendmail.sh so the script can alert you.
    """
    host = os.uname().nodename.upper()
    subj = f"[{host}] Valar: {subject}"
    body_esc = body.replace('%', '%%').replace('"', r'\"')
    # body_esc = body.replace('"', r"\"")
    os.system(f'~/bin/sendmail.sh "{to_email}" "{subj}" "$(printf \'{body_esc}\')"')
    log.info("e-mail sent: %s", subj)


# ─── Helpers ────────────────────────────────────────────────────────────
def _u64(b: bytes, ofs: int = 0) -> int:
    return int.from_bytes(b[ofs:ofs+8], "big")

def decode_uint64_list(b: bytes) -> List[int]:
    return [_u64(b, i) for i in range(0, len(b), 8) if i+8 <= len(b)]

def decode_global_state(gs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for entry in gs:
        key = base64.b64decode(entry["key"]).decode()
        val = entry["value"]
        if val["type"] == 2:                      # uint64
            out[key] = val["uint"]
        else:                                     # bytes
            b = base64.b64decode(val["bytes"])
            if len(b) == 32 and key in ("val_owner", "val_manager"):
                try:
                    out[key] = encode_address(b)
                except Exception:
                    out[key] = b.hex()
            elif key in ("P", "T", "W", "S", "del_app_list"):
                out[key] = decode_uint64_list(b)
            else:
                out[key] = b.hex()
    return out


# human-friendly conversions --------------------------------------------
def _algo(x_micro: int | None) -> str:
    return f"{x_micro/1_000_000:,.2f} ALGO" if x_micro else ""

def _ppm(x: int | None) -> str:
    return f"{x/10_000:,.1f} %" if x is not None else ""


# DB helpers -------------------------------------------------------------
def dict_factory(cur, row):
    return {col[0]: row[idx] for idx, col in enumerate(cur.description)}

def ensure_currency(conn: sqlite3.Connection, client: algod.AlgodClient,
                    asset_id: int):
    if asset_id == 0:
        conn.execute("INSERT OR IGNORE INTO currencies "
                     "(asset_id,symbol,decimals) VALUES (0,'ALGO',6)")
        conn.commit()
        return
    if conn.execute("SELECT 1 FROM currencies WHERE asset_id=?",
                    (asset_id,)).fetchone():
        return
    try:
        params  = client.asset_info(asset_id)["params"]
        symbol  = params.get("unit-name", f"ASA{asset_id}")
        decimals = params["decimals"]
    except Exception:
        symbol, decimals = f"ASA{asset_id}", 0
    conn.execute("INSERT OR IGNORE INTO currencies "
                 "(asset_id,symbol,decimals) VALUES (?,?,?)",
                 (asset_id, symbol, decimals))
    conn.commit()

# ─── Main scan routine ──────────────────────────────────────────────────
def main() -> None:
    log.info("=== scan start ===")
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    this_round = client.status()["last-round"]

    nb_addr = get_application_address(NOTICEBOARD_APP_ID)
    ad_ids  = [app["id"] for app in
               client.account_info(nb_addr).get("created-apps", [])]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA busy_timeout = 10000")

    meta = conn.execute(
            "SELECT last_scanned_round FROM sys_meta WHERE task_id=?",
            (TASK_ID,)).fetchone()
    first_run = meta is None or meta["last_scanned_round"] == 0

    alerts: list[str] = []

    for aid in ad_ids:
        try:
            gs = client.application_info(aid)["params"].get("global-state", [])
        except Exception as e:
            log.warning("skip app %s: %s", aid, e)
            continue

        ad = decode_global_state(gs)

        # currency row
        if "P" in ad and len(ad["P"]) >= 5:
            ensure_currency(conn, client, ad["P"][4])

        row = {
            "ad_id": aid,
            "val_owner": ad.get("val_owner"),
            "val_manager": ad.get("val_manager"),
            "state": f"{int(ad.get('state', 0)):02d}",
            "cnt_del": ad.get("cnt_del"),
            "cnt_del_max": ad.get("cnt_del_max"),
            "noticeboard_app_id": ad.get("noticeboard_app_id"),
            "tc_sha256": ad.get("tc_sha256"),
            "total_algo_earned": ad.get("total_algo_earned"),
            "total_algo_fees_generated": ad.get("total_algo_fees_generated"),
            "created_at_round": ad.get("created_at_round"),
            "updated_at_round": this_round,
            "commission_ppm": ad.get("commission_ppm"),
            # P-array
            "fee_round_min": ad.get("P", [None, 0])[1] if "P" in ad else None,
            "fee_round_var": ad.get("P", [None, None, 0])[2] if "P" in ad else None,
            "fee_setup":     ad.get("P", [None, None, None, 0])[3] if "P" in ad else None,
            "fee_asset_id":  ad.get("P", [None, None, None, None, 0])[4] if "P" in ad else None,
            # T-array
            "valid_until_round":  ad.get("T", [None, None, None, None, 0])[4] if "T" in ad else None,
            "min_duration_rounds":ad.get("T", [None, None,          0])[2] if "T" in ad else None,
            "max_duration_rounds":ad.get("T", [None, None, None,    0])[3] if "T" in ad else None,
            "setup_time_rounds":  ad.get("T", [0])[0]                 if "T" in ad else None,
            "confirm_time_rounds":ad.get("T", [None, 0])[1]           if "T" in ad else None,
            # S-array
            "stake_max":       ad.get("S", [0])[0]  if "S" in ad else None,
            "gratis_stake_ppm":ad.get("S", [None,0])[1] if "S" in ad else None,
            # W-array
            "warning_max":     ad.get("W", [0])[0]  if "W" in ad else None,
            "warning_time_rounds": ad.get("W", [None,0])[1] if "W" in ad else None,
        }

        old = conn.execute("SELECT * FROM validator_ads WHERE ad_id=?",
                           (aid,)).fetchone()

        # ---------- new ad -------------------------------------------------
        if old is None:
            conn.execute(f"INSERT INTO validator_ads ({','.join(row.keys())}) "
                         f"VALUES ({','.join('?'*len(row))})",
                         tuple(row.values()))
            conn.commit()
            log.info("NEW Validator-Ad discovered: %s", aid)

            if not first_run:
                fee_sym  = "ALGO" if row["fee_asset_id"] == 0 else f"ASA{row['fee_asset_id']}"
                dec      = 6                              # ALGO & USDC both use 6-decimals
                rounds_pm = int((30 * 24 * 3600) / SECONDS_PER_ROUND)   # ≈ 926 k rounds / 30 d

                setup    = row["fee_setup"]       / 10**dec
                op_min   = math.ceil(row["fee_round_min"] * rounds_pm / 1000) / 10**dec
                op_var   = math.ceil(row["fee_round_var"] * rounds_pm * 100_000 / 1_000_000_000) / 10**dec
                stake    = row["stake_max"]       / 1_000_000
                gratis   = row["gratis_stake_ppm"] / 10_000          # → %

                alerts.append(
                    f"NEW Validator-Ad {aid}\n"
                    f" • Owner        : {row['val_owner']}\n"
                    f" • Setup fee    : {setup:,.2f} {fee_sym}\n"
                    f" • Min op fee   : {op_min:,.2f} {fee_sym}/mo\n"
                    f" • Var op fee   : {op_var:,.2f} {fee_sym}/mo per 100k ALGO\n"
                    f" • Max stake    : {stake:,.0f} ALGO\n"
                    f" • Gratis stake : {gratis:.1f} %\n"
                )
                log.info(alerts[-1].replace("\n", " | "))

        # ---------- existing ad -------------------------------------------
        else:
            changed = {k: (old[k], row[k])
                       for k in WATCHED_FIELDS if old[k] != row[k]}
            if changed:
                # DB update
                set_clause = ", ".join(f"{k}=?" for k in row)
                conn.execute(f"UPDATE validator_ads SET {set_clause} WHERE ad_id=?",
                             tuple(row.values()) + (aid,))
                conn.commit()
                # pretty diff ------------------------------------------------
                rounds_pm = int((30*24*3600) / SECONDS_PER_ROUND)    # ≈ 926 000 rounds / 30 days

                diff_lines = []
                for fld, (prev, new) in changed.items():
                # ── pretty diff ─────────────────────────────────────
                    if fld == "fee_round_min":
                        p_prev = _algo(math.ceil(prev * rounds_pm / 1000))
                        p_new  = _algo(math.ceil(new  * rounds_pm / 1000))
                    elif fld == "fee_round_var":
                        p_prev = _algo(math.ceil(prev * rounds_pm * 100_000 / 1_000_000_000))
                        p_new  = _algo(math.ceil(new  * rounds_pm * 100_000 / 1_000_000_000))
                    elif fld in {"fee_setup", "stake_max"}:
                        p_prev, p_new = _algo(prev), _algo(new)
                    elif fld == "gratis_stake_ppm":
                        p_prev, p_new = _ppm(prev), _ppm(new)
                    else:                         # asset-ID or something rare
                        p_prev, p_new = prev, new

                    diff_lines.append(f" • {fld}: {p_prev} → {p_new}")

                    log.info("CHANGE ad=%s field=%s %s → %s",
                             aid, fld, p_prev, p_new)

                alerts.append(f"Validator-Ad {aid} changed:\n" +
                              "\n".join(diff_lines))
            # else:
            #    conn.execute("UPDATE validator_ads SET updated_at_round=? "
            #                 "WHERE ad_id=?",
            #                 (this_round, aid))
            #    conn.commit()

    # ---------- sys_meta --------------------------------------------------
    conn.execute("""
        INSERT INTO sys_meta(task_id,last_scanned_round,last_checked_at)
        VALUES (?,?,datetime('now'))
        ON CONFLICT(task_id) DO UPDATE SET
            last_scanned_round = excluded.last_scanned_round,
            last_checked_at    = excluded.last_checked_at
    """, (TASK_ID, this_round))
    conn.commit()
    conn.close()

    if alerts and not first_run:
        send_alert_email("VALIDATOR-Ad WATCHER", "\n\n".join(alerts))

    log.info("scan complete – %d ads, %d alerts", len(ad_ids), len(alerts))


# ─── entry-point ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("fatal error: %s", e)
        sys.exit(1)
