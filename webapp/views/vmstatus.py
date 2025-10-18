# /home/ve2pcq/ve2fet/webapp/views/vmstatus.py
import os, json, datetime
from flask import Blueprint, render_template

bp = Blueprint("vmstatus", __name__, url_prefix="/vmstatus")

# Path to the collector's aggregate file
FLEET_JSON = os.path.expanduser("~/ve2fet/webapp/vmmonitor/output/fleet-status.json")

def _fmt_epoch(epoch: int) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"

def _human_uptime(seconds: int) -> str:
    try:
        s = int(seconds)
    except Exception:
        return "?"
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"

@bp.route("/")
def page():
    hosts = []
    generated_at_epoch = 0
    load_error = ""

    try:
        with open(FLEET_JSON, "r") as f:
            hosts = json.load(f)
        generated_at_epoch = int(os.path.getmtime(FLEET_JSON))
#        generated_at = _fmt_epoch(os.path.getmtime(FLEET_JSON))
        # sort for stable view

        import re
        def _natkey(h):
            s = h.get("hostname", "")
            m = re.search(r"(\d+)$", s)
            return (re.sub(r"\d+$", "", s).lower(), int(m.group(1)) if m else -1)

        hosts.sort(key=_natkey)
#        hosts.sort(key=lambda h: h.get("hostname", ""))

    except Exception as e:
        load_error = str(e)

    return render_template(
        "vmstatus.html",
        hosts=hosts,
        generated_at_epoch=generated_at_epoch,
        load_error=load_error,
        _human_uptime=_human_uptime,
    )
