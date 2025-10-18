#!/usr/bin/env python3
"""
sc_staking_status.py — Update delegator_contracts.staking_status with MINIMAL DB LOCKS

Decision tree per beneficiary (uses local algod first, Indexer only when needed):
  1) Read status + amount from LOCAL ALGOD.
     - If amount < 30,000 ALGO → "Not eligible" (no Indexer call)
     - If status == Online     → call Indexer once for incentive-eligible:
         • True  → "Eligible"
         • False → "Not eligible"
     - If status == Offline    → call Indexer once for incentive-eligible:
         • False → "Suspended"
         • True  → "Not eligible"
     - Else (e.g., NotParticipating) → "Not eligible" (no Indexer call)

Locking strategy:
  • Open a READ-ONLY connection to fetch all beneficiaries; close it.
  • For each address, do network calls (algod/indexer) with NO DB lock held.
  • For the UPDATE, open a short-lived AUTOCOMMIT connection, run one UPDATE with a WHERE
    that skips no-ops, then close immediately. This keeps write locks to milliseconds.

Logging and alerts:
  • Same log format as your other jobs (“=== scan start ===”, final summary).
  • Sends ONE alert e-mail and exits if the Indexer probe fails.
"""

import os, sys, json, gzip, sqlite3, logging, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from algosdk.v2client import algod

# ── Config (match your existing jobs) ─────────────────────────────────────
ALGOD_ADDRESS = "http://localhost:8080"
ALGOD_TOKEN   = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

DB_PATH  = os.getenv("VALAR_DB",  str(Path.home() / "ve2fet/valar_database/valar.db"))
LOG_DIR  = Path(os.getenv("VALAR_LOG", str(Path.home() / "ve2fet/dev"))).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "scan_staking_status.log"

INDEXER_URL   = os.getenv("INDEXER_URL", "https://mainnet-idx.4160.nodely.dev").rstrip("/")
INDEXER_TOKEN = os.getenv("INDEXER_TOKEN", "").strip()
MIN_ALGO      = int(os.getenv("MIN_ALGO", "30000"))
MIN_MICRO     = MIN_ALGO * 1_000_000

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("sc_staking_status")

# ── E-mail helper (same pattern) ─────────────────────────────────────────
def send_alert_email(subject: str, body: str, to_email: str | None = None) -> None:
    if to_email is None:
        to_email = "algo99uptime@yahoo.com"
    host = os.uname().nodename.upper()
    subj = f"[{host}] Valar: {subject}"
    body_esc = body.replace('"', r"\"")
    os.system(f"""~/bin/sendmail.sh "{to_email}" "{subj}" "$(printf '{body_esc}')" """)
    log.info("e-mail sent: %s", subj)

# ── HTTP (Indexer) ───────────────────────────────────────────────────────
def fetch_json(url: str, timeout: int = 20) -> dict | list:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "valar-staking-status/min-locks",
    }
    if INDEXER_TOKEN:
        headers["X-Algo-API-Token"] = INDEXER_TOKEN
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding", "").lower() == "gzip":
            data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))

def get_indexer_ie(addr: str, timeout: int = 15, retries: int = 1, backoff: float = 0.25) -> tuple[bool | None, str | None]:
    """Return (incentive_eligible, err). Treat missing field as False."""
    url = f"{INDEXER_URL}/v2/accounts/{addr}"
    last_err = None
    for a in range(retries + 1):
        try:
            j = fetch_json(url, timeout=timeout)
            acc = j.get("account", j if isinstance(j, dict) else {})
            ie = acc.get("incentive-eligible", acc.get("incentiveEligible", False))
            return bool(ie), None
        except (HTTPError, URLError) as e:
            last_err = f"http_error:{e}"
        except Exception as e:
            last_err = f"error:{e}"
        if a < retries:
            time.sleep(backoff * (a + 1))
    return None, last_err

# ── algod helpers ────────────────────────────────────────────────────────
def get_algod_status_amount(client: algod.AlgodClient, addr: str, retries: int = 2, backoff: float = 0.2) -> tuple[str | None, int | None, str | None]:
    """Return (status, amount_micro, err)."""
    last_err = None
    for a in range(retries + 1):
        try:
            info = client.account_info(addr)
            status = info.get("status")  # "Online"/"Offline"/"NotParticipating"
            amt = info.get("amount")
            if not isinstance(amt, int):
                awpr = info.get("amount-without-pending-rewards")
                amt = awpr if isinstance(awpr, int) else None
            return status, amt, None
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if a < retries:
            time.sleep(backoff * (a + 1))
    return None, None, last_err

# ── Classifier ───────────────────────────────────────────────────────────
def classify(status: str | None, ie: bool | None, amt_micro: int | None) -> str:
    if status is None or ie is None or amt_micro is None:
        return "Unknown"
    s = (status or "").lower()
    if s == "offline" and ie is False:
        return "Suspended"
    if s == "online" and ie is True and amt_micro >= MIN_MICRO:
        return "Eligible"
    return "Not eligible"

