# ~/ve2pcq/ve2fet/webapp/views/vmclients.py

from flask import Blueprint, render_template, request
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from db import DB_PATH, _algo, SECONDS_PER_ROUND

bp = Blueprint("vmclients", __name__, url_prefix="/vmclients")


@bp.route("/")
def page():
    # optional ?vm= filter
    vm_filter = request.args.get("vm", type=int)

    # fetch everything, including collected_at
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT vm_number, parent_address, last_round, collected_at "
        "FROM part_keys "
        "ORDER BY vm_number, parent_address"
    ).fetchall()]
    conn.close()

    # get current network round
    try:
        curr_round = _algo.status().get("last-round", 0)
    except:
        curr_round = 0

    # annotate expiry & time_left
    now = datetime.now(timezone.utc)
    for r in rows:
        lr = r["last_round"] or 0
        secs = max(0, (lr - curr_round) * SECONDS_PER_ROUND)
        exp = now + timedelta(seconds=secs)
        r["expiry"]    = exp
        d = int(secs // 86400)
        h = int((secs % 86400) // 3600)
        m = int((secs % 3600) // 60)
        r["time_left"] = f"{d}d {h}h {m}m"

    # compute "As of" from the latest collected_at
    if rows:
        latest = max(datetime.fromisoformat(r["collected_at"]) for r in rows)
        as_of = latest.strftime("%Y-%m-%d %H:%M:%S")
    else:
        as_of = "—"


    # group into blocks by vm_number (filtered if requested)
    if rows:
        vm_numbers = {r["vm_number"] for r in rows}
        min_vm, max_vm = min(vm_numbers), max(vm_numbers)
        full_range = range(min_vm, max_vm + 1)
    else:
        full_range = []

    blocks = []
    for vm in full_range:
        if vm_filter and vm != vm_filter:
            continue
        grp = [r for r in rows if r["vm_number"] == vm]
        blocks.append({
            "vm": vm,
            "count": len(grp),
            "keys": grp
        })

    # timestamp for "loaded since…"
    page_ts = int(time.time() * 1000)

    return render_template(
        "vmclients.html",
        as_of=as_of,
        blocks=blocks,
        vm_filter=vm_filter,
        page_ts=page_ts,
    )
