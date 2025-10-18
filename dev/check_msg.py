import os
import base64
import logging
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from algosdk.v2client import algod
import string

# ─── Configuration ─────────────────────────────────────────────────────
LOG_PATH = "/home/ve2pcq/ve2fet/dev/check_msg.log"
ROUND_FILE = "/home/ve2pcq/ve2fet/dev/check_msg.txt"

MONITORED_ADDRESSES = {
    "64MEIPURBOTSS3YI3WLHN77LSP5HUR3E5SFYT4ADUY6EKVOKYVUKHSJFTM",
    "CMQ6VSWMFA2PPXOPKVRBBRJCF5W4QBXMS53LO66CY2MMN3XP25345HBVQA",
    "5XXZWVTAVBEY4SBBCFUDQEMPM3MISMJ5DNFG6JBJDQZ6FI2PVQPZYF4JG4",
    "PWE6I2NRNQKP73A6Q5MYUYEW43F6YSK2ZOHQ6XOVNOIWA6B4D64ZFSD7QY",
}

ALGOD_ADDRESS = "http://localhost:8080"
ALGOD_TOKEN = "f9ba7e6e74c2a8d5c76acb3f0e6880e4dbc834f3006b154888baaa33687ef690"

# ─── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("check_msg")


# ─── Email Helper ────────────────────────────────────────────────────────
def send_alert_email(subject: str, body: str, to_email: str = "algo99uptime@yahoo.com") -> None:
    host = os.uname().nodename.upper()
    subj = f"[{host}] ALGORAND - Message: {subject}"
    body_esc = body.replace('%', '%%').replace('"', r'\"')
    os.system(f'~/bin/sendmail.sh "{to_email}" "{subj}" "$(printf \'{body_esc}\')"')
    log.info("e-mail sent: %s", subj)


# ─── Filtering ───────────────────────────────────────────────────────────
def looks_like_encoded_junk(text):
    return " " not in text

# ─── Setup ───────────────────────────────────────────────────────────────
client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
last_round = client.status()["last-round"]

# Read last scanned round
try:
    with open(ROUND_FILE, "r") as f:
        start_round = int(f.read().strip()) + 1
except FileNotFoundError:
    start_round = max(0, last_round - 1000)  # first run: scan last ~1000 rounds

if start_round > last_round:
    start_round = last_round

# ─── Main Loop ───────────────────────────────────────────────────────────
messages = []
for round_num in range(start_round, last_round + 1):
    try:
        block = client.block_info(round_num)
    except Exception:
        log.warning("Could not fetch block %d; stopping scan.", round_num)
        break

    txns = block.get("block", {}).get("txns", [])
    timestamp = block["block"]["ts"]
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)

    for txn in txns:
        txn_fields = txn.get("txn", {})

        note_b64 = txn_fields.get("note")
        if not note_b64:
            continue

        receiver = txn_fields.get("rcv") or txn_fields.get("arcv")
        sender = txn_fields.get("snd")

        if receiver not in MONITORED_ADDRESSES:
            continue

        try:
            note_bytes = base64.b64decode(note_b64)
            note_text = note_bytes.decode("utf-8", errors="replace").strip()
        except Exception:
            continue

        if (
            not note_text
            or not all(32 <= ord(c) <= 126 or c in "\t\n\r" for c in note_text)
            or looks_like_encoded_junk(note_text)
        ):
            continue

        msg = f"[{dt.isoformat()}] To: {receiver}\nFrom: {sender}\nNote: {note_text}\n"
        messages.append(msg)
        log.info("New message:\n%s", msg)

# ─── Post Processing ─────────────────────────────────────────────────────
if messages:
    body = "\n\n".join(messages)
    send_alert_email(subject=str(len(messages)), body=body)

# Always log that we ran
log.info("check_msg.py completed: scanned rounds %d to %d", start_round, last_round)

# Update last scanned round
with open(ROUND_FILE, "w") as f:
    f.write(str(last_round))