# ── Main ─────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=== scan start ===")

    # algod probe (we rely on it to minimize Indexer calls)
    try:
        algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        _ = algod_client.status()
    except Exception as e:
        log.error("algod unreachable at %s: %s", ALGOD_ADDRESS, e)
        sys.exit(2)

    # Indexer probe — send one alert and exit if down
    try:
        _ = fetch_json(f"{INDEXER_URL}/v2/assets?limit=1", timeout=8)
    except Exception as e:
        msg = f"Indexer unreachable: {INDEXER_URL}\n{e}"
        log.error(msg)
        send_alert_email("STAKE-STATUS: Indexer unreachable", msg)
        sys.exit(2)

    # --- READ PHASE: read beneficiaries via a read-only connection, then close ---
    conn_r = sqlite3.connect(DB_PATH)
    conn_r.row_factory = lambda cur, row: {col[0]: row[idx] for idx, col in enumerate(cur.description)}
    conn_r.execute("PRAGMA busy_timeout = 5000")
    conn_r.execute("PRAGMA query_only = ON")
    rows = conn_r.execute(
        "SELECT DISTINCT del_beneficiary AS addr "
        "FROM delegator_contracts "
        "WHERE del_beneficiary IS NOT NULL AND del_beneficiary <> ''"
    ).fetchall()
    conn_r.close()

    addrs = [r["addr"] for r in rows]

    updated = 0
    idx_calls = 0
    unknowns = 0
    errs_algod = 0
    errs_indexer = 0

    for addr in addrs:
        # 1) Cheap local read (no DB lock held)
        status, amt, aerr = get_algod_status_amount(algod_client, addr)
        if aerr:
            errs_algod += 1
            log.warning("algod_read addr=%s err=%s", addr, aerr)

        # Decide if we need Indexer
        new_status: str
        ie: bool | None = None
        ierr: str | None = None

        if status is not None and isinstance(amt, int):
            if amt < MIN_MICRO:
                new_status = "Not eligible"               # no Indexer call
                ie = True  # dummy to avoid Unknown in classify()
            else:
                s = (status or "").lower()
                if s == "online" or s == "offline":
                    ie, ierr = get_indexer_ie(addr)
                    idx_calls += 1
                    if ierr:
                        errs_indexer += 1
                        log.warning("indexer_ie addr=%s err=%s", addr, ierr)
                    new_status = classify(status, ie, amt)
                else:
                    # NotParticipating, etc. → not eligible
                    new_status = "Not eligible"
                    ie = True
        else:
            # Fallback: ask Indexer for ie + skip status/amount inference
            try:
                j = fetch_json(f"{INDEXER_URL}/v2/accounts/{addr}", timeout=15)
                idx_calls += 1
                acc = j.get("account", j if isinstance(j, dict) else {})
                s = acc.get("status")
                ie = bool(acc.get("incentive-eligible", acc.get("incentiveEligible", False)))
                amount = acc.get("amount")
                if not isinstance(amount, int):
                    amount = acc.get("amount-without-pending-rewards")
                    amount = amount if isinstance(amount, int) else None
                new_status = classify(s, ie, amount)
            except Exception as e:
                errs_indexer += 1
                log.warning("indexer_fallback addr=%s err=%s", addr, e)
                new_status = "Unknown"

        # 2) WRITE PHASE: short-lived autocommit connection; skip no-ops at SQL level
        try:
            conn_w = sqlite3.connect(DB_PATH, timeout=10)
            conn_w.row_factory = lambda cur, row: {col[0]: row[idx] for idx, col in enumerate(cur.description)}
            conn_w.execute("PRAGMA busy_timeout = 10000")
            conn_w.isolation_level = None  # autocommit: each UPDATE is its own txn

            before = conn_w.total_changes
            conn_w.execute(
                "UPDATE delegator_contracts "
                "SET staking_status=? "
                "WHERE del_beneficiary=? "
                "AND (staking_status IS NULL OR staking_status <> ?)",
                (new_status, addr, new_status),
            )
            updated += (conn_w.total_changes - before)
        except sqlite3.OperationalError as e:
            # If we ever hit a transient lock, log and move on (next run will catch up)
            log.warning("sqlite_write_locked addr=%s err=%s", addr, e)
        finally:
            try:
                conn_w.close()
            except Exception:
                pass

        if new_status == "Unknown":
            unknowns += 1

    log.info(
        "scan complete – %d addrs, updated=%d, idx_calls=%d, unknown=%d, algod_errors=%d, indexer_errors=%d",
        len(addrs), updated, idx_calls, unknowns, errs_algod, errs_indexer
    )

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("fatal error: %s", e)
        sys.exit(1)
