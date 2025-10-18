#!/usr/bin/env python3
"""
sc_staking_status.py — Update delegator_contracts.staking_status (minimize Indexer calls)

Decision tree per beneficiary:
  1) Read status + amount from LOCAL ALGOD.
     - If amount < 30,000 ALGO → "Not eligible" (no Indexer call)
     - If status == Online     → call Indexer once for incentive-eligible:
         • True  → "Eligible"
         • False → "Not eligible"
     - If status == Offline    → call Indexer once for incentive-eligible:
         • False → "Suspended"
         • True  → "Not eligible"
  2) Update only when value changes.
  3) Same logging format as your other jobs. Alert e-mail if Indexer is unreachable.

Env:
  VALAR_DB      (default: ~/ve2fet/valar_database/valar.db)
  VALAR_LOG     (default: ~/ve2fet/dev) → scan_staking_status.log
  INDEXER_URL   (default: https://mainnet-idx.4160.nodely.dev)
  INDEXER_TOKEN (optional; sent as X-Algo-API-Token)
  MIN_ALGO      (default: 30000)
"""

import os, sys, json, gzip, sqlite3, logging, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from algosdk.v2client import algod

# ── Config (match your existing scripts) ──────────────────────────────────
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

# ── Logging (same format) ────────────────────────────────────────────────
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("sc_staking_status")

# ── E-mail (same helper style) ───────────────────────────────────────────
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
        "User-Agent": "valar-staking-status/min-idx",
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

    # algod probe
    try:
        algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        _ = algod_client.status()
    except Exception as e:
        log.error("algod unreachable at %s: %s", ALGOD_ADDRESS, e)
        # No email requirement for algod per your instruction; continue only makes little sense.
        sys.exit(2)

    # Indexer reachability probe (send alert if down; exit)
    try:
        # Not all deployments expose /health; use a light endpoint as probe
        _ = fetch_json(f"{INDEXER_URL}/v2/assets?limit=1", timeout=8)
    except Exception as e:
        msg = f"Indexer unreachable: {INDEXER_URL}\n{e}"
        log.error(msg)
        send_alert_email("STAKE-STATUS: Indexer unreachable", msg)
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = lambda cur, row: {col[0]: row[idx] for idx, col in enumerate(cur.description)}
    conn.execute("PRAGMA busy_timeout = 5000")

    rows = conn.execute(
        "SELECT DISTINCT del_beneficiary AS addr "
        "FROM delegator_contracts "
        "WHERE del_beneficiary IS NOT NULL AND del_beneficiary <> ''"
    ).fetchall()
    addrs = [r["addr"] for r in rows]

    updated = 0
    idx_calls = 0
    unknowns = 0
    errs_algod = 0
    errs_indexer = 0

    for addr in addrs:
        # 1) Cheap local read
        status, amt, aerr = get_algod_status_amount(algod_client, addr)
        if aerr:
            errs_algod += 1
            log.warning("algod_read addr=%s err=%s", addr, aerr)

        new_status: str

        # If we have status+amount:
        if status is not None and isinstance(amt, int):
            if amt < MIN_MICRO:
                new_status = "Not eligible"          # no Indexer call
                ie, ierr = True, None                # dummy to avoid Unknown
            elif (status or "").lower() == "online":
                ie, ierr = get_indexer_ie(addr)      # one Indexer call
                idx_calls += 1
                if ierr:
                    errs_indexer += 1
                    log.warning("indexer_ie addr=%s err=%s", addr, ierr)
                new_status = classify(status, ie, amt)
            elif (status or "").lower() == "offline":
                ie, ierr = get_indexer_ie(addr)      # one Indexer call
                idx_calls += 1
                if ierr:
                    errs_indexer += 1
                    log.warning("indexer_ie addr=%s err=%s", addr, ierr)
                new_status = classify(status, ie, amt)
            else:
                # NotParticipating or anything else → not eligible
                new_status = "Not eligible"
                ie, ierr = True, None
        else:
            # Fall back: ask Indexer for ie + also status/amount if algod failed badly
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

        # Skip no-op updates

        row = conn.execute(
            "SELECT staking_status FROM delegator_contracts WHERE del_beneficiary=? LIMIT 1",
            (addr,),
        ).fetchone()
        old = row["staking_status"] if row else None
        if old != new_status:
            before = conn.total_changes
            conn.execute(
                "UPDATE delegator_contracts SET staking_status=? WHERE del_beneficiary=?",
                (new_status, addr),
            )
            updated += (conn.total_changes - before)  # exact number of rows actually changed

        if new_status == "Unknown":
            unknowns += 1

    conn.commit()
    conn.close()

    log.info("scan complete – %d addrs, updated=%d, idx_calls=%d, unknown=%d, algod_errors=%d, indexer_errors=%d",
             len(addrs), updated, idx_calls, unknowns, errs_algod, errs_indexer)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("fatal error: %s", e)
        sys.exit(1)
